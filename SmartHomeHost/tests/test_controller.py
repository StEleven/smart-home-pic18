"""Deterministic offscreen host-session checks; no physical serial device is used."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtSerialPort import QSerialPort
from PySide6.QtWidgets import QApplication

from smarthome.controller import ACTION_CAP, Controller
from smarthome.protocol import MAX_LINE, encode


class SerialDouble:
    """Only the synchronous serial methods used by the write path."""

    def __init__(self, *, backlog=0, partial=False):
        self.open = True
        self.backlog = backlog
        self.partial = partial
        self.written = []

    def isOpen(self):
        return self.open

    def bytesToWrite(self):
        return self.backlog

    def write(self, data):
        self.written.append(data)
        return len(data) - 1 if self.partial else len(data)

    def close(self):
        self.open = False


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.now = 100.0
        self.clock = patch("smarthome.controller.time.monotonic", side_effect=lambda: self.now)
        self.clock.start()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Automatic disconnect archives also stay within this disposable test
        # directory. Fabricated serial frames must not become project evidence.
        self.fake_module = Path(self.temp.name) / "host" / "smarthome" / "controller.py"
        self.paths = patch("smarthome.controller.Path", side_effect=lambda _: self.fake_module)
        self.paths.start()
        self.controller = Controller()
        self.controller.timer.stop()
        self.outbound: list[tuple[str, dict]] = []

        def capture(kind, **fields):
            self.outbound.append((kind, fields))
            return True

        self.controller._write = capture

    def tearDown(self) -> None:
        self.controller.timer.stop()
        self.controller.mode = "offline"
        self.controller.serial.close()
        self.controller.deleteLater()
        self.paths.stop()
        self.clock.stop()

    @staticmethod
    def snapshot(boot="board-a", seq=1, **updates):
        state = {
            "boot": boot, "seq": str(seq), "uptime": "60",
            "temp": "260", "humid": "500", "lux": "300",
            "rain": "0", "water": "0", "door": "1", "window": "1",
            "window_target": "0", "curtain": "100", "vent": "0",
            "living": "70", "bedroom": "40", "hall": "30",
            "load_keep": "1", "load_switch": "1", "cooling": "0", "demand": "0",
            "scene": "home", "control": "auto", "manual_ms": "0",
            "timer": "idle", "timer_s": "0", "muted": "0",
        }
        state.update(updates)
        return state

    def begin_real(self, caps="scene,window,curtain,lights,loads,mute,timer", seq=1):
        self.controller._reset("real")
        self.handshake(caps=caps)
        self.controller.receive(encode("STATE", **self.snapshot(seq=seq)))

    def handshake(self, boot="board-a", caps="window", firmware="test-fw"):
        self.controller.receive(encode("CAPS", boot=boot, firmware=firmware, caps=caps))

    def test_hello_retries_reuse_nonce_and_reconnect_gets_new_client_with_existing_boot(self):
        c = self.controller
        c._reset('real')
        c._hello()
        c._hello()
        hellos = [fields for kind, fields in self.outbound if kind == 'HELLO']
        self.assertEqual(len(hellos), 2)
        self.assertEqual(hellos[0]['nonce'], hellos[1]['nonce'])
        for fields in hellos:
            self.assertRegex(fields['nonce'], r'^[0-9a-f]{32}$')
        self.handshake(boot='already-running')
        c.receive(encode('STATE', **self.snapshot(boot='already-running')))
        self.assertTrue(c.fresh)
        self.assertEqual(c.boot, 'already-running')
        c._reset('real')
        self.assertNotEqual(c.client_nonce, hellos[0]['nonce'])

    def test_session_capability_requires_current_client_and_ack_echo(self):
        c = self.controller
        c._reset('real')
        c._hello()
        client = c.client_nonce
        caps = {'boot': 'board-a', 'firmware': 'v1.1', 'caps': 'window,session'}
        for old_client in (None, '0' * 32):
            c.receive(encode('CAPS', **(caps if old_client is None else caps | {'client': old_client})))
            c.receive(encode('STATE', **self.snapshot()))
            self.assertIsNone(c.boot)
            self.assertFalse(c.can('window'))
        c.receive(encode('CAPS', **caps, client=client))
        c.receive(encode('STATE', **self.snapshot()))
        self.assertTrue(c.request('window', 'open'))
        command = self.outbound[-1][1]
        self.assertEqual(command['client'], client)
        pending = c.pending.copy()
        for old_client in (None, '0' * 32):
            fields = {'boot': 'board-a', 'id': command['id'], 'result': 'ok'}
            c.receive(encode('ACK', **(fields if old_client is None else fields | {'client': old_client})))
            self.assertEqual(c.pending, pending)
        c.receive(encode('ACK', boot='board-a', id=command['id'], client=client, result='ok'))
        self.assertIsNone(c.pending)
        c.receive(encode('ACK', boot='board-a', id=command['id'], client=client, result='ok'))
        self.assertIsNone(c.pending)
        self.assertEqual(sum(kind == 'CMD' for kind, _ in self.outbound), 1)

    def test_stale_state_rebinds_client_and_recovers_after_mcu_restart(self):
        c = self.controller
        c._reset('real')
        old_client = c.client_nonce
        c.receive(encode('CAPS', boot='old-boot', firmware='v1.1', caps='window,session', client=old_client))
        c.receive(encode('STATE', **self.snapshot(boot='old-boot', seq=90)))
        c.request('window', 'close')
        previous_state = c.state.copy()
        self.now += 2.01
        c.tick()
        new_client = c.client_nonce
        self.assertNotEqual(new_client, old_client)
        self.assertIsNone(c.pending)
        self.assertIsNone(c.boot)
        self.assertFalse(c.fresh)
        self.assertEqual(c.state, previous_state)
        self.assertEqual(self.outbound[-1], ('HELLO', {'nonce': new_client}))
        c.receive(encode('CAPS', boot='old-boot', firmware='v1.1', caps='window,session', client=old_client))
        self.assertIsNone(c.boot)
        c.receive(encode('STATE', **self.snapshot(boot='old-boot', seq=91)))
        self.assertFalse(c.fresh)
        c.receive(encode('CAPS', boot=new_client, firmware='v1.1', caps='window,session', client=new_client))
        c.receive(encode('STATE', **self.snapshot(boot=new_client, seq=1)))
        self.assertTrue(c.can('window'))
        self.assertEqual(c.last_seq, 1)
        self.assertEqual(sum(kind == 'CMD' for kind, _ in self.outbound), 1)

    def test_ack_timeout_with_fresh_state_queries_without_rehandshake(self):
        self.begin_real()
        c = self.controller
        c.request('window', 'open')
        self.now += 1.0
        c.receive(encode('STATE', **self.snapshot(seq=2)))
        self.now += 1.01
        c.tick()
        self.assertIsNone(c.pending)
        self.assertIn('结果未知', c.request_status)
        self.assertEqual(self.outbound[-1], ('GET', {}))
        self.assertEqual(sum(kind == 'CMD' for kind, _ in self.outbound), 1)

    def ack(self, **updates):
        fields = {"boot": "board-a", "id": self.controller.pending["id"], "result": "ok", "reason": "OK"}
        fields.update(updates)
        self.controller.receive(encode("ACK", **fields))

    def test_handshake_and_valid_snapshot_are_both_required(self):
        c = self.controller
        c._reset("real")
        c.receive(encode("STATE", **self.snapshot()))
        self.assertFalse(c.fresh)
        self.assertEqual(c.state, {})
        self.assertFalse(c.request("window", "open"))
        self.assertEqual(self.outbound, [])
        self.handshake(caps="window")
        self.assertEqual(self.outbound, [("GET", {})])
        self.assertFalse(c.can("window"))
        c.receive(encode("STATE", **self.snapshot()))
        self.assertTrue(c.fresh)
        self.assertTrue(c.can("window"))
        self.assertFalse(c.can("scene"))
        self.assertFalse(c.can("unknown-action"))

    def test_readonly_capabilities_show_state_without_enabling_commands(self):
        self.begin_real(caps="")
        c = self.controller
        self.assertTrue(c.fresh)
        self.assertEqual(c.capabilities, set())
        for action in ACTION_CAP:
            self.assertFalse(c.can(action), action)
            self.assertFalse(c.request(action, "1"), action)
        self.assertEqual([kind for kind, _ in self.outbound], ["GET"])

    def test_duplicate_and_stale_snapshots_cannot_refresh_or_overwrite(self):
        self.begin_real(seq=10)
        c = self.controller
        original = c.state.copy()
        received = c.last_state
        self.now += 1.0
        for seq in (10, 9, 0x8000000A):
            c.receive(encode("STATE", **self.snapshot(seq=seq, water="1")))
        self.assertEqual(c.state, original)
        self.assertEqual(c.last_state, received)
        self.assertEqual(sum(row[4] == "STATE" for row in c.records), 1)
        self.now = received + 2.0
        c.tick()
        self.assertFalse(c.fresh)
        self.assertFalse(c.can("window"))
        self.assertIn("过期", c.status)
        self.assertEqual(sum(row[4] == "状态过期" for row in c.records), 1)
        c.tick()
        self.assertEqual(sum(row[4] == "状态过期" for row in c.records), 1)
        self.handshake()
        c.receive(encode("STATE", **self.snapshot(seq=11, water="1")))
        self.assertTrue(c.can("window"))
        self.assertEqual(c.state["water"], "1")

    def test_sequence_wrap_is_forward_progress(self):
        self.begin_real(seq=0xFFFFFFFF)
        self.now += 0.5
        self.controller.receive(encode("STATE", **self.snapshot(seq=0)))
        self.assertEqual(self.controller.last_seq, 0)
        self.assertEqual(self.controller.last_state, self.now)

    def test_ack_acceptance_does_not_claim_physical_state(self):
        self.begin_real()
        c = self.controller
        old_state = c.state.copy()
        self.assertTrue(c.request("window", "open"))
        pending = c.pending.copy()
        self.assertFalse(c.can("window"))
        self.assertFalse(c.request("scene", "away"))
        self.assertEqual(c.pending, pending)
        self.ack()
        self.assertIsNone(c.pending)
        self.assertEqual(c.state, old_state)
        self.assertEqual(c.request_status, "指令已接收")
        self.assertEqual(self.outbound[-1], ("GET", {}))
        self.assertEqual(sum(kind == "CMD" for kind, _ in self.outbound), 1)

    def test_only_matching_boot_and_request_ack_can_resolve_pending(self):
        self.begin_real()
        c = self.controller
        c.request("window", "open")
        pending = c.pending.copy()
        self.ack(boot="old-boot")
        self.ack(id="999")
        self.assertEqual(c.pending, pending)
        self.ack(result="rejected", reason="RAIN")
        self.assertIsNone(c.pending)
        self.assertIn("拒绝", c.request_status)
        self.assertIn("雨湿", c.request_status)
        self.assertEqual(c.state["window"], "1")

    def test_timeout_is_unknown_and_queries_state_without_resending_command(self):
        self.begin_real()
        c = self.controller
        c.request("window", "open")
        request_id = c.pending["id"]
        self.now += 2.01
        c.tick()
        self.assertIsNone(c.pending)
        self.assertIn("结果未知", c.request_status)
        self.assertFalse(c.can("window"))
        first_outbound = self.outbound.copy()
        self.assertEqual([kind for kind, _ in first_outbound], ["GET", "CMD", "HELLO"])
        self.now += 3
        c.tick()
        self.assertEqual(sum(kind == 'CMD' for kind, _ in self.outbound), 1)
        self.assertEqual(self.outbound[-1], first_outbound[-1], 'handshake retry retains the nonce')
        c.receive(encode("ACK", boot="board-a", id=request_id, result="ok", reason="OK"))
        self.assertIn("结果未知", c.request_status)
        self.handshake()
        c.receive(encode("STATE", **self.snapshot(seq=2)))
        self.assertTrue(c.can("window"))

    def test_new_caps_boot_clears_pending_and_requires_new_state(self):
        self.begin_real(seq=100)
        c = self.controller
        c.request("window", "open")
        old_id = c.pending["id"]
        self.handshake(boot="board-b", caps="window")
        self.assertIsNone(c.pending)
        self.assertEqual(c.state, {})
        self.assertIsNone(c.last_seq)
        self.assertFalse(c.can("window"))
        c.receive(encode("ACK", boot="board-a", id=old_id, result="ok", reason="OK"))
        self.assertFalse(c.can("window"))
        c.receive(encode("STATE", **self.snapshot(boot="board-b", seq=1)))
        self.assertTrue(c.can("window"))

    def test_state_boot_change_requires_fresh_handshake(self):
        self.begin_real()
        c = self.controller
        c.request("window", "open")
        c.receive(encode("STATE", **self.snapshot(boot="board-b", seq=0)))
        self.assertIsNone(c.boot)
        self.assertIsNone(c.pending)
        self.assertEqual(c.capabilities, set())
        self.assertFalse(c.fresh)
        self.assertFalse(c.can("window"))
        self.assertEqual(self.outbound[-1][0], "HELLO")
        self.assertRegex(self.outbound[-1][1]['nonce'], r'^[0-9a-f]{32}$')
        c.receive(encode("STATE", **self.snapshot(boot="board-b", seq=1)))
        self.assertFalse(c.can("window"))
        self.handshake(boot="board-b")
        self.assertFalse(c.can("window"))
        c.receive(encode("STATE", **self.snapshot(boot="board-b", seq=2)))
        self.assertTrue(c.can("window"))

    def test_simulation_and_real_receive_paths_are_isolated(self):
        self.begin_real()
        c = self.controller
        c.request("window", "open")
        c.start_demo()
        self.assertIsNone(c.pending)
        self.assertEqual(c.mode, "simulation")
        self.assertTrue(c.boot.startswith("SIM-"))
        simulated = c.state.copy()
        prior_outbound = self.outbound.copy()
        c.receive(encode("CAPS", boot="hardware", firmware="real-fw", caps="window"))
        c.receive(encode("STATE", **self.snapshot(boot="hardware", seq=200)))
        self.assertEqual(c.state, simulated)
        self.assertTrue(all(row[1] == "simulation" for row in c.records))
        c.set_input("rain", "1")
        c.request("window", "open")
        self.assertEqual(self.outbound, prior_outbound)
        self.assertEqual(c.request_status, "操作被拒绝：雨湿限制")
        self.assertTrue(all(row[1] == "simulation" for row in c.records))
        c._reset("real")
        self.assertIsNone(c.simulator)
        self.assertEqual(c.state, {})
        self.assertEqual(list(c.records), [])
        self.assertEqual(c.capabilities, set())
        self.assertFalse(c.can("window"))
        c.set_input("rain", "0")
        self.assertEqual(c.state, {})

    def test_invalid_wire_data_is_logged_without_destroying_current_state(self):
        self.begin_real()
        c = self.controller
        old_state = c.state.copy()
        invalid = (
            b"not-sh1\n", b"SH1|STATE|boot=board-a\n", b"SH1|EVENT|code=\xff\n",
            b"SH1|CAPS|boot=board-a|caps=window\n", b"SH1|ACK|id=1|id=1\n",
            b"x" * (MAX_LINE + 20) + b"\n",
            encode("STATE", **self.snapshot(seq=2, temp="9999")),
        )
        for wire in invalid:
            c.receive(wire)
        self.assertEqual(c.state, old_state)
        self.assertGreaterEqual(sum(row[4] == "协议异常" for row in c.records), len(invalid))
        c.request("window", "open")
        pending = c.pending.copy()
        self.ack(result="bogus")
        self.assertEqual(c.pending, pending)
        good = encode("STATE", **self.snapshot(seq=2, temp="270"))
        for offset in range(0, len(good), 7):
            c.receive(good[offset:offset + 7])
        self.assertEqual(c.state["temp"], "270")

    def test_disconnect_preserves_only_expired_snapshot_and_archives_source(self):
        self.begin_real()
        c = self.controller
        c.request("window", "open")
        old_state = c.state.copy()
        c.disconnect()
        self.assertEqual(c.mode, "offline")
        self.assertEqual(c.state, old_state)
        self.assertFalse(c.fresh)
        self.assertFalse(c.can("window"))
        self.assertIsNone(c.pending)
        self.assertEqual(c.capabilities, set())
        self.assertTrue(Path(c.last_saved).is_file())
        with open(c.last_saved, newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.reader(stream))
        self.assertTrue(all(row[1] == "real" for row in rows[1:]))
        self.assertTrue(any(row[4] == "STATE" for row in rows[1:]))
        c.receive(encode("STATE", **self.snapshot(seq=200)))
        self.assertEqual(c.state, old_state)

    def test_serial_resource_error_disconnects_and_disables_controls(self):
        self.begin_real()
        c = self.controller
        c.request("window", "open")
        c._serial_error(QSerialPort.SerialPortError.ResourceError)
        self.assertEqual(c.mode, "offline")
        self.assertFalse(c.can("window"))
        self.assertIsNone(c.pending)
        self.assertIn("中断", c.status)
        self.assertTrue(any(row[4] == "串口异常" for row in c.records))

    def test_failed_send_does_not_create_pending_or_claim_accepted(self):
        self.begin_real()
        c = self.controller
        c._write = lambda *args, **kwargs: False
        self.assertFalse(c.request("window", "open"))
        self.assertIsNone(c.pending)
        self.assertIn("未完成发送", c.request_status)
        self.assertFalse(any(row[4] == "请求" for row in c.records))

    def test_serial_backlog_rejects_new_request_before_writing(self):
        self.begin_real()
        c = self.controller
        c.serial = SerialDouble(backlog=4097)
        c._write = lambda kind, **fields: Controller._write(c, kind, **fields)
        self.assertFalse(c.request("window", "open"))
        self.assertEqual(c.serial.written, [])
        self.assertIsNone(c.pending)
        self.assertEqual(c.mode, "real")
        self.assertTrue(any(row[4] == "通信异常" and "拥塞" in row[5] for row in c.records))

    def test_partial_serial_write_disconnects_and_records_unknown_result(self):
        self.begin_real()
        c = self.controller
        c.serial = SerialDouble(partial=True)
        c._write = lambda kind, **fields: Controller._write(c, kind, **fields)
        self.assertFalse(c.request("window", "open"))
        self.assertEqual(c.mode, "offline")
        self.assertFalse(c.serial.isOpen())
        self.assertIsNone(c.pending)
        self.assertFalse(c.can("window"))
        self.assertEqual(len(c.serial.written), 1)
        self.assertTrue(any(row[4] == "通信异常" and "结果未知" in row[5] for row in c.records))

    def test_archive_error_does_not_report_a_prior_session_as_saved(self):
        self.begin_real()
        c = self.controller
        c.last_saved = "prior-session.csv"
        with patch.object(c, "export", side_effect=OSError("test permission denied")):
            c.disconnect()
        self.assertEqual(c.mode, "offline")
        self.assertFalse(c.can("window"))
        self.assertTrue(any(row[4] == "保存失败" for row in c.records))
        self.assertNotIn("prior-session.csv", c.request_status)
        self.assertEqual(c.last_saved, "")

    def test_failed_archive_blocks_switch_without_losing_unsaved_records(self):
        self.begin_real()
        c = self.controller
        c.request("window", "open")
        snapshot_rows = [row for row in c.records if row[4] == "STATE"]
        with patch.object(c, "export", side_effect=OSError("test disk full")):
            self.assertIs(c.start_demo(), False)
        self.assertEqual(c.mode, "offline")
        self.assertIsNone(c.pending)
        self.assertIsNone(c.simulator)
        self.assertTrue(c.archive_error)
        self.assertTrue(all(row in c.records for row in snapshot_rows))
        unsaved = list(c.records)
        c.serial = SerialDouble()
        self.assertIs(c.connect_port("UNIT_TEST_ONLY"), False)
        self.assertEqual(c.mode, "offline")
        self.assertEqual(list(c.records), unsaved)
        self.assertFalse(c.can("window"))

        manual_path = Path(self.temp.name) / "recovered-session.csv"
        c.export(manual_path)
        self.assertTrue(manual_path.is_file())
        self.assertFalse(c.archive_error)
        self.assertIsNot(c.start_demo(), False)
        self.assertEqual(c.mode, "simulation")
        self.assertTrue(c.boot.startswith("SIM-"))
        self.assertTrue(all(row[1] == "simulation" for row in c.records))

    def test_export_keeps_source_boot_firmware_and_raw_snapshot(self):
        self.begin_real()
        c = self.controller
        c.log("EVENT", "=untrusted formula", {"code": "TEST"})
        path = Path(self.temp.name) / "session.csv"
        c.export(path)
        with path.open(newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(len(rows[0]), 7)
        snapshots = [row for row in rows[1:] if row[4] == "STATE"]
        self.assertEqual(len(snapshots), 1)
        row = snapshots[0]
        self.assertEqual(row[1:4], ["real", "board-a", "test-fw"])
        self.assertEqual(json.loads(row[6]), c.state)
        self.assertRegex(row[0], r"T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}$")
        self.assertEqual(rows[-1][5], "'=untrusted formula")


if __name__ == "__main__":
    unittest.main()
