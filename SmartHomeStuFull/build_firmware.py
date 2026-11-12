"""Assemble the public extensions with a locally obtained course starter and build with XC8."""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
LOCAL = HERE / "_work"
BASE = LOCAL / "config.mcc"
DFP_VERSION = "1.30.487"
AUDIO = {
    "welcome_pcm": ("g_welcomeAudio", (523.25, 659.25, 783.99)),
    "smart_home_melody_pcm": ("g_smartHomeMelodyAudio", (659.25, 523.25, 587.33, 783.99)),
}


def write_audio(stem: str, symbol: str, notes: tuple[float, ...]) -> None:
    samples: list[int] = []
    for hz in notes:
        for index in range(800):
            envelope = min(1.0, index / 80, (799 - index) / 140)
            samples.append(round(128 + 56 * envelope * math.sin(math.tau * hz * index / 8000)))
        samples.extend([128] * 200)
    rows = ["    " + ", ".join(str(n) for n in samples[i:i + 16]) + ","
            for i in range(0, len(samples), 16)]
    text = (f'#include "{stem}.h"\n\nconst uint8_t {symbol}[] = {{\n'
            + "\n".join(rows)
            + f"\n}};\nconst uint32_t {symbol}Length = (uint32_t)sizeof({symbol});\n")
    (BASE / "resource" / f"{stem}.c").write_text(text, encoding="utf-8", newline="\n")


def prepare(base_archive: Path) -> None:
    spec = json.loads((HERE / "integration.json").read_text(encoding="utf-8"))
    data = base_archive.read_bytes()
    if sha256(data).hexdigest() != spec["archive_sha256"]:
        raise ValueError("Course starter archive does not match the version in integration.json.")
    expected: dict[str, bytes] = {}
    skipped = {f"resource/{stem}.c" for stem in AUDIO}
    with ZipFile(BytesIO(data)) as archive:
        for entry in archive.namelist():
            if not entry.startswith("SmartHome/config.mcc/") or not entry.endswith((".c", ".h")):
                continue
            name = entry.removeprefix("SmartHome/config.mcc/")
            if name in skipped:
                continue
            raw = archive.read(entry).replace(b"\r\n", b"\n")
            if (change := spec["files"].get(name)) is not None:
                if sha256(raw).hexdigest() != change["base_sha256"]:
                    raise ValueError(f"Course file does not match the expected version: {name}")
                lines = raw.decode("utf-8").splitlines(keepends=True)
                blocks: list[str] = []
                index = 0
                for start, end, replacement in change["edits"]:
                    if not index <= start <= end <= len(lines):
                        raise ValueError(f"Invalid edit range for {name}")
                    blocks.extend(lines[index:start])
                    blocks.append(replacement)
                    index = end
                blocks.extend(lines[index:])
                raw = "".join(blocks).encode("utf-8")
                if sha256(raw).hexdigest() != change["output_sha256"]:
                    raise ValueError(f"Integrated file failed verification: {name}")
            expected[name] = raw
    if not set(spec["files"]) <= expected.keys():
        raise ValueError("A course file required by the integration is missing.")
    for name, raw in expected.items():
        output = BASE / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw)
    for source in (HERE / "config.mcc").rglob("*"):
        if source.is_file() and source.suffix in (".c", ".h"):
            output = BASE / source.relative_to(HERE / "config.mcc")
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, output)
    for stem, (symbol, notes) in AUDIO.items():
        write_audio(stem, symbol, notes)


def build(compiler: str, pack: Path) -> None:
    xc8 = shutil.which(compiler)
    if xc8 is None:
        raise ValueError("XC8 compiler not found. Install XC8 3.10 and use --xc8 or add xc8-cc to PATH.")
    if not pack.is_dir():
        raise ValueError(f"PIC18F-Q device pack not found at {pack}. Pass the pack's xc8 directory with --dfp.")
    obj_dir = LOCAL / "obj"
    out_dir = LOCAL / "out"
    obj_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    flags = ["-mcpu=18F57Q43", f"-mdfp={pack.resolve()}", "-fno-short-double",
             "-fno-short-float", "-memi=wordwrite", "-O0", "-maddrqual=ignore", "-mwarn=-3",
             "-ginhx32", "-Wl,--data-init", "-mno-keep-startup", "-mno-download",
             "-mno-default-config-bits", "-std=c99", "-gdwarf-3", "-mstack=compiled:auto:auto:auto"]
    includes = [f"-I{BASE / folder}" for folder in ("", "app", "device_driver", "service", "resource")]
    objects = []
    for source in sorted(BASE.rglob("*.c")):
        target = obj_dir / ("-".join(source.relative_to(BASE).with_suffix("").parts) + ".p1")
        subprocess.run([xc8, *flags, *includes, "-DXPRJ_default=default",
                        "-c", str(source), "-o", str(target)], cwd=obj_dir, check=True)
        objects.append(str(target))
    subprocess.run([xc8, *flags, "-Wl,-Map=mem.map", "-Wl,--defsym=__MPLAB_BUILD=1",
                    "-msummary=-psect,-class,+mem,-hex,-file", *objects, "-o", "default.elf"],
                   cwd=out_dir, check=True)
    for name in ("default.hex", "default.elf"):
        product = out_dir / name
        if not product.is_file() or product.stat().st_size == 0:
            raise ValueError(f"Compiler did not produce {product}")
        print(product)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-archive", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--xc8", default=os.environ.get("XC8_CC", "xc8-cc"))
    parser.add_argument("--dfp", type=Path, default=Path.home() / ".mchp_packs" / "Microchip" /
                        "PIC18F-Q_DFP" / DFP_VERSION / "xc8")
    args = parser.parse_args()
    try:
        prepare(args.base_archive)
        if args.prepare_only:
            print(BASE)
        else:
            build(args.xc8, args.dfp)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Firmware preparation/build failed: {error}\n")


if __name__ == "__main__":
    main()
