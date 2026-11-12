"""Native tests run the production SH1 transport in a DLL with fake UART I/O.

No MCU or serial port is accessed. Python's production STATE parser validates
the actual C transport's emitted STATE. Run with the SmartHomeHost venv Python.
"""
from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
WORKSPACE = PROJECT.parent
SOURCE = Path(os.environ.get('SMARTHOME_FIRMWARE_SOURCE', PROJECT / '_work/config.mcc'))
sys.path.insert(0, str(WORKSPACE / "SmartHomeHost"))
from smarthome.protocol import parse, validate_state


def build(clang_dir: Path) -> Path:
    output = HERE / ".build"
    output.mkdir(exist_ok=True)
    sources = [HERE / "serial_fixture.c", SOURCE / "service/host_serial.c"]
    includes = [HERE / "stubs", SOURCE, SOURCE / "service", SOURCE / "app", SOURCE / "device_driver"]
    objects = []
    for source in sources:
        target = output / (source.stem + ".obj")
        command = [str(clang_dir / "clang.exe"), "-std=c99", "-ffreestanding", "-fno-builtin",
                   "-fno-stack-protector", "-Wall", "-Wextra", "-Werror", "-O1"]
        for include in includes:
            command += ["-I", str(include)]
        subprocess.run(command + ["-c", str(source), "-o", str(target)], check=True)
        objects.append(str(target))
    exports = ["Test_Reset", "Test_Input", "Test_Task", "Test_Output", "Test_ClearOutput",
               "Test_CommandCalls", "Test_RxOverflows", "Test_Rejects", "Test_SetTxReady",
               "Test_UnknownInputs"]
    library = output / "serial_test.dll"
    subprocess.run([str(clang_dir / "lld.exe"), "-flavor", "link", "/dll", "/noentry",
                    "/nodefaultlib", f"/out:{library}", *[f"/export:{name}" for name in exports],
                    *objects], check=True)
    return library


