"""Protocol corruption and offline rule checks; these are not hardware tests."""

from __future__ import annotations

import math
import unittest

from smarthome.protocol import MAX_LINE, LineFramer, ProtocolError, encode, parse, validate_state
from smarthome.simulator import Simulator


class ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.valid = Simulator().snapshot()

    def test_encode_and_parse_round_trip(self) -> None:
        wire = encode("CMD", boot="test-1", id=42, action="window", value="open")
        self.assertEqual(wire, b"SH1|CMD|boot=test-1|id=42|action=window|value=open\n")
        kind, fields = parse(wire)
        self.assertEqual(kind, "CMD")
        self.assertEqual(fields["id"], "42")
        self.assertEqual(parse(wire[:-1]), (kind, fields))
        self.assertEqual(parse(wire[:-1] + b"\r\n"), (kind, fields))
        self.assertEqual(parse(encode("HELLO")), ("HELLO", {}))
        self.assertEqual(parse(encode("EVENT", code="WATER")), ("EVENT", {"code": "WATER"}))

    def test_encode_rejects_delimiters_controls_and_non_ascii(self) -> None:
        for value in ("a|b", "a=b", "\n", "\r", "\t", "\x00", "\x7f", "中文", ""):
            with self.subTest(value=repr(value)), self.assertRaises(ProtocolError):
                encode("CMD", value=value)
        with self.assertRaises(ProtocolError):
            encode("CMD", **{"Bad-key": "x"})
        with self.assertRaises(ProtocolError):
            encode("INVALID")
        with self.assertRaises(ProtocolError):
            encode("CMD", value="x" * MAX_LINE)

    def test_readonly_firmware_can_advertise_no_capabilities(self) -> None:
        wire = encode("CAPS", boot="readonly-1", firmware="sensor-only", caps="")
        self.assertEqual(parse(wire), (
            "CAPS", {"boot": "readonly-1", "firmware": "sensor-only", "caps": ""}
        ))
        # This exception belongs only to the CAPS capability list.
        for kind, key in (("CMD", "caps"), ("CAPS", "firmware"), ("ACK", "reason")):
            with self.subTest(kind=kind, key=key):
                with self.assertRaises(ProtocolError):
                    encode(kind, **{key: ""})
                with self.assertRaises(ProtocolError):
                    parse(f"SH1|{kind}|{key}=\n".encode("ascii"))

    def test_parse_rejects_malformed_frames(self) -> None:
        malformed = (
            b"", b"SH2|STATE\n", b"SH1|state\n", b"SH1|UNKNOWN\n",
            b"SH1|CMD|a=1|a=2\n", b"SH1|CMD|a=1=2\n", b"SH1|CMD|a\n",
            b"SH1|CMD|=1\n", b"SH1|CMD|a=\n", b"SH1|CMD|A=1\n",
            b"SH1|CMD|a=1|\n", b"SH1|CMD\nSH1|GET\n", b"SH1|CMD\r",
            b"SH1|CMD|a=\xff\n", b"SH1|CMD|a=\x00\n",
            b"x" * (MAX_LINE + 1),
        )
        for wire in malformed:
            with self.subTest(wire=wire[:80]), self.assertRaises(ProtocolError):
                parse(wire)

    def test_framer_handles_fragmentation_and_concatenation(self) -> None:
        wire = encode("STATE", **self.valid)
        expected = [wire, encode("PING"), encode("GET")]
        joined = b"".join(expected)
        for chunk_size in (1, 2, 7, 31, len(joined)):
            with self.subTest(chunk_size=chunk_size):
                framer = LineFramer()
                actual = []
                for offset in range(0, len(joined), chunk_size):
                    actual.extend(framer.feed(joined[offset:offset + chunk_size]))
                self.assertEqual(actual, expected)
                self.assertEqual(framer.errors, 0)

    def test_framer_bounds_and_resynchronizes_only_after_newline(self) -> None:
        framer = LineFramer()
        self.assertEqual(framer.feed(b"x" * (MAX_LINE + 20)), [])
        self.assertEqual(framer.errors, 1)
        self.assertLessEqual(len(framer._buffer), MAX_LINE)
        # A valid-looking suffix of the damaged line must be discarded too.
        self.assertEqual(framer.feed(b"SH1|GET\n" + encode("PING")), [encode("PING")])
        self.assertEqual(framer.errors, 1)
        self.assertEqual(framer.feed(b"z" * MAX_LINE + b"\n" + encode("GET")), [encode("GET")])
        self.assertEqual(framer.errors, 2)
        exact = b"x" * (MAX_LINE - 1) + b"\n"
        self.assertEqual(framer.feed(exact), [exact])
        framer.feed(b"partial")
        framer.reset()
        self.assertEqual(framer.errors, 0)
        self.assertEqual(framer.feed(encode("GET")), [encode("GET")])

    def test_state_requires_full_schema_and_copies_future_fields(self) -> None:
        missing = self.valid.copy()
        missing.pop("water")
        with self.assertRaises(ProtocolError):
            validate_state(missing)
        future = self.valid | {"future_sensor": "42"}
        validated = validate_state(future)
        self.assertEqual(validated, future)
        validated["temp"] = "?"
        self.assertNotEqual(validated["temp"], future["temp"])

    def test_state_sensor_unknowns_and_range_boundaries(self) -> None:
        boundaries = {
            "seq": ("0", "4294967295"), "uptime": ("0", "4294967295"),
            "temp": ("-400", "1250"), "humid": ("0", "1000"),
            "lux": ("0", "200000"), "window_target": ("0", "100"),
            "manual_ms": ("0", "600000"), "timer_s": ("0", "86400"),
        }
        for key, values in boundaries.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertEqual(validate_state(self.valid | {key: value})[key], value)
        for key in (
            "temp", "humid", "lux", "rain", "water", "door", "window", "window_target",
            "curtain", "vent", "living", "bedroom", "hall", "load_keep", "load_switch",
            "cooling", "demand", "muted",
        ):
            with self.subTest(key=key):
                self.assertEqual(validate_state(self.valid | {key: "?"})[key], "?")

    def test_state_rejects_invalid_ranges_types_tokens_and_enums(self) -> None:
        invalid = {
            "boot": "bad token", "seq": "4294967296", "uptime": "-1",
            "temp": "-401", "humid": "1001", "lux": "200001", "rain": "2",
            "water": "-1", "door": "closed", "window": "100", "window_target": "101",
            "curtain": "-1", "vent": "101", "living": "1.5", "bedroom": "+1", "hall": " 1",
            "load_keep": "2", "load_switch": "2", "cooling": "on", "demand": "True",
            "scene": "holiday", "control": "automatic", "manual_ms": "?",
            "timer": "started", "timer_s": "86401", "muted": "2",
        }
        for key, value in invalid.items():
            with self.subTest(key=key, value=value), self.assertRaises(ProtocolError):
                validate_state(self.valid | {key: value})
        with self.assertRaises(ProtocolError):
            validate_state(self.valid | {"temp": 250})
        with self.assertRaises(ProtocolError):
            validate_state(self.valid | {"Bad": "x"})
        with self.assertRaises(ProtocolError):
            validate_state(self.valid | {"future_sensor": "x|y"})
        with self.assertRaises(ProtocolError):
            validate_state(self.valid | {"seq": "-0"})


class SimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sim = Simulator()
        # These rule tests explicitly request natural ventilation; automatic
        # temperature demand and hysteresis are covered separately below.
        self.sim.command('demand', '0')

    def assertCommand(self, action: str, value: str) -> None:
        self.assertEqual(self.sim.command(action, value), (True, "OK"))

    def test_snapshots_are_complete_copies_with_sequence_and_uptime(self) -> None:
        first = self.sim.snapshot()
        self.sim.tick(1.5)
        second = self.sim.snapshot()
        self.assertEqual(second["seq"], str(int(first["seq"]) + 1))
        self.assertEqual(second["uptime"], "1")
        first["temp"] = "999"
        self.assertEqual(self.sim.snapshot()["temp"], "260")
        self.assertEqual(validate_state(second), second)
        self.sim.state["seq"] = "4294967295"
        self.assertEqual(self.sim.snapshot()["seq"], "0")

    def test_rain_closes_and_cancels_manual_then_clearing_needs_ventilation(self) -> None:
        self.assertCommand("window", "open")
        self.assertEqual(self.sim.snapshot()["window"], "0")
        self.sim.set_input("rain", "1")
        rainy = self.sim.snapshot()
        self.assertEqual((rainy["window_target"], rainy["window"], rainy["vent"]), ("0", "1", "0"))
        self.assertEqual((rainy["control"], rainy["manual_ms"]), ("auto", "0"))
        self.assertEqual(self.sim.command("window", "open"), (False, "RAIN"))
        self.sim.set_input("rain", "0")
        self.assertEqual(self.sim.snapshot()["window_target"], "0")
        self.sim.set_input("temp", "310")
        self.assertEqual(self.sim.snapshot()["window_target"], "100")

    def test_unknown_rain_blocks_open_and_sensor_unknowns_persist(self) -> None:
        self.sim.set_input("temp", "310")
        self.sim.set_input("rain", "?")
        self.assertEqual(self.sim.snapshot()["window_target"], "0")
        self.assertEqual(self.sim.command("window", "open"), (False, "RAIN_UNKNOWN"))
        for key in ("temp", "humid", "lux", "water", "door", "window", "demand"):
            self.sim.set_input(key, "?")
        self.sim.tick(10)
        for key in ("temp", "humid", "lux", "rain", "water", "door", "window", "demand"):
            self.assertEqual(self.sim.snapshot()[key], "?")

    def test_long_away_overrides_manual_and_auto_and_disables_switch_load(self) -> None:
        self.sim.set_input("temp", "310")
        self.sim.set_input("door", "0")
        self.assertCommand("window", "open")
        self.assertCommand("scene", "long_away")
        locked = self.sim.snapshot()
        self.assertEqual((locked["door"], locked["window"], locked["window_target"]), ("0", "1", "0"))
        self.assertEqual((locked["load_keep"], locked["load_switch"]), ("1", "0"))
        self.assertEqual(self.sim.command("window", "open"), (False, "LONG_AWAY"))
        self.assertCommand("window", "auto")
        self.assertEqual(self.sim.snapshot()["window_target"], "0")
        self.assertEqual(self.sim.command("load_switch", "1"), (False, "LONG_AWAY"))
        self.assertCommand("scene", "home")
        self.sim.set_input("temp", "260")
        self.assertEqual(self.sim.snapshot()["window_target"], "0")
        self.assertEqual(self.sim.snapshot()["manual_ms"], "0")

    def test_long_away_preserves_door_feedback_until_input_changes(self) -> None:
        self.sim.set_input("door", "0")
        self.assertCommand("scene", "long_away")
        self.sim.tick(60)
        self.assertEqual(self.sim.snapshot()["door"], "0")
        self.sim.set_input("door", "?")
        self.assertEqual(self.sim.snapshot()["door"], "?")
        self.sim.set_input("door", "1")
        self.assertEqual(self.sim.snapshot()["door"], "1")

    def test_ordinary_away_keeps_door_feedback_and_permits_natural_ventilation(self) -> None:
        self.sim.set_input("door", "0")
        self.sim.set_input("temp", "310")
        self.assertCommand("scene", "away")
        away = self.sim.snapshot()
        self.assertEqual(away["door"], "0")
        self.assertEqual(away["window_target"], "100")
        self.assertEqual(away["load_keep"], "1")
        self.assertEqual(away["load_switch"], "0")
        self.assertCommand("window", "open")
        self.sim.set_input("demand", "1")
        self.assertCommand("window", "auto")
        self.assertEqual(self.sim.snapshot()["cooling"], "0")

    def test_window_manual_takeover_expires_and_rechecks_current_inputs(self) -> None:
        self.assertCommand("window", "open")
        self.sim.tick(59.5)
        state = self.sim.snapshot()
        self.assertEqual((state["control"], state["manual_ms"], state["window_target"]), ("manual", "500", "100"))
        self.sim.tick(0.5)
        state = self.sim.snapshot()
        self.assertEqual((state["control"], state["manual_ms"], state["window_target"]), ("auto", "0", "0"))
        self.sim.set_input("temp", "310")
        self.assertCommand("window", "close")
        self.assertEqual(self.sim.snapshot()["window_target"], "0")
        self.sim.tick(60)
        self.assertEqual(self.sim.snapshot()["window_target"], "100")

    def test_cooling_requires_closed_confirmed_window_and_never_overlaps_open(self) -> None:
        self.sim.set_input("temp", "310")
        self.assertEqual(self.sim.snapshot()["window_target"], "100")
        self.sim.set_input("demand", "1")
        state = self.sim.snapshot()
        self.assertEqual((state["window"], state["window_target"], state["cooling"]), ("1", "0", "1"))
        self.assertCommand("window", "open")
        state = self.sim.snapshot()
        self.assertEqual((state["window"], state["cooling"]), ("0", "0"))
        self.sim.set_input("window", "?")
        self.assertCommand("window", "auto")
        self.assertEqual((self.sim.snapshot()["window"], self.sim.snapshot()["cooling"]), ("?", "0"))
        self.sim.set_input("window", "1")
        self.assertEqual(self.sim.snapshot()["cooling"], "1")

    def test_air_conditioning_vent_follows_cooling_not_natural_window_ventilation(self) -> None:
        self.sim.set_input("temp", "310")
        state = self.sim.snapshot()
        self.assertEqual((state["window_target"], state["cooling"], state["vent"]), ("100", "0", "0"))
        self.sim.set_input("demand", "1")
        state = self.sim.snapshot()
        self.assertEqual((state["window_target"], state["window"], state["cooling"], state["vent"]), ("0", "1", "1", "100"))
        self.sim.set_input("window", "0")
        state = self.sim.snapshot()
        self.assertEqual((state["cooling"], state["vent"]), ("0", "0"))

    def test_window_contact_override_persists_and_can_resume_following_target(self) -> None:
        self.sim.set_input("demand", "1")
        self.sim.set_input("window", "0")
        self.sim.tick(2)
        state = self.sim.snapshot()
        self.assertEqual((state["window_target"], state["window"], state["cooling"]), ("0", "0", "0"))
        self.sim.set_input("window", "1")
        self.assertEqual(self.sim.snapshot()["cooling"], "1")
        self.assertCommand("window", "open")
        # The contact is independent of the open target: this can model a
        # jammed actuator. Cooling still cannot run with an open target.
        state = self.sim.snapshot()
        self.assertEqual((state["window_target"], state["window"], state["cooling"]), ("100", "1", "0"))
        self.sim.set_input("window", "auto")
        self.assertEqual(self.sim.snapshot()["window"], "0")
        self.assertCommand("window", "auto")
        self.assertEqual(self.sim.snapshot()["window"], "1")
        self.sim.set_input("window", "?")
        self.assertCommand("scene", "long_away")
        state = self.sim.snapshot()
        self.assertEqual((state["window"], state["window_target"], state["cooling"]), ("?", "0", "0"))
        self.sim.set_input("window", "auto")
        self.assertEqual(self.sim.snapshot()["window"], "1")

    def test_water_mute_lasts_until_a_confirmed_clear_and_resets_for_next_alarm(self) -> None:
        self.assertEqual(self.sim.command("mute", "1"), (False, "NO_WATER_ALARM"))
        self.sim.set_input("water", "1")
        self.assertCommand("mute", "1")
        self.sim.tick(100)
        self.assertEqual(self.sim.snapshot()["muted"], "1")
        self.sim.set_input("water", "?")
        self.assertEqual(self.sim.snapshot()["muted"], "1")
        self.sim.set_input("water", "0")
        self.assertEqual(self.sim.snapshot()["muted"], "0")
        self.sim.set_input("water", "1")
        self.assertEqual(self.sim.snapshot()["muted"], "0")

    def test_timer_pause_resume_completion_and_stop(self) -> None:
        self.assertEqual(self.sim.command("timer_pause", "1"), (False, "TIMER_STATE"))
        self.assertCommand("timer_start", "3")
        self.sim.tick(1.25)
        self.assertEqual((self.sim.snapshot()["timer"], self.sim.snapshot()["timer_s"]), ("running", "2"))
        self.assertCommand("timer_pause", "1")
        self.sim.tick(100)
        self.assertEqual((self.sim.snapshot()["timer"], self.sim.snapshot()["timer_s"]), ("paused", "2"))
        self.assertCommand("timer_resume", "1")
        self.sim.tick(1.75)
        self.assertEqual((self.sim.snapshot()["timer"], self.sim.snapshot()["timer_s"]), ("done", "0"))
        self.assertEqual(self.sim.command("timer_resume", "1"), (False, "TIMER_STATE"))
        self.assertCommand("timer_stop", "1")
        self.assertEqual((self.sim.snapshot()["timer"], self.sim.snapshot()["timer_s"]), ("idle", "0"))

    def test_scene_lights_and_curtain_auto_presets_and_manual_hall(self) -> None:
        self.assertCommand("scene", "sleep")
        self.assertEqual([self.sim.snapshot()[key] for key in ("living", "bedroom", "hall")], ["0", "0", "0"])
        self.sim.tick(3)
        self.assertEqual(self.sim.snapshot()["hall"], "0")
        self.assertCommand("hall", "15")
        self.assertEqual(self.sim.snapshot()["hall"], "15")
        self.assertCommand("scene", "movie")
        self.assertEqual(self.sim.snapshot()["living"], "20")
        self.assertEqual(self.sim.snapshot()["curtain"], "0")
        self.assertCommand("curtain", "open")
        self.assertEqual(self.sim.snapshot()["curtain"], "100")
        self.assertCommand("curtain", "auto")
        self.assertEqual(self.sim.snapshot()["curtain"], "0")

    def test_curtain_hysteresis_requires_three_continuous_seconds(self) -> None:
        self.sim.set_input("lux", "499")
        self.sim.tick(3)
        self.assertEqual(self.sim.snapshot()["curtain"], "100")
        self.sim.set_input("lux", "500")
        self.sim.tick(2.9)
        self.assertEqual(self.sim.snapshot()["curtain"], "100")
        self.sim.tick(0.1)
        self.assertEqual(self.sim.snapshot()["curtain"], "0")
        self.sim.set_input("lux", "?")
        self.sim.tick(3)
        self.assertEqual(self.sim.snapshot()["curtain"], "0")
        self.sim.set_input("lux", "301")
        self.sim.tick(3)
        self.assertEqual(self.sim.snapshot()["curtain"], "0")
        self.sim.set_input("lux", "300")
        self.sim.tick(2.9)
        self.assertEqual(self.sim.snapshot()["curtain"], "0")
        self.sim.tick(0.1)
        self.assertEqual(self.sim.snapshot()["curtain"], "100")
        self.assertCommand("scene", "away")
        self.sim.set_input("lux", "500")
        self.sim.tick(2)
        self.sim.set_input("lux", "?")
        self.sim.tick(10)
        self.assertEqual(self.sim.snapshot()["curtain"], "100")
        self.sim.set_input("lux", "500")
        self.sim.tick(3)
        self.assertEqual(self.sim.snapshot()["curtain"], "0")
        self.sim.set_input("lux", "300")
        self.sim.tick(3)
        self.assertEqual(self.sim.snapshot()["curtain"], "100")
        self.assertCommand("scene", "sleep")
        self.assertEqual(self.sim.snapshot()["curtain"], "0")
        self.assertCommand("scene", "movie")
        self.assertEqual(self.sim.snapshot()["curtain"], "0")

    def test_independent_light_takeovers_expire_and_auto_restores_scene_preset(self) -> None:
        self.assertCommand("living", "10")
        self.sim.tick(30)
        self.assertCommand("bedroom", "20")
        self.sim.tick(29.5)
        state = self.sim.snapshot()
        self.assertEqual((state["living"], state["bedroom"], state["hall"]), ("10", "20", "30"))
        self.assertEqual((state["control"], state["manual_ms"]), ("auto", "0"))
        self.sim.tick(0.5)
        self.assertEqual((self.sim.snapshot()["living"], self.sim.snapshot()["bedroom"]), ("70", "20"))
        self.assertCommand("bedroom", "auto")
        self.assertEqual(self.sim.snapshot()["bedroom"], "40")
        self.assertCommand("scene", "sleep")
        self.assertCommand("hall", "15")
        self.sim.tick(60)
        self.assertEqual(self.sim.snapshot()["hall"], "0")
        self.assertCommand("living", "80")
        self.assertCommand("scene", "movie")
        self.assertEqual(self.sim.snapshot()["living"], "20")

    def test_curtain_takeover_expires_using_current_light_and_auto_can_end_early(self) -> None:
        self.sim.set_input("lux", "600")
        self.assertCommand("curtain", "open")
        self.sim.tick(59.5)
        self.assertEqual(self.sim.snapshot()["curtain"], "100")
        self.sim.tick(0.5)
        self.assertEqual(self.sim.snapshot()["curtain"], "0")
        self.assertCommand("curtain", "open")
        self.assertCommand("curtain", "auto")
        self.assertEqual(self.sim.snapshot()["curtain"], "0")
        self.sim.set_input("lux", "300")
        self.assertCommand("curtain", "close")
        self.assertEqual(self.sim.snapshot()["curtain"], "0")
        self.sim.tick(60)
        self.assertEqual(self.sim.snapshot()["curtain"], "100")

    def test_invalid_commands_and_inputs_do_not_change_state(self) -> None:
        before = self.sim.state.copy()
        for action, value in (
            ("living", "101"), ("hall", "-1"), ("bedroom", "1.5"),
            ("window", "ajar"), ("curtain", "50"), ("scene", "party"),
            ("load_switch", "2"), ("mute", "0"), ("timer_start", "0"),
            ("timer_start", "86401"), ("timer_pause", "0"), ("load_keep", "0"),
        ):
            with self.subTest(action=action, value=value):
                self.assertFalse(self.sim.command(action, value)[0])
                self.assertEqual(self.sim.state, before)
        with self.assertRaises(ProtocolError):
            self.sim.set_input("temp", "1251")
        with self.assertRaises(ValueError):
            self.sim.set_input("unsupported", "0")
        for dt in (-1, math.inf, math.nan, True):
            with self.subTest(dt=dt), self.assertRaises(ValueError):
                self.sim.tick(dt)
        self.assertEqual(self.sim.state, before)


if __name__ == "__main__":
    unittest.main()
