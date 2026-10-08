"""Static G-code analysis. Nothing here executes or sends G-code.

Understands PrusaSlicer output (header, embedded `; prusaslicer_config`
block) and cross-references the printer's Klipper config: macros the file
calls, travel limits, temperature limits, and Klipper-specific command
parameters.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from printer_agent.klipper_config import KlipperConfig

# Commands Klipper implements natively (not exhaustive for extras, but covers
# what slicers emit). Unknown commands are only *reported*: Klipper answers
# them with "Unknown command" and continues the print.
KLIPPER_BUILTINS = frozenset(
    [
        "G0",
        "G1",
        "G2",
        "G3",
        "G4",
        "G10",
        "G11",
        "G17",
        "G18",
        "G19",
        "G20",
        "G21",
        "G28",
        "G90",
        "G91",
        "G92",
        "M17",
        "M18",
        "M82",
        "M83",
        "M84",
        "M104",
        "M105",
        "M106",
        "M107",
        "M109",
        "M110",
        "M112",
        "M114",
        "M115",
        "M117",
        "M118",
        "M119",
        "M140",
        "M190",
        "M204",
        "M220",
        "M221",
        "M400",
        "M486",
        "M600",
        "M73",
        "M141",
        "M191",
        "M20",
        "M21",
        "M23",
        "M24",
        "M25",
        "M26",
        "M27",
        "M28",
        "M29",
        "M30",
        "M32",
        "M701",
        "M702",
        "M300",
        "M106",
        "M108",
        "SET_VELOCITY_LIMIT",
        "SET_PRESSURE_ADVANCE",
        "BED_MESH_CALIBRATE",
        "BED_MESH_PROFILE",
        "BED_MESH_CLEAR",
        "BED_MESH_OUTPUT",
        "BED_MESH_MAP",
        "BED_MESH_OFFSET",
        "PROBE",
        "PROBE_CALIBRATE",
        "PROBE_ACCURACY",
        "QUERY_PROBE",
        "Z_OFFSET_APPLY_PROBE",
        "SET_GCODE_OFFSET",
        "SAVE_GCODE_STATE",
        "RESTORE_GCODE_STATE",
        "SET_HEATER_TEMPERATURE",
        "TEMPERATURE_WAIT",
        "SET_FAN_SPEED",
        "SET_PIN",
        "SET_LED",
        "EXCLUDE_OBJECT",
        "EXCLUDE_OBJECT_DEFINE",
        "EXCLUDE_OBJECT_START",
        "EXCLUDE_OBJECT_END",
        "PAUSE",
        "RESUME",
        "CLEAR_PAUSE",
        "CANCEL_PRINT",
        "SDCARD_RESET_FILE",
        "TURN_OFF_HEATERS",
        "RESPOND",
        "STATUS",
        "RESTART",
        "FIRMWARE_RESTART",
        "SET_RETRACTION",
        "SET_INPUT_SHAPER",
        "SET_KINEMATIC_POSITION",
        "SCREWS_TILT_CALCULATE",
        "BED_SCREWS_ADJUST",
        "UPDATE_DELAYED_GCODE",
        "SET_IDLE_TIMEOUT",
        "SET_FILAMENT_SENSOR",
        "SET_PRINT_STATS_INFO",
        "SET_DISPLAY_TEXT",
        "SET_STEPPER_ENABLE",
        "ACTIVATE_EXTRUDER",
        "SET_EXTRUDER_ROTATION_DISTANCE",
        "SAVE_VARIABLE",
        "SAVE_CONFIG",
        "Z_TILT_ADJUST",
        "QUAD_GANTRY_LEVEL",
        "BLTOUCH_DEBUG",
        "BLTOUCH_STORE",
        "GET_POSITION",
        "QUERY_ENDSTOPS",
        "M220",
        "M221",
    ]
)
# Marlin commands PrusaSlicer emits with gcode_flavor=marlin/marlin2 that
# Klipper does not implement; their limits are silently not applied.
MARLIN_ONLY = {
    "M201": "max acceleration",
    "M203": "max feedrate",
    "M205": "jerk",
    "M900": "linear advance",
    "M907": "motor current",
    "M593": "input shaping",
}
BED_MESH_CALIBRATE_PARAMS = frozenset(
    {
        "PROFILE",
        "METHOD",
        "HORIZONTAL_MOVE_Z",
        "MESH_MIN",
        "MESH_MAX",
        "PROBE_COUNT",
        "MESH_RADIUS",
        "MESH_ORIGIN",
        "ROUND_PROBE_COUNT",
        "ALGORITHM",
        "ADAPTIVE",
        "ADAPTIVE_MARGIN",
        "SPEED",
        "SAMPLES",
        "SAMPLE_RETRACT_DIST",
        "SAMPLES_TOLERANCE",
        "SAMPLES_TOLERANCE_RETRIES",
        "LIFT_SPEED",
        "SAMPLES_RESULT",
        "PROBE_SPEED",
        "SCAN_MODE",
        "SCAN_SPEED",
        "ZERO_REFERENCE_POSITION",
    }
)
_WORD_RE = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+)")
_KLIPPER_PARAM_RE = re.compile(r"(\w+)\s*=\s*(\"[^\"]*\"|\S+)")


@dataclass(slots=True)
class Occurrence:
    line: int
    text: str
    section: str  # 'start' | 'body' | 'end'


@dataclass(slots=True)
class GcodeReport:
    lines: int = 0
    slicer: str | None = None
    slicer_config: dict[str, str] = field(default_factory=dict)
    homes: list[Occurrence] = field(default_factory=list)
    mesh_ops: list[Occurrence] = field(default_factory=list)
    temp_cmds: list[Occurrence] = field(default_factory=list)
    unknown_commands: dict[str, int] = field(default_factory=dict)
    marlin_only: dict[str, int] = field(default_factory=dict)
    macro_calls: dict[str, int] = field(default_factory=dict)
    bounds: dict[str, list[float]] = field(default_factory=dict)  # extruding moves only
    travel_bounds: dict[str, list[float]] = field(default_factory=dict)
    first_extrusion_line: int | None = None
    max_feedrate_mm_s: float = 0.0
    layer_changes: int = 0
    findings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        keep = (
            "layer_height",
            "first_layer_height",
            "temperature",
            "first_layer_temperature",
            "bed_temperature",
            "first_layer_bed_temperature",
            "gcode_flavor",
            "retract_length",
            "retract_speed",
            "nozzle_diameter",
            "filament_type",
            "filament_settings_id",
            "printer_settings_id",
            "print_settings_id",
            "bed_shape",
            "max_print_height",
            "z_offset",
            "perimeter_speed",
            "first_layer_speed",
            "travel_speed",
            "default_acceleration",
            "first_layer_acceleration",
            "extrusion_multiplier",
            "use_relative_e_distances",
            "start_gcode",
            "end_gcode",
            "machine_max_acceleration_x",
        )
        return {
            "lines": self.lines,
            "slicer": self.slicer,
            "slicer_settings": {k: self.slicer_config[k] for k in keep if k in self.slicer_config},
            "homing_commands": [asdict(o) for o in self.homes],
            "bed_mesh_commands": [asdict(o) for o in self.mesh_ops],
            "temperature_commands": [asdict(o) for o in self.temp_cmds[:20]],
            "macro_calls": self.macro_calls,
            "unknown_commands": self.unknown_commands,
            "marlin_only_commands": self.marlin_only,
            "extrusion_bounds": self.bounds,
            "travel_bounds": self.travel_bounds,
            "first_extrusion_line": self.first_extrusion_line,
            "max_feedrate_mm_s": round(self.max_feedrate_mm_s, 1),
            "layer_changes": self.layer_changes,
            "findings": self.findings,
        }


def inspect(text: str, cfg: KlipperConfig | None = None) -> GcodeReport:
    rep = GcodeReport()
    lines = text.splitlines()
    rep.lines = len(lines)
    _read_slicer_metadata(lines, rep)
    macros = cfg.macros() if cfg else {}
    absolute, rel_e = True, False
    pos = {"X": 0.0, "Y": 0.0, "Z": 0.0, "E": 0.0}
    section = "start"
    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith(";"):
            low = stripped.lower()
            if low.startswith((";layer_change", ";before_layer_change", ";layer:")):
                rep.layer_changes += 1
                section = "body"
            elif "prusaslicer_config = begin" in low:
                break
            elif low.startswith("; filament used") or low.startswith(";end gcode") or "end of print" in low:
                section = "end"
            continue
        code = stripped.split(";", 1)[0].strip()
        if not code:
            continue
        cmd = code.split()[0].upper()
        if cmd in ("G0", "G1", "G2", "G3"):
            words = {k.upper(): float(v) for k, v in _WORD_RE.findall(code[len(cmd) :])}
            if "F" in words:
                rep.max_feedrate_mm_s = max(rep.max_feedrate_mm_s, words["F"] / 60.0)
            extruding = False
            for axis in ("X", "Y", "Z"):
                if axis in words:
                    pos[axis] = words[axis] if absolute else pos[axis] + words[axis]
            if "E" in words:
                de = words["E"] if rel_e else words["E"] - pos["E"]
                pos["E"] = pos["E"] + words["E"] if rel_e else words["E"]
                extruding = de > 0 and any(a in words for a in ("X", "Y"))
            target = rep.bounds if extruding else rep.travel_bounds
            for axis in ("X", "Y", "Z"):
                if axis in words:
                    b = target.setdefault(axis, [pos[axis], pos[axis]])
                    b[0], b[1] = min(b[0], pos[axis]), max(b[1], pos[axis])
            if extruding and rep.first_extrusion_line is None:
                rep.first_extrusion_line = i
            continue
        occ = Occurrence(i, code[:120], section)
        if cmd == "G90":
            absolute = True
        elif cmd == "G91":
            absolute = False
        elif cmd == "M82":
            rel_e = False
        elif cmd == "M83":
            rel_e = True
        elif cmd == "G92":
            words = {k.upper(): float(v) for k, v in _WORD_RE.findall(code[3:])}
            for axis, val in words.items():
                if axis in pos:
                    pos[axis] = val
        if cmd == "G28":
            rep.homes.append(occ)
        elif cmd.startswith("BED_MESH"):
            rep.mesh_ops.append(occ)
        elif cmd in ("M104", "M109", "M140", "M190", "SET_HEATER_TEMPERATURE", "TEMPERATURE_WAIT"):
            rep.temp_cmds.append(occ)
        if cmd in MARLIN_ONLY:
            rep.marlin_only[cmd] = rep.marlin_only.get(cmd, 0) + 1
        elif cmd in macros:
            rep.macro_calls[cmd] = rep.macro_calls.get(cmd, 0) + 1
            body = (macros[cmd].get("gcode") or "").upper()
            if re.search(r"\bG28\b", body):
                rep.homes.append(Occurrence(i, f"{cmd} (macro contains G28)", section))
            if "BED_MESH_CALIBRATE" in body:
                rep.mesh_ops.append(Occurrence(i, f"{cmd} (macro contains BED_MESH_CALIBRATE)", section))
        elif cmd not in KLIPPER_BUILTINS:
            rep.unknown_commands[cmd] = rep.unknown_commands.get(cmd, 0) + 1
    _findings(rep, cfg)
    return rep


def _read_slicer_metadata(lines: list[str], rep: GcodeReport) -> None:
    for line in lines[:5]:
        if "generated by" in line.lower():
            rep.slicer = line.lstrip("; ").strip()
            break
    in_cfg = False
    for line in lines[-2000:] if len(lines) > 2000 else lines:
        s = line.strip()
        if s == "; prusaslicer_config = begin":
            in_cfg = True
            continue
        if s == "; prusaslicer_config = end":
            break
        if in_cfg and s.startswith("; ") and " = " in s:
            k, _, v = s[2:].partition(" = ")
            rep.slicer_config[k.strip()] = v.strip()
    if not rep.slicer_config:
        # Older/other slicers: "; key = value" comments at the end.
        for line in lines[-400:]:
            s = line.strip()
            if s.startswith("; ") and " = " in s:
                k, _, v = s[2:].partition(" = ")
                rep.slicer_config.setdefault(k.strip(), v.strip())


def _add(
    rep: GcodeReport,
    severity: str,
    code: str,
    message: str,
    failure_class: str | None = None,
    line: int | None = None,
) -> None:
    d: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if failure_class:
        d["failure_class"] = failure_class
    if line:
        d["line"] = line
    rep.findings.append(d)


def _findings(rep: GcodeReport, cfg: KlipperConfig | None) -> None:
    sc = rep.slicer_config
    flavor = sc.get("gcode_flavor")
    if flavor and flavor != "klipper":
        _add(
            rep,
            "warning",
            "gcode_flavor",
            f"gcode_flavor is {flavor!r}. PrusaSlicer has a 'klipper' flavor; with {flavor} the "
            "machine limits it emits (M201/M203/M205) are ignored by Klipper, so the slicer's time "
            "estimate assumes limits the printer is not using",
            "SLICER.incorrect_profile",
        )
    if rep.marlin_only:
        _add(
            rep,
            "info",
            "marlin_only_commands",
            "Klipper does not implement "
            + ", ".join(f"{c} ({MARLIN_ONLY[c]}) x{n}" for c, n in rep.marlin_only.items())
            + "; each produces 'Unknown command' and is skipped",
            "SLICER.unknown_command",
        )
    if rep.unknown_commands:
        _add(
            rep,
            "warning",
            "unknown_commands",
            "commands not defined as Klipper built-ins or macros in this printer's config: "
            + ", ".join(f"{c} x{n}" for c, n in sorted(rep.unknown_commands.items())),
            "SLICER.unknown_command",
        )
    if len(rep.homes) > 1:
        where = "; ".join(f"line {o.line}: {o.text}" for o in rep.homes)
        _add(
            rep,
            "warning",
            "multiple_homing",
            f"the file homes {len(rep.homes)} times ({where})",
            "SLICER.start_gcode",
        )
    if not rep.homes:
        _add(
            rep,
            "warning",
            "no_homing",
            "the file never homes (G28); it relies on prior state",
            "SLICER.start_gcode",
        )
    for o in rep.mesh_ops:
        if not o.text.upper().startswith("BED_MESH_CALIBRATE"):
            continue
        params = {k.upper() for k, _ in _KLIPPER_PARAM_RE.findall(o.text)}
        bad = params - BED_MESH_CALIBRATE_PARAMS
        if bad:
            msg = (
                f"BED_MESH_CALIBRATE does not accept {', '.join(sorted(bad))} (line {o.line}). "
                "Klipper ignores unknown parameters, so this runs a full probe every print"
            )
            if "LOAD" in bad:
                msg += "; if the intent was to reuse a saved mesh, the command is BED_MESH_PROFILE LOAD=default"
            _add(rep, "warning", "bed_mesh_bad_param", msg, "SLICER.start_gcode", o.line)
    if rep.mesh_ops and rep.homes and rep.mesh_ops[0].line < rep.homes[0].line:
        _add(
            rep,
            "error",
            "mesh_before_home",
            "bed mesh is calibrated before the printer homes",
            "SLICER.start_gcode",
            rep.mesh_ops[0].line,
        )
    if rep.first_extrusion_line is not None:
        waits = [o for o in rep.temp_cmds if o.text.upper().startswith(("M109", "TEMPERATURE_WAIT"))]
        if not waits or waits[0].line > rep.first_extrusion_line:
            _add(
                rep,
                "error",
                "extrude_before_wait",
                f"first extrusion (line {rep.first_extrusion_line}) happens before waiting for the "
                "nozzle temperature (M109)",
                "EXTRUSION.cold_extrusion",
                rep.first_extrusion_line,
            )
    try:
        if float(sc.get("z_offset", "0") or 0) != 0:
            _add(
                rep,
                "warning",
                "slicer_z_offset",
                f"slicer z_offset is {sc['z_offset']}; combined with Klipper's probe z_offset this "
                "shifts every layer and is easy to forget",
                "SLICER.incorrect_profile",
            )
    except ValueError:
        pass
    if cfg is None:
        return
    for axis in ("X", "Y", "Z"):
        sec = cfg.section(f"stepper_{axis.lower()}")
        if sec is None:
            continue
        try:
            lo = float(sec.get("position_min", "0") or 0)
            hi = float(sec.get("position_max", "nan") or "nan")
        except ValueError:
            continue
        for label, bounds in (("extrusion", rep.bounds), ("travel", rep.travel_bounds)):
            b = bounds.get(axis)
            if b and (b[0] < lo - 1e-6 or b[1] > hi + 1e-6):
                _add(
                    rep,
                    "error",
                    "out_of_range",
                    f"{label} moves reach {axis} {b[0]:g}..{b[1]:g} but the config allows "
                    f"{lo:g}..{hi:g}: Klipper will abort with 'Move out of range'",
                    "MOTION.out_of_range",
                )
    for heater, keys in (
        ("extruder", ("temperature", "first_layer_temperature")),
        ("heater_bed", ("bed_temperature", "first_layer_bed_temperature")),
    ):
        max_t = cfg.float_value(heater, "max_temp")
        if max_t is None:
            continue
        for k in keys:
            for v in (sc.get(k) or "").split(","):
                try:
                    t = float(v)
                except ValueError:
                    continue
                if t >= max_t:
                    _add(
                        rep,
                        "error",
                        "temp_over_max",
                        f"slicer {k}={t:g} is at/above {heater} max_temp {max_t:g}",
                        "SLICER.temperature",
                    )
    for o in rep.temp_cmds:
        m = re.search(r"\bS(\d+(?:\.\d+)?)", o.text.upper())
        heater = "heater_bed" if o.text.upper().startswith(("M140", "M190")) else "extruder"
        max_t = cfg.float_value(heater, "max_temp")
        if m and max_t is not None and float(m.group(1)) >= max_t:
            _add(
                rep,
                "error",
                "temp_over_max",
                f"line {o.line} sets {heater} to {m.group(1)} >= max_temp {max_t:g}",
                "SLICER.temperature",
                o.line,
            )
    accel = cfg.float_value("printer", "max_accel")
    for k in ("default_acceleration", "perimeter_acceleration", "infill_acceleration"):
        try:
            slicer_accel = float(sc.get(k, "0") or 0)
        except ValueError:
            continue
        if accel and slicer_accel > accel:
            _add(
                rep,
                "info",
                "accel_above_limit",
                f"slicer {k}={slicer_accel:g} exceeds printer max_accel {accel:g}; Klipper clamps it",
                "SLICER.acceleration",
            )