class SerialTests(unittest.TestCase):
    nonce = "0123456789abcdef0123456789abcdef"
    lib: ctypes.CDLL

    def setUp(self):
        self.now = 0
        self.client = self.nonce
        self.lib.Test_Reset(0)

    def tick(self, count=40):
        for _ in range(count):
            self.now += 1
            self.lib.Test_Task(self.now)

    def feed(self, data: bytes, *, drain=True):
        for offset in range(0, len(data), 8):
            part = data[offset:offset+8]
            self.lib.Test_Input(part, len(part))
            if drain:
                self.tick(1)
        if drain:
            self.tick()

    def frames(self):
        return [parse(line) for line in self.lib.Test_Output().splitlines()]

    def hello(self, nonce=None):
        self.client = nonce or self.nonce
        self.feed(f"SH1|HELLO|nonce={self.client}\n".encode())

    def command(self, ident="1", boot=None, action="scene", value="home", client=None):
        self.feed(f"SH1|CMD|boot={boot or self.nonce}|client={client or self.client}|id={ident}|action={action}|value={value}\n".encode())

    def test_nonce_reconnect_and_state_schema(self):
        self.hello()
        frames = self.frames()
        caps = next(fields for kind, fields in frames if kind == "CAPS")
        self.assertEqual(caps["boot"], self.nonce)
        self.assertIn("session", caps["caps"].split(","))
        self.assertIn("light_effect", caps["caps"].split(","))
        self.assertIn("ktv", caps["caps"].split(","))
        self.assertIn("demand_hold", caps["caps"].split(","))
        self.assertEqual(caps["client"], self.client)
        state = next(fields for kind, fields in frames if kind == "STATE")
        validate_state(state)
        self.assertEqual(state["temp"], "-123")
        self.assertEqual(state["state_source"], "commanded")
        self.assertEqual(state["alarm"], "0")
        self.assertEqual(state["light_effect"], "warm")
        self.assertEqual(state["ktv_brightness"], "50")
        self.assertEqual(state["demand_mode"], "auto")
        self.lib.Test_ClearOutput()
        self.hello("fedcba9876543210fedcba9876543210")
        self.assertTrue(all(fields["boot"] == self.nonce for _, fields in self.frames()))
        self.lib.Test_UnknownInputs()
        self.lib.Test_ClearOutput()
        self.feed(b"SH1|GET\r\n")
        state = next(fields for kind, fields in self.frames() if kind == "STATE")
        validate_state(state)
        self.assertTrue(all(state[key] == "?" for key in ("temp", "humid", "lux", "rain", "water", "demand")))

    def test_rainbow_command_and_state_roundtrip(self):
        self.hello()
        self.lib.Test_ClearOutput()
        self.command(action="light_effect", value="rainbow")
        frames = self.frames()
        self.assertTrue(any(kind == "ACK" and fields["result"] == "ok" for kind, fields in frames))
        state = next(fields for kind, fields in frames if kind == "STATE")
        self.assertEqual(validate_state(state)["light_effect"], "rainbow")
        self.lib.Test_ClearOutput()
        self.command(ident="2", action="light_effect", value="warm")
        state = next(fields for kind, fields in self.frames() if kind == "STATE")
        self.assertEqual(validate_state(state)["light_effect"], "warm")

    def test_ktv_effects_brightness_and_manual_mode_on_wire(self):
        self.hello()
        for ident, action, value, key, expected in (
            (1, "light_effect", "pulse", "light_effect", "pulse"),
            (2, "light_effect", "party", "light_effect", "party"),
            (3, "ktv_brightness", "0", "ktv_brightness", "0"),
            (4, "ktv_brightness", "20", "ktv_brightness", "20"),
            (5, "demand", "1", "demand_mode", "on"),
            (6, "demand", "0", "demand_mode", "off"),
            (7, "demand", "auto", "demand_mode", "auto"),
        ):
            self.lib.Test_ClearOutput()
            self.command(ident=str(ident), action=action, value=value)
            state = next(fields for kind, fields in self.frames() if kind == "STATE")
            self.assertEqual(validate_state(state)[key], expected)

    def test_boot_wrong_duplicate_and_id_reuse(self):
        self.hello()
        self.command(boot="wrong")
        self.assertEqual(self.lib.Test_CommandCalls(), 0)
        self.assertTrue(any(kind == "ACK" and fields["reason"] == "BOOT_MISMATCH" for kind, fields in self.frames()))
        self.command()
        self.command()
        self.command(ident="01")
        self.assertEqual(self.lib.Test_CommandCalls(), 1)
        self.command(value="away")
        self.assertEqual(self.lib.Test_CommandCalls(), 1)
        self.assertTrue(any(kind == "ACK" and fields["reason"] == "ID_REUSE" for kind, fields in self.frames()))

    def test_malformed_frames_do_not_execute(self):
        self.hello()
        base = f"SH1|CMD|boot={self.nonce}|client={self.client}|id=1|action=scene|value=home".encode()
        for frame in (
            base.replace(b"|id=1|", b"|id=4294967296|"),
            base.replace(b"|id=1|", b"|id=-1|"),
            base.replace(b"|id=1|", b"|id=|"),
            base + b"|id=2",
            base.replace(b"|value=home", b"|value=ho=me"),
            base.replace(b"|action=scene", b"|Action=scene"),
            base.replace(b"|value=home", b"|value=ho\x00me"),
        ):
            self.feed(frame + b"\n")
        self.assertEqual(self.lib.Test_CommandCalls(), 0)
        self.command()
        self.assertEqual(self.lib.Test_CommandCalls(), 1)

    def test_long_command_crlf_and_recovery(self):
        self.hello()
        self.feed(b"SH1|CMD|boot=" + self.nonce.encode() + b"|id=1|action=scene|value=" + b"x"*400 + b"\n")
        self.assertEqual(self.lib.Test_CommandCalls(), 0)
        self.assertGreater(self.lib.Test_Rejects(), 0)
        self.feed(f"SH1|CMD|boot={self.nonce}|client={self.client}|id=2|action=scene|value=home\r\n".encode())
        self.assertEqual(self.lib.Test_CommandCalls(), 1)
        self.feed(f"SH1|CMD|boot={self.nonce}|client={self.client}|id=3|action=scene|value=ho\rme\n".encode())
        self.assertEqual(self.lib.Test_CommandCalls(), 1)

    def test_repeated_hello_keeps_duplicate_suppression(self):
        self.hello()
        self.command()
        self.hello()
        self.command()
        self.assertEqual(self.lib.Test_CommandCalls(), 1, "HELLO must not replay an already accepted command")

    def test_new_client_reuses_id_but_old_client_is_rejected(self):
        self.hello()
        self.command()
        old_client = self.client
        self.hello("fedcba9876543210fedcba9876543210")
        self.command(value="away")
        self.assertEqual(self.lib.Test_CommandCalls(), 2)
        self.command(ident="2", client=old_client)
        self.assertEqual(self.lib.Test_CommandCalls(), 2)
        acks = [fields for kind, fields in self.frames() if kind == "ACK"]
        self.assertEqual(acks[-1]["reason"], "CLIENT_MISMATCH")
        self.assertEqual(acks[-2]["client"], self.client)

    def test_legacy_no_nonce_hello_retains_duplicate_cache(self):
        self.feed(b"SH1|HELLO\n")
        boot = next(fields["boot"] for kind, fields in self.frames() if kind == "CAPS")
        command = f"SH1|CMD|boot={boot}|id=1|action=scene|value=home\n".encode()
        self.feed(command)
        self.feed(b"SH1|HELLO\n")
        self.feed(command)
        self.assertEqual(self.lib.Test_CommandCalls(), 1)

    def test_tx_busy_does_not_block_and_ring_overflow_recovers(self):
        self.hello()
        self.lib.Test_SetTxReady(0)
        self.feed(b"SH1|GET\n")
        self.feed(b"x" * 400 + b"\n", drain=False)
        self.assertGreater(self.lib.Test_RxOverflows(), 0)
        self.tick(30)
        self.lib.Test_SetTxReady(1)
        self.tick(50)
        self.feed(b"\n")
        self.command(ident="2")
        self.assertEqual(self.lib.Test_CommandCalls(), 1)

    def test_ring_loss_never_joins_prefix_to_late_suffix(self):
        self.hello()
        prefix = f"SH1|CMD|boot={self.nonce}|client={self.client}|id=7|action=scene|value=ho".encode()
        padding = 255 - len(prefix)
        buffered = b"x\n" * (padding // 2) + (b"\n" if padding % 2 else b"") + prefix
        self.assertEqual(len(buffered), 255)
        # These x bytes belong to the same command but are lost at a full
        # ring. They must not be spliced out to turn invalid 'hox...me' into
        # an executable 'home' command after an earlier buffered newline.
        self.lib.Test_Input(buffered, len(buffered))
        self.lib.Test_Input(b"x" * 30, 30)
        self.assertGreater(self.lib.Test_RxOverflows(), 0)
        self.tick(300)
        self.feed(b"me\n")
        self.assertEqual(self.lib.Test_CommandCalls(), 0, "RX loss must discard the actually damaged frame")

    def test_production_controller_and_c_transport_byte_roundtrip(self):
        """Production Qt Controller <-> production C transport, fake UART only.

        Writes are queued until the pump runs, as real serial writes are; this
        avoids manufacturing a synchronous ACK before request sets pending.
        No serial port is opened and disposable logs stay outside the project.
        """
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        from smarthome.controller import Controller

        class FakeSerial:
            def __init__(self):
                self.open = True
                self.queued = []
                self.written = []
                self.incoming = b""

            def isOpen(self): return self.open
            def bytesToWrite(self): return sum(map(len, self.queued))
            def write(self, data):
                wire = bytes(data)
                self.queued.append(wire)
                self.written.append(wire)
                return len(wire)

            def readAll(self):
                data, self.incoming = self.incoming, b""
                return data

            def close(self): self.open = False

        app = QApplication.instance() or QApplication([])
        board_frames = []
        with tempfile.TemporaryDirectory() as temp:
            fake_module = Path(temp) / "host" / "smarthome" / "controller.py"
            with patch("smarthome.controller.time.monotonic", side_effect=lambda: 100.0 + self.now / 1000.0), \
                    patch("smarthome.controller.Path", side_effect=lambda _: fake_module):
                controller = Controller()
                controller.timer.stop()
                original_serial = controller.serial  # Constructed closed; never opened.
                self.assertFalse(original_serial.isOpen())
                serial = FakeSerial()
                try:
                    self.assertTrue(controller._reset("real"))
                    controller.serial = serial

                    def pump():
                        for _ in range(12):
                            had_write = bool(serial.queued)
                            while serial.queued:
                                self.feed(serial.queued.pop(0))
                            self.tick(40)
                            wire = self.lib.Test_Output()
                            self.lib.Test_ClearOutput()
                            if wire:
                                self.assertTrue(wire.endswith(b"\n"))
                                board_frames.extend(parse(line) for line in wire.splitlines())
                                serial.incoming += wire
                                controller._read()  # Production receive/framer/payload validation.
                            if not serial.queued and not wire and not had_write:
                                return
                        self.fail("software serial link did not become idle")

                    self.assertTrue(controller._hello())
                    pump()
                    self.assertTrue(controller.fresh)
                    self.assertEqual(controller.boot, controller.client_nonce)
                    self.assertIn("session", controller.capabilities)
                    caps = next(fields for kind, fields in board_frames if kind == "CAPS")
                    self.assertEqual(caps["client"], controller.client_nonce)
                    self.assertTrue(controller.can("scene"))
                    before_seq = controller.last_seq
                    self.assertTrue(controller.request("scene", "home"))
                    self.assertIsNotNone(controller.pending)
                    self.assertFalse(controller.can("scene"))
                    pump()
                    self.assertEqual(self.lib.Test_CommandCalls(), 1)
                    self.assertIsNone(controller.pending)
                    self.assertTrue(controller.fresh)
                    self.assertTrue(controller.can("scene"))
                    self.assertGreater(controller.last_seq, before_seq)
                    written = [parse(wire) for wire in serial.written]
                    kinds = [kind for kind, _ in written]
                    self.assertEqual(kinds.count("HELLO"), 1)
                    self.assertEqual(kinds.count("CMD"), 1)
                    self.assertGreaterEqual(kinds.count("GET"), 2)
                    command = next(fields for kind, fields in written if kind == "CMD")
                    ack = next(fields for kind, fields in board_frames if kind == "ACK")
                    self.assertEqual(command["client"], controller.client_nonce)
                    self.assertEqual(ack["client"], command["client"])
                    self.assertEqual(ack["boot"], command["boot"])
                    self.assertEqual(ack["id"], command["id"])
                    self.assertEqual(ack["result"], "ok")
                    validate_state(controller.state)
                    self.assertEqual(controller.state["state_source"], "commanded")
                    self.assertTrue(any(row[4] == "响应" for row in controller.records))
                finally:
                    controller.mode = "offline"
                    serial.close()
                    original_serial.close()
                    controller.timer.stop()
                    controller.deleteLater()
                    app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clang-dir", type=Path, required=True)
    args, unittest_args = parser.parse_known_args()
    SerialTests.lib = ctypes.CDLL(str(build(args.clang_dir)))
    SerialTests.lib.Test_Input.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
    SerialTests.lib.Test_Reset.argtypes = SerialTests.lib.Test_Task.argtypes = [ctypes.c_uint32]
    SerialTests.lib.Test_Output.restype = ctypes.c_char_p
    SerialTests.lib.Test_CommandCalls.restype = SerialTests.lib.Test_RxOverflows.restype = ctypes.c_uint32
    SerialTests.lib.Test_Rejects.restype = ctypes.c_uint32
    unittest.main(argv=[sys.argv[0], *unittest_args], verbosity=2)
