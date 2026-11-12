"""Browse original lab additions; verify or build them against a local course starter."""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent / "SmartHomeStuFull"
MARKER = re.compile(r"/\* TODO\[(S\d{2}-\d{2})\] BEGIN.*?/\* TODO\[\1\] END \*/", re.S)


def load() -> tuple[dict, dict]:
    index = json.loads((HERE / "index.json").read_text(encoding="utf-8"))
    data = (FIRMWARE / "integration.json").read_bytes()
    if sha256(data).hexdigest() != index["integration_sha256"]:
        raise ValueError("integration.json changed; review and update the BasicLabs index first.")
    return index, json.loads(data)


def additions(block: dict, spec: dict) -> str:
    edits = spec["files"][block["source"]]["edits"]
    return "".join(edits[i][2] for i in block["edits"])


def show(index: dict, spec: dict, stage: int | None, ident: str | None) -> None:
    selected = [block for item in index["stages"] for block in item["blocks"]
                if (stage is None or item["stage"] == stage) and (ident is None or block["id"] == ident)]
    if not selected:
        raise ValueError("No matching lab block.")
    for block in selected:
        print(f"## {block['id']} {block['title']}\n\nSource: {block['source']}\n")
        print("```c\n" + textwrap.dedent(additions(block, spec)).strip() + "\n```\n")


def verify(index: dict, spec: dict, archive_path: Path, source_root: Path | None) -> None:
    archive_data = archive_path.read_bytes()
    if sha256(archive_data).hexdigest() != spec["archive_sha256"]:
        raise ValueError("Course starter archive does not match the integration version.")
    lookup = {block["id"]: block for item in index["stages"] for block in item["blocks"]}
    if len(lookup) != sum(len(item["blocks"]) for item in index["stages"]):
        raise ValueError("Duplicate block identifiers.")
    found = set()
    source_checks = 0
    with ZipFile(BytesIO(archive_data)) as archive:
        for name, change in spec["files"].items():
            raw = archive.read("SmartHome/config.mcc/" + name).replace(b"\r\n", b"\n")
            if sha256(raw).hexdigest() != change["base_sha256"]:
                raise ValueError(f"Course source checksum mismatch: {name}")
            text = raw.decode("utf-8")
            for match in MARKER.finditer(text):
                ident = match[1]
                block = lookup.get(ident)
                if block is None or block["source"] != name:
                    raise ValueError(f"Missing or incorrect source mapping: {ident}")
                first = text.count("\n", 0, match.start())
                end = text.count("\n", 0, match.end()) + 1
                for i in block["edits"]:
                    start, stop, replacement = change["edits"][i]
                    if block.get("placement") == "after-end-marker":
                        valid = start == stop == end
                    else:
                        valid = first <= start < end or start < first < stop
                    if not valid or not replacement.strip():
                        raise ValueError(f"Edit is not at the expected block: {ident}, edit {i}")
                if not re.sub(r"/\*.*?\*/|//[^\n]*", "", additions(block, spec), flags=re.S).strip():
                    raise ValueError(f"No executable additions: {ident}")
                found.add(ident)
            lines = text.splitlines(keepends=True)
            result: list[str] = []
            cursor = 0
            for start, end, replacement in change["edits"]:
                if not cursor <= start <= end <= len(lines):
                    raise ValueError(f"Invalid integration range: {name}")
                result.extend(lines[cursor:start])
                result.append(replacement)
                cursor = end
            result.extend(lines[cursor:])
            integrated = "".join(result).encode("utf-8")
            if sha256(integrated).hexdigest() != change["output_sha256"]:
                raise ValueError(f"Integrated source checksum mismatch: {name}")
            if source_root is not None:
                actual = (source_root / name).read_bytes().replace(b"\r\n", b"\n")
                if integrated != actual:
                    raise ValueError(f"Integration differs from the actual project: {name}")
                source_checks += 1
    if found != lookup.keys():
        raise ValueError(f"Unknown index entries: {lookup.keys() - found}")
    counts = [sum(int(ident[1:3]) == stage for ident in found) for stage in range(1, 10)]
    if counts != [3, 3, 9, 7, 8, 6, 12, 5, 5]:
        raise ValueError(f"Unexpected stage coverage: {counts}")
    print(f"Verified {len(found)} lab additions; stage counts: {counts}.")
    print(f"All {len(spec['files'])} integrated source checksums match.")
    if source_root is not None:
        print(f"All {source_checks} integrated files match the actual project source.")


def build(args: argparse.Namespace) -> None:
    module_spec = importlib.util.spec_from_file_location("smarthome_firmware_build", FIRMWARE / "build_firmware.py")
    if module_spec is None or module_spec.loader is None:
        raise ValueError("Cannot load the firmware build entry point.")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    # Keep each lab's local, non-public assembled source and outputs separate.
    module.LOCAL = HERE / "_work" / f"stage-{args.stage:02d}"
    module.BASE = module.LOCAL / "config.mcc"
    module.prepare(args.base_archive)
    for filename, pattern, replacement in (
        ("lab_config.h", r"^#define LAB_STAGE \d+$", f"#define LAB_STAGE {args.stage}"),
        ("extension_config.h", r"^#define SMART_HOME_EXTENSIONS_ENABLE 1$", "#define SMART_HOME_EXTENSIONS_ENABLE 0"),
    ):
        path = module.BASE / filename
        output, count = re.subn(pattern, replacement, path.read_text(encoding="utf-8"), flags=re.M)
        if count != 1:
            raise ValueError(f"Stage selection setting changed: {filename}")
        path.write_text(output, encoding="utf-8", newline="\n")
    print(f"LAB_STAGE={args.stage}; SMART_HOME_EXTENSIONS_ENABLE=0", flush=True)
    if args.prepare_only:
        print(module.BASE)
    else:
        module.build(args.xc8, args.dfp)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    browse = commands.add_parser("show", help="Print additions from integration.json without copying course files.")
    selection = browse.add_mutually_exclusive_group()
    selection.add_argument("--stage", type=int, choices=range(1, 10))
    selection.add_argument("--block", help="For example S03-07.")
    check = commands.add_parser("verify", help="Check all 58 mappings against the local starter archive.")
    check.add_argument("--base-archive", type=Path, required=True)
    check.add_argument("--source-root", type=Path, help="Optional config.mcc directory from the actual project.")
    firmware = commands.add_parser("build", help="Assemble and build one basic lab stage with extensions disabled.")
    firmware.add_argument("--stage", type=int, choices=range(1, 10), required=True)
    firmware.add_argument("--base-archive", type=Path, required=True)
    firmware.add_argument("--prepare-only", action="store_true")
    firmware.add_argument("--xc8", default=os.environ.get("XC8_CC", "xc8-cc"))
    firmware.add_argument("--dfp", type=Path, default=Path.home() / ".mchp_packs" / "Microchip" /
                          "PIC18F-Q_DFP" / "1.30.487" / "xc8")
    args = parser.parse_args()
    try:
        index, spec = load()
        if args.command == "show":
            show(index, spec, args.stage, args.block)
        elif args.command == "verify":
            verify(index, spec, args.base_archive, args.source_root)
        else:
            verify(index, spec, args.base_archive, None)
            build(args)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"BasicLabs failed: {error}\n")


if __name__ == "__main__":
    main()
