"""Small, bounded SH1 serial framing and STATE validation.

All values returned by this module remain strings. ``?`` is an explicit unknown
reading; firmware must emit it in every snapshot while a sensor is invalid or
stale, because SH1 STATE does not carry individual sensor ages.
"""

from __future__ import annotations

import re

MAX_LINE = 1024  # Maximum wire length, including the line terminator.
KINDS = frozenset(
    {"HELLO", "CAPS", "GET", "STATE", "CMD", "ACK", "ERR", "EVENT", "PING", "PONG"}
)
_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}\Z", re.ASCII)
_BOOT = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z", re.ASCII)
_INTEGER = re.compile(r"-?[0-9]+\Z", re.ASCII)
_UNSIGNED = re.compile(r"[0-9]+\Z", re.ASCII)


class ProtocolError(ValueError):
    """A frame or its payload is invalid."""


def _value_text(value: object, *, allow_empty: bool = False) -> str:
    # Integer command IDs are convenient for callers; booleans are deliberately
    # excluded, since Python's "True" is not a SH1 numeric value.
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ProtocolError("field values must be nonempty ASCII text")
    if any(ord(char) < 32 or ord(char) > 126 or char in "|=" for char in value):
        raise ProtocolError("illegal field value")
    return value


def _check_key(key: object) -> None:
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ProtocolError("illegal field key")


def encode(kind: str, **fields: object) -> bytes:
    """Encode one SH1 frame; field insertion order is retained."""
    if not isinstance(kind, str) or kind not in KINDS:
        raise ProtocolError("unsupported frame kind")
    parts = ["SH1", kind]
    for key, value in fields.items():
        _check_key(key)
        text = _value_text(value, allow_empty=kind == "CAPS" and key == "caps")
        parts.append(f"{key}={text}")
    wire = ("|".join(parts) + "\n").encode("ascii")
    if len(wire) > MAX_LINE:
        raise ProtocolError("frame exceeds MAX_LINE")
    return wire


def parse(line: bytes) -> tuple[str, dict[str, str]]:
    """Parse an LF/CRLF frame, or a single frame without its terminator.

    Syntax validation is separate from payload validation. Call
    :func:`validate_state` before using a STATE payload.
    """
    if not isinstance(line, bytes):
        raise ProtocolError("frame must be bytes")
    if not line or len(line) > MAX_LINE:
        raise ProtocolError("empty or oversized frame")
    body = line
    if body.endswith(b"\n"):
        body = body[:-1]
        if body.endswith(b"\r"):
            body = body[:-1]
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ProtocolError("frame must be ASCII") from exc
    if any(ord(char) < 32 or ord(char) > 126 for char in text):
        raise ProtocolError("control character in frame")
    parts = text.split("|")
    if len(parts) < 2 or parts[0] != "SH1" or parts[1] not in KINDS:
        raise ProtocolError("invalid prefix or frame kind")
    fields: dict[str, str] = {}
    for part in parts[2:]:
        if part.count("=") != 1:
            raise ProtocolError("malformed field")
        key, value = part.split("=", 1)
        _check_key(key)
        if key in fields:
            raise ProtocolError("duplicate field")
        fields[key] = _value_text(value, allow_empty=parts[1] == "CAPS" and key == "caps")
    return parts[1], fields


