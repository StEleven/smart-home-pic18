"""Deterministic host-only mirror of the house control rules.

Temperature ventilation uses 30 C, shading 500/300 lx and three-second
confirmation. Door, window, curtain and ordinary lighting takeovers last
60 seconds. AC manual mode persists until auto or an away scene. KTV uses
one retained master level; learning has its own white pixel overlay.
"""

from __future__ import annotations

import math
import uuid

from .protocol import validate_state


class Simulator:
    capabilities = ("scene", "ktv", "door", "window", "curtain", "lights", "light_effect", "loads", "mute", "timer", "demand", "demand_hold", "night")
    HOT_TEMP = 300  # Tenths of degrees C; offline demonstration threshold.
    STRONG_LIGHT = 500
    WEAK_LIGHT = 300
    SHADE_CONFIRM_SECONDS = 3.0
    MANUAL_SECONDS = 60.0
    _SCENES = frozenset({"home", "away", "long_away", "sleep", "movie", "ktv", "unknown"})
    _INPUTS = frozenset({"temp", "humid", "lux", "rain", "water", "door", "window", "demand"})
    _LIGHT_PRESETS = {
        "home": (70, 40, 30),
        "away": (0, 0, 0),
        "long_away": (0, 0, 0),
        "sleep": (0, 0, 0),
        "movie": (20, 0, 10),
        "ktv": (50, 50, 50),
        "unknown": (0, 0, 0),
    }

    def __init__(self) -> None:
        self.state: dict[str, str] = {
            "boot": "SIM-" + uuid.uuid4().hex[:12],
            "seq": "0", "uptime": "0",
            "temp": "260", "humid": "500", "lux": "300",
            "rain": "0", "water": "0", "door": "1", "window": "1",
            "door_target": "0", "window_target": "0", "curtain": "100", "vent": "0",
            "living": "70", "bedroom": "40", "hall": "30",
            "light_effect": "warm", "ktv_brightness": "50", "demand_mode": "auto",
            "load_keep": "1", "load_switch": "1", "cooling": "0", "demand": "0",
            "scene": "home", "control": "auto", "manual_ms": "0",
            "timer": "idle", "timer_s": "0", "muted": "0",
            "state_source": "commanded", "comfort": "2", "setpoint10": "315", "alarm": "0", "night": "0",
        }
        self._uptime = 0.0
        self._light_effect_started = 0.0
        self._timer_started = 0.0
        self._manual_remaining = 0.0
        self._manual_target = 0
        self._timer_remaining = 0.0
        self._night_remaining = 0.0
        self._window_feedback: str | None = None
        self._door_feedback: str | None = None
        self._door_manual_remaining = 0.0
        self._door_manual_target = "0"
        self._demand_override: str | None = None
        self._automatic_demand = False
        self._curtain_shaded = False
        self._shade_candidate: bool | None = None
        self._shade_elapsed = 0.0
        self._output_manual_remaining = {
            "living": 0.0, "bedroom": 0.0, "hall": 0.0, "curtain": 0.0
        }
        self._evaluate()

    def _end_manual(self) -> None:
        self._manual_remaining = 0.0
        self.state["control"] = "auto"
        self.state["manual_ms"] = "0"

    def _update_shading(self, dt_seconds: float = 0.0) -> None:
        lux = self.state['lux']
        if lux == '?':
            self._shade_candidate = None
            self._shade_elapsed = 0.0
            return
        requested = (True if int(lux) >= self.STRONG_LIGHT else
                     False if int(lux) <= self.WEAK_LIGHT else self._curtain_shaded)
        if requested == self._curtain_shaded:
            self._shade_candidate = None
            self._shade_elapsed = 0.0
        elif requested != self._shade_candidate:
            self._shade_candidate = requested
            self._shade_elapsed = 0.0
        else:
            self._shade_elapsed += dt_seconds
            if self._shade_elapsed >= self.SHADE_CONFIRM_SECONDS:
                self._curtain_shaded = requested
                self._shade_candidate = None
                self._shade_elapsed = 0.0

    def _evaluate(self) -> None:
        self._update_shading()
        state = self.state
        scene = state["scene"]
        locked = scene == "long_away"
        if self._door_manual_remaining > 0:
            state["door_target"] = self._door_manual_target
        else:
            state["door_target"] = "100" if scene == "home" else "0"
        state["door"] = (self._door_feedback if self._door_feedback is not None
                         else "?" if state["door_target"] == "?"
                         else "1" if state["door_target"] == "0" else "0")
        if state["temp"] == "?":
            self._automatic_demand = False
        else:
            setpoint = 315 if state["setpoint10"] == "?" else int(state["setpoint10"])
            temperature = int(state["temp"])
            if temperature >= setpoint + 5:
                self._automatic_demand = True
            elif temperature <= setpoint - 5:
                self._automatic_demand = False
        state["demand"] = ("1" if state["demand_mode"] == "on" else
                           "0" if state["demand_mode"] == "off" else
                           self._demand_override if self._demand_override is not None else
                           "?" if state["temp"] == "?" else "1" if self._automatic_demand else "0")
        state["comfort"] = ("0" if state["humid"] == "?" else
                            "1" if int(state["humid"]) < 400 else
                            "3" if int(state["humid"]) > 600 else "2")
        # Unknown rain is treated conservatively while the sample is missing.
        rain_safe = state["rain"] == "0"
        if locked or not rain_safe:
            self._end_manual()
            target = 0
        elif self._manual_remaining > 0:
            target = self._manual_target
        else:
            self._end_manual()
            hot = state["temp"] != "?" and int(state["temp"]) >= self.HOT_TEMP
            ventilate = scene in {"home", "away"} and hot and state["demand"] == "0"
            target = 100 if ventilate else 0
        state["window_target"] = str(target)
        state["manual_ms"] = str(math.ceil(self._manual_remaining * 1000))
        state["window"] = (
            self._window_feedback if self._window_feedback is not None
            else "1" if target == 0 else "0"
        )
        if locked:
            state["load_switch"] = "0"
        state["load_keep"] = "1"
        state["cooling"] = "1" if scene in {"home", "sleep", "movie", "ktv"} and (
            state["demand_mode"] == "on" or (
                state["demand_mode"] == "auto" and state["demand"] == "1"
                and state["temp"] != "?" and state["window"] == "1" and target == 0
            )
        ) else "0"
        state["vent"] = "100" if state["cooling"] == "1" else "0"
        for key, preset in zip(("living", "bedroom", "hall"), self._LIGHT_PRESETS[scene]):
            if scene == "ktv":
                state[key] = state["ktv_brightness"]
            elif self._output_manual_remaining[key] == 0:
                state[key] = "10" if key == 'hall' and scene == 'sleep' and self._night_remaining > 0 else str(preset)
        state['night'] = '1' if self._night_remaining > 0 else '0'
        if self._output_manual_remaining["curtain"] == 0:
            if scene in {"sleep", "movie", "ktv", "long_away"}:
                state["curtain"] = "0"
            elif scene in {"home", "away"} and state["lux"] != "?":
                state["curtain"] = "0" if self._curtain_shaded else "100"
            # With unknown light/scene, retain the last target instead of
            # opening based on a missing reading.
        # Muting is tied to this continuous wet episode. Missing readings do
        # not claim that water cleared and therefore do not clear the latch.
        if state["water"] == "0":
            state["muted"] = "0"
            state["alarm"] = "0"
        elif state["water"] == "1":
            state["alarm"] = "1"

    def tick(self, dt_seconds: float) -> None:
        """Advance simulation time explicitly; wall clock time is never read."""
        if isinstance(dt_seconds, bool) or not isinstance(dt_seconds, (int, float)):
            raise ValueError("time step must be a finite nonnegative number")
        if not math.isfinite(dt_seconds) or dt_seconds < 0:
            raise ValueError("time step must be a finite nonnegative number")
        self._uptime = (self._uptime + dt_seconds % 0x100000000) % 0x100000000
        self._update_shading(dt_seconds)
        self.state["uptime"] = str(int(self._uptime) & 0xFFFFFFFF)
        self._manual_remaining = max(0.0, self._manual_remaining - dt_seconds)
        self._night_remaining = max(0.0, self._night_remaining - dt_seconds)
        self._door_manual_remaining = max(0.0, self._door_manual_remaining - dt_seconds)
        for key, remaining in self._output_manual_remaining.items():
            self._output_manual_remaining[key] = max(0.0, remaining - dt_seconds)
        if self.state["timer"] == "running":
            self._timer_remaining = max(0.0, self._timer_remaining - dt_seconds)
            self.state["timer_s"] = str(math.ceil(self._timer_remaining))
            if self._timer_remaining == 0:
                self.state["timer"] = "done"
        self._evaluate()

    def snapshot(self) -> dict[str, str]:
        """Return a complete independent snapshot with the next uint32 seq."""
        self._evaluate()
        self.state["seq"] = str((int(self.state["seq"]) + 1) & 0xFFFFFFFF)
        return validate_state(self.state)

    @staticmethod
    def _wheel(position: int) -> tuple[int, int, int]:
        position %= 256
        if position < 85:
            return 255 - position * 3, position * 3, 0
        if position < 170:
            return 0, 255 - (position - 85) * 3, (position - 85) * 3
        return (position - 170) * 3, 0, 255 - (position - 170) * 3

    def light_frame(self) -> list[tuple[int, int, int]]:
        """Mirror all eight firmware pixels; animation never changes room STATE."""
        state = self.state
        ktv = state["scene"] == "ktv"
        effect = state["light_effect"] if ktv else "warm"
        elapsed = round(self._uptime * 1000) - round(self._light_effect_started * 1000)
        phase = elapsed // 24
        beat = (elapsed // 180) % 256
        lead = (beat * 5) & 7
        pixels = []
        for index, room in enumerate(("living",) * 3 + ("bedroom",) * 3 + ("hall",) * 2):
            level = int(state["ktv_brightness"] if ktv else state[room])
            if effect in {"rainbow", "pulse"}:
                color = self._wheel(phase + index * 32)
                if effect == "pulse":
                    t = elapsed % 2400
                    triangle = t if t < 1200 else 2400 - t
                    gain = 10 + triangle * 90 // 1200
                    level = level * gain // 100
            elif effect == "party":
                color = self._wheel(beat * 53 + index * 71)
                if index not in {lead, (lead + 3) & 7, (lead + 5) & 7}:
                    level = 0
            else:
                color = (255, 210, 150)
            pixels.append(tuple(component * level // 100 for component in color))
        if not ktv and state["scene"] not in {"away", "long_away"}:
            if state["timer"] == "running":
                t = (round(self._uptime * 1000) - round(self._timer_started * 1000)) % 4000
                triangle = t if t < 2000 else 4000 - t
                white = (10 + triangle // 40) * 255 // 100
                pixels[7] = (white, white, white)
            elif state["timer"] == "paused":
                pixels[7] = (51, 51, 51)
        return pixels

    @property
    def window_feedback(self) -> str:
        """Explicit simulated feedback override, or ``auto`` for output-following."""
        return self._window_feedback if self._window_feedback is not None else "auto"

    @property
    def door_feedback(self) -> str:
        return self._door_feedback if self._door_feedback is not None else "auto"

    def set_input(self, name: str, value: object) -> None:
        """Set a persistent input in SH1 units, or ``?`` for missing data.

        ``door/window='auto'`` releases the simulated feedback override and resumes modeled
        target-following. It is a simulator-only input, never a STATE value.
        """
        if not isinstance(name, str) or name not in self._INPUTS:
            raise ValueError("unsupported simulated input")
        if isinstance(value, bool):
            text = "1" if value else "0"
        elif isinstance(value, (str, int)):
            text = str(value)
        else:
            raise ValueError("input must be an integer or SH1 string")
        if name in {"door", "window"} and text == "auto":
            setattr(self, "_" + name + "_feedback", None)
            self._evaluate()
            return
        candidate = self.state.copy()
        candidate[name] = text
        validate_state(candidate)
        self.state[name] = text
        if name in {"door", "window"}:
            setattr(self, "_" + name + "_feedback", text)
        elif name == "demand":
            self._demand_override = text
            self.state["demand_mode"] = "auto"  # Explicit simulator fault input.
        self._evaluate()

    @staticmethod
    def _bounded_int(value: str, lower: int, upper: int) -> int | None:
        if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
            return None
        try:
            number = int(value)
        except ValueError:
            return None
        return number if lower <= number <= upper else None

    def set_actuator(self, name: str, value: object) -> None:
        """Set a demonstration-only percentage, preserving explicit fault injection."""
        if name != "door":
            raise ValueError("unsupported simulated actuator")
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError("actuator target must be an integer or ?")
        text = str(value)
        validate_state(self.state | {"door_target": text})
        self.state["door_target"] = text
        self._door_manual_target = text
        self._door_manual_remaining = self.MANUAL_SECONDS
        self._evaluate()

    def command(self, action: str, value: str) -> tuple[bool, str]:
        """Execute one offline command and return an ASCII result code."""
        if not isinstance(action, str) or not isinstance(value, str):
            return False, "INVALID_VALUE"
        state = self.state
        if action == "scene":
            if value not in self._SCENES:
                return False, "INVALID_VALUE"
            state["scene"] = value
            self._night_remaining = 0.0
            self._end_manual()
            self._door_manual_remaining = 0.0
            if value in {"away", "long_away"}:
                state["demand_mode"] = "auto"
                self._demand_override = None
            state["light_effect"] = "rainbow" if value == "ktv" else "warm"
            self._light_effect_started = self._uptime
            for key in self._output_manual_remaining:
                self._output_manual_remaining[key] = 0.0
            state["load_switch"] = "0" if value in {"away", "long_away", "sleep", "unknown"} else "1"
        elif action == "door":
            if value not in {"open", "close", "auto"}:
                return False, "INVALID_VALUE"
            if value == "open" and state["scene"] in {"away", "long_away"}:
                return False, "LONG_AWAY" if state["scene"] == "long_away" else "AWAY"
            self._door_manual_remaining = 0.0 if value == "auto" else self.MANUAL_SECONDS
            self._door_manual_target = "100" if value == "open" else "0"
        elif action == "demand":
            if value not in {"0", "1", "auto"}:
                return False, "INVALID_VALUE"
            if value == "1" and state["scene"] in {"away", "long_away"}:
                return False, "AWAY"
            self._demand_override = None
            state["demand_mode"] = {"auto": "auto", "1": "on", "0": "off"}[value]
        elif action == "window":
            if value not in {"open", "close", "auto"}:
                return False, "INVALID_VALUE"
            if value == "open":
                if state["scene"] == "long_away":
                    return False, "LONG_AWAY"
                if state["rain"] != "0":
                    return False, "RAIN" if state["rain"] == "1" else "RAIN_UNKNOWN"
            if value == "auto":
                self._end_manual()
            else:
                self._manual_target = 100 if value == "open" else 0
                self._manual_remaining = self.MANUAL_SECONDS
                state["control"] = "manual"
        elif action == "curtain":
            if value not in {"open", "close", "auto"}:
                return False, "INVALID_VALUE"
            self._output_manual_remaining["curtain"] = 0.0 if value == "auto" else self.MANUAL_SECONDS
            if value != "auto":
                state["curtain"] = "100" if value == "open" else "0"
        elif action == "light_effect":
            if value not in {"warm", "rainbow", "pulse", "party"}:
                return False, "INVALID_VALUE"
            if state["scene"] != "ktv":
                return False, "SCENE"
            self._light_effect_started = self._uptime
            state["light_effect"] = value
        elif action == "ktv_brightness":
            level = self._bounded_int(value, 0, 100)
            if level is None:
                return False, "INVALID_VALUE"
            if state["scene"] != "ktv":
                return False, "SCENE"
            state["ktv_brightness"] = str(level)
        elif action in {"living", "bedroom", "hall"}:
            if state["scene"] == "ktv":
                return False, "SCENE"
            if value not in {"0", "auto"} and state["scene"] == "long_away":
                return False, "LONG_AWAY"
            if value == "auto":
                self._output_manual_remaining[action] = 0.0
            else:
                level = self._bounded_int(value, 0, 100)
                if level is None:
                    return False, "INVALID_VALUE"
                state[action] = str(level)
                self._output_manual_remaining[action] = self.MANUAL_SECONDS
        elif action == "load_switch":
            if value not in {"0", "1"}:
                return False, "INVALID_VALUE"
            if value == "1" and state["scene"] == "long_away":
                return False, "LONG_AWAY"
            state["load_switch"] = value
        elif action == "night":
            if value != '1' or state['scene'] != 'sleep':
                return False, 'INVALID_VALUE'
            self._night_remaining = 30.0
        elif action == "mute":
            if value != "1":
                return False, "INVALID_VALUE"
            if state["alarm"] != "1":
                return False, "NO_WATER_ALARM"
            state["muted"] = "1"
        elif action == "timer_start":
            seconds = self._bounded_int(value, 1, 86400)
            if seconds is None:
                return False, "INVALID_VALUE"
            self._timer_remaining = float(seconds)
            self._timer_started = self._uptime
            state["timer"] = "running"
            state["timer_s"] = str(seconds)
        elif action in {"timer_pause", "timer_resume", "timer_stop"}:
            if value != "1":
                return False, "INVALID_VALUE"
            if action == "timer_pause":
                if state["timer"] != "running":
                    return False, "TIMER_STATE"
                state["timer"] = "paused"
            elif action == "timer_resume":
                if state["timer"] != "paused":
                    return False, "TIMER_STATE"
                state["timer"] = "running"
            else:
                state["timer"] = "idle"
                state["timer_s"] = "0"
                self._timer_remaining = 0.0
        else:
            return False, "UNSUPPORTED"
        self._evaluate()
        return True, "OK"
