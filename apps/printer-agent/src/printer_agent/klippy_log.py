"""Parser for klippy.log.

klippy.log is the richest evidence source a Klipper printer has:

- `Start printer at <date> (<wall> <monotonic>)` anchors Klipper's monotonic
  eventtime to wall-clock time for each (re)start.
- `===== Config file =====` dumps the *effective* config Klipper loaded.
- `Stats <eventtime>: ...` lines, about once a second, carry heater temp/
  target/PWM, MCU link quality (retransmits, rtt) and host load.
- Shutdown reasons, probe/endstop/TMC errors, and on shutdown a dump of the
  last G-code lines received.

Lines without their own timestamp are placed at the most recent Stats
eventtime and flagged approximate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from printer_agent.taxonomy import Taxonomy

_START_RE = re.compile(r"^Start printer at (?P<asc>.+?) \((?P<wall>\d+(?:\.\d+)?) (?P<mono>\d+(?:\.\d+)?)\)")
_STATS_RE = re.compile(r"^Stats (?P<t>\d+(?:\.\d+)?): (?P<body>.*)$")
_VERSION_RE = re.compile(r"^Git version: '?(?P<v>[^']+)'?")
_SHUTDOWN_RE = re.compile(r"^Transition to shutdown state: (?P<reason>.*)$")
_GCODE_DUMP_RE = re.compile(r"^Dumping gcode input (?P<n>\d+) blocks")
_GCODE_READ_RE = re.compile(r"^Read (?P<t>\d+(?:\.\d+)?): (?P<data>.*)$")
_MCU_SHUTDOWN_RE = re.compile(r"^MCU '(?P<mcu>[^']+)' shutdown: (?P<reason>.*)$")
_CONFIG_BEGIN = "===== Config file ====="
_CONFIG_END = "======================="
_GLOBAL_STAT_KEYS = frozenset(
    {
        "gcodein",
        "sysload",
        "cputime",
        "memavail",
        "print_time",
        "buffer_time",
        "print_stall",
        "sd_pos",
    }
)
HEATER_GROUPS = ("extruder", "heater_bed")
# Informational lines worth keeping verbatim: calibration results and
# similar command output that respond_info() also writes to the log.
_NOTE_RE = re.compile(
    r"PID parameters:|probe accuracy results:|Recommended shaper|Mesh Bed Leveling Complete|"
    r": adjust (?:CW|CCW) |probe at .* is z=|Z position: |pressure_advance:|rotation_distance|"
    r"Unknown command",
    re.IGNORECASE,
)


@dataclass(slots=True)
class StatsSample:
    eventtime: float
    groups: dict[str, dict[str, float]]

    def heater(self, name: str) -> dict[str, float] | None:
        return self.groups.get(name)


@dataclass(slots=True)
class LogEvent:
    line_no: int
    text: str
    eventtime: float | None
    kind: str  # start | shutdown | error | warning
    signature: str | None = None
    failure_class: str | None = None
    groups: dict[str, str] = field(default_factory=dict)
    statement: str | None = None
    wall: float | None = None
    approximate: bool = True


@dataclass(slots=True)
class Session:
    index: int
    start_line: int
    start_wall: float | None = None
    start_mono: float | None = None
    anchored_by: str | None = None  # 'start_line' | 'live_offset'
    version: str | None = None
    config_text: str | None = None
    events: list[LogEvent] = field(default_factory=list)
    stats: list[StatsSample] = field(default_factory=list)
    gcode_dump: list[tuple[float, str]] = field(default_factory=list)
    shutdown: LogEvent | None = None
    notes: list[tuple[int, float | None, str]] = field(default_factory=list)

    def to_wall(self, eventtime: float | None) -> float | None:
        if eventtime is None or self.start_wall is None or self.start_mono is None:
            return None
        return self.start_wall + (eventtime - self.start_mono)

    def to_mono(self, wall: float) -> float | None:
        if self.start_wall is None or self.start_mono is None:
            return None
        return self.start_mono + (wall - self.start_wall)

    @property
    def end_wall(self) -> float | None:
        last = self.stats[-1].eventtime if self.stats else None
        if self.events and self.events[-1].eventtime is not None:
            last = max(last or 0.0, self.events[-1].eventtime)
        return self.to_wall(last)


@dataclass(slots=True)
class KlippyLog:
    sessions: list[Session]
    truncated: bool

    def all_events(self) -> list[LogEvent]:
        return [e for s in self.sessions for e in s.events]

    def session_at(self, wall: float) -> Session | None:
        best = None
        for s in self.sessions:
            if s.start_wall is not None and s.start_wall <= wall:
                best = s
        return best


def parse(
    text: str,
    taxonomy: Taxonomy,
    *,
    truncated: bool = False,
    live_offset: float | None = None,
) -> KlippyLog:
    """Parse klippy.log text.

    live_offset (wall - monotonic, from a live Moonraker query) anchors a
    leading session whose `Start printer` line fell outside the fetched tail.
    CLOCK_MONOTONIC is per-boot, so this is only valid if the node has not
    rebooted since; such anchors are flagged.
    """
    sessions: list[Session] = []
    current = Session(index=0, start_line=1)
    in_config = False
    config_lines: list[str] = []
    in_dump = False
    last_t: float | None = None

    def push_event(ev: LogEvent) -> None:
        current.events.append(ev)

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if in_config:
            if line == _CONFIG_END:
                current.config_text = "\n".join(config_lines) + "\n"
                in_config = False
                config_lines = []
            else:
                config_lines.append(line)
            continue
        if line == _CONFIG_BEGIN:
            in_config = True
            config_lines = []
            continue
        m = _START_RE.match(line)
        if m:
            if current.events or current.stats or current.config_text or current.start_wall:
                sessions.append(current)
                current = Session(index=len(sessions), start_line=lineno, version=current.version)
            current.start_wall = float(m.group("wall"))
            current.start_mono = float(m.group("mono"))
            current.anchored_by = "start_line"
            last_t = current.start_mono
            push_event(
                LogEvent(
                    lineno,
                    line,
                    last_t,
                    "start",
                    approximate=False,
                    statement="Klipper (re)started",
                )
            )
            in_dump = False
            continue
        m = _VERSION_RE.match(line)
        if m:
            current.version = m.group("v")
            continue
        m = _STATS_RE.match(line)
        if m:
            last_t = float(m.group("t"))
            current.stats.append(StatsSample(last_t, _parse_stats(m.group("body"))))
            in_dump = False
            continue
        m = _GCODE_DUMP_RE.match(line)
        if m:
            in_dump = True
            current.gcode_dump = []
            continue
        if in_dump:
            m = _GCODE_READ_RE.match(line)
            if m:
                current.gcode_dump.append((float(m.group("t")), _unrepr(m.group("data"))))
                continue
            in_dump = False
        m = _SHUTDOWN_RE.match(line)
        if m:
            reason = m.group("reason")
            match = taxonomy.match(reason)
            ev = LogEvent(lineno, line, last_t, "shutdown", statement=f"Klipper shut down: {reason}")
            if match:
                sig, groups = match
                ev.signature, ev.failure_class, ev.groups = sig.id, sig.failure_class, groups
            current.shutdown = current.shutdown or ev
            push_event(ev)
            continue
        match = taxonomy.match(line)
        if match:
            sig, groups = match
            if _is_duplicate(current, sig.id, lineno):
                continue
            push_event(
                LogEvent(
                    lineno,
                    line,
                    last_t,
                    "error" if sig.fatal else "warning",
                    sig.id,
                    sig.failure_class,
                    groups,
                    sig.statement.format_map(_Default(groups)),
                )
            )
            continue
        m = _MCU_SHUTDOWN_RE.match(line)
        if m:
            push_event(
                LogEvent(
                    lineno,
                    line,
                    last_t,
                    "error",
                    statement=f"MCU {m.group('mcu')} shutdown: {m.group('reason')}",
                )
            )
            continue
        if _NOTE_RE.search(line):
            current.notes.append((lineno, last_t, line))
    if in_config and config_lines:
        current.config_text = "\n".join(config_lines) + "\n"
    sessions.append(current)

    if live_offset is not None:
        first = sessions[0]
        if first.start_wall is None:
            first.start_mono = 0.0
            first.start_wall = live_offset
            first.anchored_by = "live_offset"
    for s in sessions:
        for ev in s.events:
            ev.wall = s.to_wall(ev.eventtime)
    return KlippyLog(sessions=[s for s in sessions if s.events or s.stats or s.config_text], truncated=truncated)


def _is_duplicate(session: Session, sig_id: str, lineno: int) -> bool:
    # Klipper often logs the same error twice in a row (logged + echoed).
    return any(e.signature == sig_id and lineno - e.line_no <= 3 for e in session.events[-3:])


class _Default(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return f"<{key}>"


def _parse_stats(body: str) -> dict[str, dict[str, float]]:
    groups: dict[str, dict[str, float]] = {"_": {}}
    current = "_"
    for tok in body.split():
        if tok.endswith(":") and "=" not in tok:
            current = tok[:-1]
            groups.setdefault(current, {})
            continue
        if "=" not in tok:
            continue
        key, _, val = tok.partition("=")
        try:
            num = float(val)
        except ValueError:
            continue
        target = "_" if key in _GLOBAL_STAT_KEYS else current
        groups.setdefault(target, {})[key] = num
    return groups


def _unrepr(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1]
    return s.replace("\\n", "\n").strip()


# ------------------------------------------------------------- analysis


def heater_trace(
    session: Session, heater: str, *, end_mono: float | None = None, window: float = 300.0
) -> list[dict[str, float]]:
    """Samples of {t, temp, target, pwm} for a heater in the window before end."""
    if not session.stats:
        return []
    end = end_mono if end_mono is not None else session.stats[-1].eventtime
    out = []
    for s in session.stats:
        if s.eventtime > end or s.eventtime < end - window:
            continue
        h = s.heater(heater)
        if h and "temp" in h:
            out.append(
                {
                    "t": s.eventtime,
                    "temp": h.get("temp", 0.0),
                    "target": h.get("target", 0.0),
                    "pwm": h.get("pwm", 0.0),
                }
            )
    return out


def link_trend(
    session: Session, mcu: str = "mcu", *, end_mono: float | None = None, window: float = 300.0
) -> dict[str, Any] | None:
    """Change in MCU link error counters and host load over the window."""
    samples = [
        s
        for s in session.stats
        if (end_mono is None or s.eventtime <= end_mono) and (end_mono is None or s.eventtime >= end_mono - window)
    ]
    if len(samples) < 2:
        return None
    first, last = samples[0], samples[-1]
    f_mcu, l_mcu = first.groups.get(mcu, {}), last.groups.get(mcu, {})
    loads = [s.groups["_"].get("sysload") for s in samples if "sysload" in s.groups["_"]]
    mem = [s.groups["_"].get("memavail") for s in samples if "memavail" in s.groups["_"]]
    return {
        "window_s": round(last.eventtime - first.eventtime, 1),
        "retransmit_bytes": l_mcu.get("bytes_retransmit", 0) - f_mcu.get("bytes_retransmit", 0),
        "invalid_bytes": l_mcu.get("bytes_invalid", 0) - f_mcu.get("bytes_invalid", 0),
        "srtt_last": l_mcu.get("srtt"),
        "max_sysload": max((x for x in loads if x is not None), default=None),
        "min_memavail_kb": min((x for x in mem if x is not None), default=None),
    }