class LineFramer:
    """Accumulate serial fragments without an unbounded line buffer.

    Complete lines include their LF. An overlong line increments ``errors``
    once, then is discarded through its next LF so a suffix cannot become a
    seemingly valid frame. Call ``reset`` when a connection is replaced.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._discarding = False
        self.errors = 0

    def reset(self) -> None:
        self._buffer.clear()
        self._discarding = False
        self.errors = 0

    def feed(self, data: bytes) -> list[bytes]:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("serial data must be bytes")
        lines: list[bytes] = []
        for byte in data:
            if self._discarding:
                if byte == 10:
                    self._discarding = False
                continue
            self._buffer.append(byte)
            if len(self._buffer) > MAX_LINE:
                self._buffer.clear()
                self.errors += 1
                self._discarding = byte != 10
            elif byte == 10:
                lines.append(bytes(self._buffer))
                self._buffer.clear()
        return lines


_RANGES: dict[str, tuple[int, int, bool]] = {
    "seq": (0, 0xFFFFFFFF, False),
    "uptime": (0, 0xFFFFFFFF, False),
    "temp": (-400, 1250, True),
    "humid": (0, 1000, True),
    "lux": (0, 200000, True),
    "rain": (0, 1, True),
    "water": (0, 1, True),
    "door": (0, 1, True),
    "window": (0, 1, True),
    "window_target": (0, 100, True),
    "curtain": (0, 100, True),
    "vent": (0, 100, True),
    "living": (0, 100, True),
    "bedroom": (0, 100, True),
    "hall": (0, 100, True),
    "load_keep": (0, 1, True),
    "load_switch": (0, 1, True),
    "cooling": (0, 1, True),
    "demand": (0, 1, True),
    "manual_ms": (0, 600000, False),
    "timer_s": (0, 86400, False),
    "muted": (0, 1, True),
}
_ENUMS: dict[str, frozenset[str]] = {
    "scene": frozenset({"home", "away", "long_away", "sleep", "movie", "ktv", "unknown"}),
    "control": frozenset({"auto", "manual", "unknown"}),
    "timer": frozenset({"idle", "running", "paused", "done", "unknown"}),
}
STATE_KEYS = frozenset({"boot", *_RANGES, *_ENUMS})
# Optional output targets do not change the original mandatory schema.
_OPTIONAL_RANGES = {"door_target": (0, 100, True), "comfort": (0, 3, False),
                    "setpoint10": (200, 320, True), "away_check_ok": (0, 1, False),
                    "door_manual_ms": (0, 600000, False), "curtain_manual_ms": (0, 600000, False),
                    "living_manual_ms": (0, 600000, False), "bedroom_manual_ms": (0, 600000, False),
                    "hall_manual_ms": (0, 600000, False), "night": (0, 1, False),
                    "alarm": (0, 1, False), "ktv_brightness": (0, 100, False)}
_OPTIONAL_ENUMS = {"state_source": frozenset({"commanded"}),
                   "light_effect": frozenset({"warm", "rainbow", "pulse", "party"}),
                   "demand_mode": frozenset({"auto", "on", "off"})}


def validate_state(fields: dict[str, str]) -> dict[str, str]:
    """Return an independent validated full snapshot, retaining future fields."""
    if not isinstance(fields, dict):
        raise ProtocolError("STATE fields must be a dictionary")
    if not STATE_KEYS.issubset(fields):
        missing = ",".join(sorted(STATE_KEYS.difference(fields)))
        raise ProtocolError(f"STATE is missing fields: {missing}")
    for key, value in fields.items():
        _check_key(key)
        if not isinstance(value, str):
            raise ProtocolError("STATE values must be strings")
        _value_text(value)
    if not _BOOT.fullmatch(fields["boot"]):
        raise ProtocolError("invalid boot token")
    ranges = _RANGES | {key: bounds for key, bounds in _OPTIONAL_RANGES.items() if key in fields}
    for key, (lower, upper, allow_unknown) in ranges.items():
        value = fields[key]
        if allow_unknown and value == "?":
            continue
        pattern = _UNSIGNED if lower >= 0 else _INTEGER
        if not pattern.fullmatch(value):
            raise ProtocolError(f"invalid integer for {key}")
        try:
            number = int(value)
        except ValueError as exc:
            raise ProtocolError(f"invalid integer for {key}") from exc
        if not lower <= number <= upper:
            raise ProtocolError(f"out of range: {key}")
    enums = _ENUMS | {key: choices for key, choices in _OPTIONAL_ENUMS.items() if key in fields}
    for key, choices in enums.items():
        if fields[key] not in choices:
            raise ProtocolError(f"invalid enum for {key}")
    return fields.copy()
