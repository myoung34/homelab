"""Semantic understanding of Klipper configuration.

Parses printer.cfg the way Klipper does (configparser semantics, inline
comments, indented continuation lines, and the `#*#` SAVE_CONFIG block that
overrides earlier values), then provides:

- an effective view (user sections with the autosave block applied),
- static validation with findings tied to section/option/line,
- a semantic diff whose entries are risk-classified,
- minimal, format-preserving edits for remediation proposals.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from printer_agent.safety import RiskLevel

AUTOSAVE_HEADER = "#*# <---------------------- SAVE_CONFIG ---------------------->"
_AUTOSAVE_PREFIX = "#*#"
_SECTION_RE = re.compile(r"^\[(?P<name>[^\]]+)\]\s*(?:[#;].*)?$")
_OPTION_RE = re.compile(r"^(?P<key>[^:=\s][^:=]*?)\s*[:=]\s?(?P<value>.*)$")
_INLINE_COMMENT_RE = re.compile(r"\s[#;].*$")


class ConfigParseError(Exception):
    pass


@dataclass(slots=True)
class Option:
    name: str
    value: str
    line: int  # 1-based line of the "key: value" line in the source text
    end_line: int  # last line of the value (continuations)
    autosave: bool = False


@dataclass(slots=True)
class Section:
    name: str
    line: int
    options: dict[str, Option] = field(default_factory=dict)
    autosave: bool = False

    @property
    def type(self) -> str:
        return self.name.split()[0]

    @property
    def suffix(self) -> str | None:
        parts = self.name.split(maxsplit=1)
        return parts[1] if len(parts) > 1 else None

    def get(self, option: str, default: str | None = None) -> str | None:
        opt = self.options.get(option)
        return opt.value if opt is not None else default


@dataclass(slots=True)
class KlipperConfig:
    text: str
    user: dict[str, Section]
    autosave: dict[str, Section]
    includes: list[str]
    parse_warnings: list[str]

    @property
    def effective(self) -> dict[str, Section]:
        """User sections with SAVE_CONFIG values applied, as Klipper sees them."""
        out: dict[str, Section] = {}
        for name, sec in self.user.items():
            out[name] = Section(name=name, line=sec.line, options=dict(sec.options))
        for name, sec in self.autosave.items():
            target = out.setdefault(name, Section(name=name, line=sec.line, autosave=True))
            target.options.update(sec.options)
        return out

    def section(self, name: str) -> Section | None:
        return self.effective.get(name)

    def sections_of_type(self, type_: str) -> list[Section]:
        return [s for s in self.effective.values() if s.type == type_]

    def value(self, section: str, option: str) -> str | None:
        sec = self.effective.get(section)
        return sec.get(option) if sec else None

    def float_value(self, section: str, option: str) -> float | None:
        v = self.value(section, option)
        try:
            return float(v) if v is not None else None
        except ValueError:
            return None

    def probe_section(self) -> Section | None:
        eff = self.effective
        for name in ("bltouch", "probe", "smart_effector", "probe_eddy_current"):
            if name in eff:
                return eff[name]
        for sec in eff.values():
            if sec.type in ("probe_eddy_current", "beacon", "cartographer"):
                return sec
        return None

    def macros(self) -> dict[str, Section]:
        return {s.suffix.upper(): s for s in self.sections_of_type("gcode_macro") if s.suffix}

    def to_dict(self, *, include_autosave: bool = True) -> dict[str, dict[str, str]]:
        src = self.effective if include_autosave else self.user
        return {n: {k: o.value for k, o in s.options.items()} for n, s in src.items()}


# ----------------------------------------------------------------- parsing


def parse(text: str) -> KlipperConfig:
    lines = text.splitlines()
    user_lines: list[tuple[int, str]] = []
    autosave_lines: list[tuple[int, str]] = []
    in_autosave = False
    for idx, raw in enumerate(lines, start=1):
        if raw.strip() == AUTOSAVE_HEADER:
            in_autosave = True
            continue
        if in_autosave:
            stripped = raw.strip()
            if stripped.startswith(_AUTOSAVE_PREFIX):
                body = stripped[len(_AUTOSAVE_PREFIX) :]
                body = body[1:] if body.startswith(" ") else body
                # Klipper's AUTOSAVE_HEADER constant includes this line.
                if body.startswith("DO NOT EDIT THIS BLOCK OR BELOW"):
                    continue
                autosave_lines.append((idx, body))
            elif stripped:
                # Klipper refuses SAVE_CONFIG when non-autosave content follows
                # the header; record it rather than silently mis-parse.
                user_lines.append((idx, raw))
        else:
            user_lines.append((idx, raw))
    warnings: list[str] = []
    includes: list[str] = []
    user = _parse_lines(user_lines, autosave=False, warnings=warnings, includes=includes)
    autosave = _parse_lines(autosave_lines, autosave=True, warnings=warnings, includes=[])
    if in_autosave and any(
        line.strip() and not line.strip().startswith(_AUTOSAVE_PREFIX) for line in lines[_header_index(lines) + 1 :]
    ):
        warnings.append(
            "non-autosave content found after the SAVE_CONFIG header; Klipper will refuse "
            "SAVE_CONFIG until it is moved above the header"
        )
    return KlipperConfig(text=text, user=user, autosave=autosave, includes=includes, parse_warnings=warnings)


def _header_index(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        if line.strip() == AUTOSAVE_HEADER:
            return i
    return len(lines)


def _parse_lines(
    lines: Iterable[tuple[int, str]],
    *,
    autosave: bool,
    warnings: list[str],
    includes: list[str],
) -> dict[str, Section]:
    sections: dict[str, Section] = {}
    current: Section | None = None
    last_opt: Option | None = None
    for lineno, raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#", ";")):
            # Full-line comments are dropped (also inside indented gcode bodies,
            # matching configparser). Blank lines keep multi-line values open.
            continue
        indented = raw[:1] in (" ", "\t")
        if indented and last_opt is not None:
            cont = _INLINE_COMMENT_RE.sub("", stripped).rstrip()
            last_opt.value = f"{last_opt.value}\n{cont}" if last_opt.value else cont
            last_opt.end_line = lineno
            continue
        m = _SECTION_RE.match(stripped)
        if m:
            name = " ".join(m.group("name").split())
            last_opt = None
            if name.startswith("include "):
                includes.append(name[len("include ") :].strip())
                current = None
                continue
            existing = sections.get(name)
            if existing is None:
                current = Section(name=name, line=lineno, autosave=autosave)
                sections[name] = current
            else:
                current = existing  # strict=False: duplicate sections merge
            continue
        om = _OPTION_RE.match(stripped)
        if om and current is not None:
            key = om.group("key").strip().lower()
            value = _INLINE_COMMENT_RE.sub("", om.group("value")).strip()
            last_opt = Option(name=key, value=value, line=lineno, end_line=lineno, autosave=autosave)
            current.options[key] = last_opt
            continue
        warnings.append(f"line {lineno}: could not parse {stripped[:60]!r}")
        last_opt = None
    return sections


# ----------------------------------------------------------- knowledge base

# Section types Klipper recognizes (from docs/Config_Reference.md). Anything
# else is reported as a warning: it may be a third-party extra.
KNOWN_SECTION_TYPES = frozenset(
    [
        "mcu",
        "printer",
        "stepper_x",
        "stepper_y",
        "stepper_z",
        "stepper_a",
        "stepper_b",
        "stepper_c",
        "extruder",
        "heater_bed",
        "bed_mesh",
        "bed_tilt",
        "bed_screws",
        "screws_tilt_adjust",
        "z_tilt",
        "quad_gantry_level",
        "safe_z_home",
        "homing_override",
        "endstop_phase",
        "gcode_macro",
        "delayed_gcode",
        "save_variables",
        "idle_timeout",
        "virtual_sdcard",
        "sdcard_loop",
        "force_move",
        "pause_resume",
        "firmware_retraction",
        "gcode_arcs",
        "respond",
        "exclude_object",
        "input_shaper",
        "adxl345",
        "lis2dw",
        "lis3dh",
        "mpu9250",
        "resonance_tester",
        "probe",
        "bltouch",
        "smart_effector",
        "probe_eddy_current",
        "axis_twist_compensation",
        "z_thermal_adjust",
        "stepper_z1",
        "stepper_z2",
        "stepper_z3",
        "extruder_stepper",
        "manual_stepper",
        "verify_heater",
        "homing_heaters",
        "thermistor",
        "adc_temperature",
        "heater_generic",
        "temperature_sensor",
        "temperature_probe",
        "temperature_fan",
        "fan",
        "heater_fan",
        "controller_fan",
        "fan_generic",
        "led",
        "neopixel",
        "dotstar",
        "pca9533",
        "pca9632",
        "servo",
        "gcode_button",
        "output_pin",
        "pwm_tool",
        "pwm_cycle_time",
        "static_digital_output",
        "multi_pin",
        "tmc2130",
        "tmc2208",
        "tmc2209",
        "tmc2660",
        "tmc2240",
        "tmc5160",
        "ad5206",
        "mcp4451",
        "mcp4728",
        "mcp4018",
        "display",
        "display_data",
        "display_template",
        "display_glyph",
        "menu",
        "filament_switch_sensor",
        "filament_motion_sensor",
        "tsl1401cl_filament_width_sensor",
        "hall_filament_width_sensor",
        "load_cell",
        "board_pins",
        "duplicate_pin_override",
        "replicape",
        "palette2",
        "angle",
        "sx1509",
        "samd_sercom",
        "temperature_host",
        "static_digital_output",
        "skew_correction",
        "dual_carriage",
        "extruder1",
        "extruder2",
        "extruder3",
        "gcode_shell_command",
        "display_status",
        "query_adc",
        "statistics",
        "motion_report",
        "bed_mesh_profile",
        "exclude_object_define",
        "tmc2130",
        "dotstar",
    ]
)

SECTION_PURPOSE: dict[str, str] = {
    "mcu": "Connection to the main micro-controller (serial path / CAN uuid).",
    "printer": "Kinematics and global velocity/acceleration limits.",
    "stepper_x": "X axis motor, endstop and travel limits.",
    "stepper_y": "Y axis motor, endstop and travel limits.",
    "stepper_z": "Z axis motor, endstop (or probe virtual endstop) and travel limits.",
    "extruder": "Extruder motor, hotend heater, thermistor and temperature limits.",
    "heater_bed": "Bed heater, thermistor and temperature limits.",
    "verify_heater": "Thermal runaway / heater verification. Weakening it disables a safety system.",
    "bltouch": "BLTouch / 3DTouch probe: sensor and control pins, offsets, sampling.",
    "probe": "Generic Z probe: pin, offsets, sampling.",
    "safe_z_home": "Homes Z at a fixed XY so the probe is over the bed.",
    "bed_mesh": "Probe a grid and compensate Z for bed shape.",
    "screws_tilt_adjust": "Probe at bed screws and report turns to level the bed.",
    "bed_screws": "Manual paper-test assistant for bed screws.",
    "virtual_sdcard": "Printing from files (required for Moonraker/Fluidd printing).",
    "pause_resume": "PAUSE/RESUME support (required by filament sensors and Fluidd).",
    "gcode_macro": "User-defined G-code macro.",
    "delayed_gcode": "Timer-driven G-code.",
    "filament_switch_sensor": "Filament runout switch.",
    "input_shaper": "Resonance compensation.",
    "tmc2209": "Stepper driver UART configuration (current, chopper mode).",
    "fan": "Part cooling fan.",
    "heater_fan": "Fan driven by heater temperature (usually hotend heatsink).",
    "fan_generic": "Manually controlled fan.",
    "display": "LCD and encoder.",
}


@dataclass(frozen=True, slots=True)
class RiskRule:
    section: str  # regex on section *type*
    option: str  # regex on option name
    risk: RiskLevel
    why: str


# Ordered: first match wins. Section-level changes (add/remove whole section)
# are classified by SECTION_RISK below.
OPTION_RISK_RULES: tuple[RiskRule, ...] = (
    RiskRule(r"verify_heater", r".*", RiskLevel.DANGEROUS, "thermal runaway protection"),
    RiskRule(
        r"extruder|heater_bed|heater_generic",
        r"max_temp|min_temp|max_power",
        RiskLevel.DANGEROUS,
        "temperature/power safety limit",
    ),
    RiskRule(
        r"extruder|heater_bed|heater_generic|temperature_fan",
        r"heater_pin|sensor_pin|sensor_type|pullup_resistor|inline_resistor|smooth_time",
        RiskLevel.DANGEROUS,
        "heater or thermistor wiring/identity",
    ),
    RiskRule(r"mcu", r".*", RiskLevel.DANGEROUS, "MCU connection"),
    RiskRule(
        r"printer",
        r"max_velocity|max_accel|max_z_velocity|max_z_accel|kinematics|minimum_cruise_ratio|square_corner_velocity",
        RiskLevel.DANGEROUS,
        "kinematic safety limits",
    ),
    RiskRule(
        r"stepper_.*",
        r"endstop_pin|position_endstop|position_min|position_max|homing_positive_dir",
        RiskLevel.DANGEROUS,
        "endstop / travel limits; wrong values crash the toolhead",
    ),
    RiskRule(
        r"stepper_.*|extruder.*",
        r"step_pin|dir_pin|enable_pin|microsteps|rotation_distance|full_steps_per_rotation|gear_ratio|step_pulse_duration",
        RiskLevel.DANGEROUS,
        "motion scaling / direction",
    ),
    RiskRule(
        r"bltouch|probe|smart_effector|probe_eddy_current",
        r"sensor_pin|control_pin|pin|pin_up_reports_not_triggered|pin_up_touch_mode_reports_triggered|probe_with_touch_mode|stow_on_each_sample|set_output_mode",
        RiskLevel.DANGEROUS,
        "probe trigger behaviour; a probe that never triggers drives the nozzle into the bed",
    ),
    RiskRule(
        r"bltouch|probe|smart_effector",
        r"z_offset",
        RiskLevel.HIGH_RISK_WRITE,
        "nozzle-to-bed distance; too low drags or crashes the nozzle",
    ),
    RiskRule(r"bltouch|probe|smart_effector", r".*", RiskLevel.HIGH_RISK_WRITE, "probe sampling/offsets"),
    RiskRule(r"safe_z_home|homing_override", r".*", RiskLevel.HIGH_RISK_WRITE, "homing sequence"),
    RiskRule(
        r"tmc.*",
        r"run_current|hold_current|sense_resistor|uart_pin|uart_address|tx_pin|cs_pin",
        RiskLevel.HIGH_RISK_WRITE,
        "driver current / addressing",
    ),
    RiskRule(r"tmc.*", r".*", RiskLevel.HIGH_RISK_WRITE, "driver chopper configuration"),
    RiskRule(
        r"extruder|heater_bed|heater_generic",
        r"control|pid_k[pid]|max_delta",
        RiskLevel.HIGH_RISK_WRITE,
        "heater control loop",
    ),
    RiskRule(
        r"extruder",
        r"pressure_advance.*|max_extrude.*|min_extrude_temp|instantaneous_corner_velocity",
        RiskLevel.HIGH_RISK_WRITE,
        "extrusion behaviour",
    ),
    RiskRule(
        r"bed_mesh|bed_tilt|z_tilt|quad_gantry_level|screws_tilt_adjust|axis_twist_compensation",
        r".*",
        RiskLevel.HIGH_RISK_WRITE,
        "bed compensation / probing moves",
    ),
    RiskRule(
        r"gcode_macro|delayed_gcode|homing_override|gcode_button",
        r"gcode|rename_existing",
        RiskLevel.HIGH_RISK_WRITE,
        "macro body runs arbitrary G-code",
    ),
    RiskRule(
        r"stepper_.*",
        r"homing_speed|second_homing_speed|homing_retract_dist",
        RiskLevel.HIGH_RISK_WRITE,
        "homing motion",
    ),
    RiskRule(
        r"fan|heater_fan|controller_fan|temperature_fan|fan_generic",
        r"pin|heater|heater_temp",
        RiskLevel.HIGH_RISK_WRITE,
        "cooling; a dead hotend fan causes heat creep",
    ),
    RiskRule(
        r"input_shaper|firmware_retraction|idle_timeout|virtual_sdcard|filament_.*",
        r".*",
        RiskLevel.HIGH_RISK_WRITE,
        "print behaviour",
    ),
    RiskRule(r".*", r"description|.*_name", RiskLevel.LOW_RISK_WRITE, "cosmetic"),
    RiskRule(
        r"display|display_.*|output_pin|led|neopixel|respond",
        r".*",
        RiskLevel.LOW_RISK_WRITE,
        "UI / indicators",
    ),
    RiskRule(r".*", r".*", RiskLevel.HIGH_RISK_WRITE, "unclassified option (treated as high risk)"),
)

SECTION_RISK: dict[str, RiskLevel] = {
    "verify_heater": RiskLevel.DANGEROUS,
    "mcu": RiskLevel.DANGEROUS,
    "printer": RiskLevel.DANGEROUS,
    "extruder": RiskLevel.DANGEROUS,
    "heater_bed": RiskLevel.DANGEROUS,
    "bltouch": RiskLevel.DANGEROUS,
    "probe": RiskLevel.DANGEROUS,
    "safe_z_home": RiskLevel.DANGEROUS,
    "homing_override": RiskLevel.DANGEROUS,
}


def classify_option_change(section: str, option: str) -> tuple[RiskLevel, str]:
    stype = section.split()[0]
    for rule in OPTION_RISK_RULES:
        if re.fullmatch(rule.section, stype) and re.fullmatch(rule.option, option):
            return rule.risk, rule.why
    return RiskLevel.HIGH_RISK_WRITE, "unclassified"


def classify_section_change(section: str) -> tuple[RiskLevel, str]:
    stype = section.split()[0]
    if stype in SECTION_RISK:
        return SECTION_RISK[stype], f"adding/removing [{stype}] changes a safety-relevant subsystem"
    if stype.startswith("stepper_") or stype.startswith("tmc"):
        return RiskLevel.DANGEROUS, "adding/removing motion hardware"
    if stype in ("display", "output_pin", "led", "neopixel", "respond"):
        return RiskLevel.LOW_RISK_WRITE, "UI section"
    return RiskLevel.HIGH_RISK_WRITE, "section added/removed"


# --------------------------------------------------------------- findings


@dataclass(slots=True)
class Finding:
    severity: str  # error | danger | warning | info
    code: str
    message: str
    section: str | None = None
    option: str | None = None
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in {
                "severity": self.severity,
                "code": self.code,
                "message": self.message,
                "section": self.section,
                "option": self.option,
                "line": self.line,
            }.items()
            if v is not None
        }


_PIN_RE = re.compile(r"^[\^~!]*(?:(?P<chip>[a-z_][a-z0-9_]*):)?(?P<pin>[A-Za-z0-9_.]+)$")
_PIN_OPTIONS = re.compile(r"(^|_)pin$")


def _pin_name(value: str) -> tuple[str | None, str] | None:
    v = value.strip()
    m = _PIN_RE.match(v)
    if not m:
        return None
    return (m.group("chip"), m.group("pin").upper())


def _floats(value: str | None) -> list[float] | None:
    if value is None:
        return None
    try:
        return [float(x) for x in value.replace(" ", "").split(",") if x]
    except ValueError:
        return None


def validate(cfg: KlipperConfig, *, expected_mcu_serial: str | None = None) -> list[Finding]:
    """Static checks Klipper would fail on, plus safety and consistency checks."""
    f: list[Finding] = []
    eff = cfg.effective
    for w in cfg.parse_warnings:
        f.append(Finding("warning", "parse", w))

    def need(sec: str, opts: Iterable[str]) -> None:
        s = eff.get(sec)
        if s is None:
            return
        for o in opts:
            if o not in s.options:
                f.append(Finding("error", "missing_option", f"[{sec}] requires '{o}'", sec, o, s.line))

    for required in ("mcu", "printer"):
        if required not in eff:
            f.append(Finding("error", "missing_section", f"[{required}] section is required", required))
    mcu_sec = eff.get("mcu")
    if mcu_sec is not None and "canbus_uuid" not in mcu_sec.options:
        need("mcu", ["serial"])
    need("printer", ["kinematics", "max_velocity", "max_accel"])
    probe = cfg.probe_section()

    # --- unknown sections
    for name, sec in eff.items():
        if sec.type not in KNOWN_SECTION_TYPES:
            f.append(
                Finding(
                    "warning",
                    "unknown_section",
                    f"[{name}] is not a standard Klipper section (third-party extra or typo?)",
                    name,
                    line=sec.line,
                )
            )

    # --- steppers
    for axis in ("x", "y", "z"):
        name = f"stepper_{axis}"
        s = eff.get(name)
        if s is None:
            continue
        need(
            name,
            [
                "step_pin",
                "dir_pin",
                "enable_pin",
                "rotation_distance",
                "endstop_pin",
                "position_max",
            ],
        )
        endstop = s.get("endstop_pin", "") or ""
        virtual = "z_virtual_endstop" in endstop
        pmin = _floats(s.get("position_min", "0"))
        pmax = _floats(s.get("position_max"))
        pend = _floats(s.get("position_endstop"))
        if virtual:
            if axis != "z":
                f.append(
                    Finding(
                        "error",
                        "virtual_endstop_axis",
                        f"probe virtual endstop is only valid on Z, used on {name}",
                        name,
                        "endstop_pin",
                    )
                )
            if probe is None:
                f.append(
                    Finding(
                        "error",
                        "virtual_endstop_without_probe",
                        f"{name} uses probe:z_virtual_endstop but no [probe]/[bltouch] section exists",
                        name,
                        "endstop_pin",
                        s.options["endstop_pin"].line,
                    )
                )
            if "position_endstop" in s.options:
                f.append(
                    Finding(
                        "error",
                        "position_endstop_with_probe",
                        f"{name} must not set position_endstop when homing with the probe",
                        name,
                        "position_endstop",
                        s.options["position_endstop"].line,
                    )
                )
            if "safe_z_home" not in eff and "homing_override" not in eff:
                f.append(
                    Finding(
                        "warning",
                        "no_safe_z_home",
                        "Z homes with the probe but there is no [safe_z_home]; Z will home "
                        "wherever X/Y happen to be, possibly off the bed",
                        name,
                    )
                )
        elif pend is None and axis in ("x", "y", "z"):
            f.append(
                Finding(
                    "error",
                    "missing_option",
                    f"[{name}] requires position_endstop",
                    name,
                    "position_endstop",
                    s.line,
                )
            )
        if pmin and pmax and pend and not (pmin[0] <= pend[0] <= pmax[0]):
            f.append(
                Finding(
                    "error",
                    "position_endstop_range",
                    f"{name}: position_endstop {pend[0]} outside [{pmin[0]}, {pmax[0]}]",
                    name,
                    "position_endstop",
                    s.options["position_endstop"].line,
                )
            )
        rd = _floats(s.get("rotation_distance"))
        if rd and rd[0] <= 0:
            f.append(
                Finding(
                    "error",
                    "rotation_distance",
                    f"{name}: rotation_distance must be > 0",
                    name,
                    "rotation_distance",
                )
            )

    # --- probe geometry: probe position = nozzle + offset, nozzle must be in limits
    xlim = _axis_limits(eff, "x")
    ylim = _axis_limits(eff, "y")
    if probe is not None:
        xo = _floats(probe.get("x_offset", "0")) or [0.0]
        yo = _floats(probe.get("y_offset", "0")) or [0.0]
        if "z_offset" not in probe.options:
            f.append(
                Finding(
                    "error",
                    "probe_z_offset_missing",
                    f"[{probe.name}] has no z_offset (neither in the section nor in SAVE_CONFIG); run PROBE_CALIBRATE",
                    probe.name,
                    "z_offset",
                    probe.line,
                )
            )
        szh = eff.get("safe_z_home")
        if szh is not None:
            hxy = _floats(szh.get("home_xy_position"))
            if hxy and len(hxy) == 2 and xlim and ylim:
                px, py = hxy[0] + xo[0], hxy[1] + yo[0]
                if not (xlim[0] <= hxy[0] <= xlim[1] and ylim[0] <= hxy[1] <= ylim[1]):
                    f.append(
                        Finding(
                            "error",
                            "safe_z_home_unreachable",
                            f"home_xy_position {hxy} is outside the X/Y travel limits",
                            "safe_z_home",
                            "home_xy_position",
                        )
                    )
                f.append(
                    Finding(
                        "info",
                        "safe_z_home_probe_point",
                        f"Z homes with the nozzle at {hxy[0]:g},{hxy[1]:g}; the probe is then at {px:g},{py:g}",
                        "safe_z_home",
                        "home_xy_position",
                    )
                )
        mesh = eff.get("bed_mesh")
        if mesh is not None and xlim and ylim:
            mn, mx = _floats(mesh.get("mesh_min")), _floats(mesh.get("mesh_max"))
            # mesh_min/max are probe coordinates; the probe can reach
            # [limit_min + offset, limit_max + offset].
            reach_x = (xlim[0] + xo[0], xlim[1] + xo[0])
            reach_y = (ylim[0] + yo[0], ylim[1] + yo[0])
            for label, pt in (("mesh_min", mn), ("mesh_max", mx)):
                if (
                    pt
                    and len(pt) == 2
                    and not (reach_x[0] <= pt[0] <= reach_x[1] and reach_y[0] <= pt[1] <= reach_y[1])
                ):
                    f.append(
                        Finding(
                            "error",
                            "mesh_unreachable",
                            f"bed_mesh {label} {pt[0]:g},{pt[1]:g} is not reachable by the probe "
                            f"(reachable X {reach_x[0]:g}..{reach_x[1]:g}, "
                            f"Y {reach_y[0]:g}..{reach_y[1]:g})",
                            "bed_mesh",
                            label,
                        )
                    )
        for opt in ("sensor_pin", "pin"):
            pv = probe.get(opt)
            if pv and probe.type == "bltouch" and opt == "sensor_pin" and not pv.strip().startswith("^"):
                f.append(
                    Finding(
                        "warning",
                        "bltouch_no_pullup",
                        "BLTouch sensor_pin has no '^' pull-up; most boards need it or the "
                        "signal floats and triggers erratically",
                        probe.name,
                        opt,
                    )
                )
    for sec_name in ("bed_mesh", "screws_tilt_adjust", "z_tilt", "quad_gantry_level"):
        if sec_name in eff and probe is None:
            f.append(Finding("error", "requires_probe", f"[{sec_name}] requires a probe", sec_name))

    # --- heaters / thermal protection
    for heater in ("extruder", "heater_bed"):
        s = eff.get(heater)
        if s is None:
            continue
        req = ["heater_pin", "sensor_type", "sensor_pin", "min_temp", "max_temp"]
        if heater == "extruder":
            req += [
                "nozzle_diameter",
                "filament_diameter",
                "step_pin",
                "dir_pin",
                "rotation_distance",
            ]
        need(heater, req)
        if "control" not in s.options:
            f.append(
                Finding(
                    "error",
                    "missing_option",
                    f"[{heater}] has no 'control' (pid/watermark) in the section or SAVE_CONFIG",
                    heater,
                    "control",
                    s.line,
                )
            )
        mt = _floats(s.get("max_temp"))
        if heater == "extruder" and mt and mt[0] > 285:
            f.append(
                Finding(
                    "info",
                    "high_max_temp",
                    f"extruder max_temp {mt[0]:g}C: only appropriate for an all-metal hotend "
                    "with a matching thermistor",
                    heater,
                    "max_temp",
                )
            )
        if heater == "heater_bed" and mt and mt[0] > 130:
            f.append(
                Finding(
                    "warning",
                    "high_bed_max_temp",
                    f"heater_bed max_temp {mt[0]:g}C is unusually high",
                    heater,
                    "max_temp",
                )
            )
        mint = _floats(s.get("min_extrude_temp"))
        if heater == "extruder" and mint and mint[0] < 150:
            f.append(
                Finding(
                    "warning",
                    "low_min_extrude_temp",
                    f"min_extrude_temp {mint[0]:g}C allows cold extrusion",
                    heater,
                    "min_extrude_temp",
                )
            )
    for vh in cfg.sections_of_type("verify_heater"):
        me = _floats(vh.get("max_error"))
        hy = _floats(vh.get("hysteresis"))
        cg = _floats(vh.get("check_gain_time"))
        if me and me[0] > 600:
            f.append(
                Finding(
                    "danger",
                    "verify_heater_disabled",
                    f"[{vh.name}] max_error {me[0]:g} (default 120) effectively disables thermal "
                    "runaway protection; a detached thermistor would heat until something burns",
                    vh.name,
                    "max_error",
                    vh.options["max_error"].line,
                )
            )
        if hy and hy[0] > 15:
            f.append(
                Finding(
                    "danger",
                    "verify_heater_hysteresis",
                    f"[{vh.name}] hysteresis {hy[0]:g} (default 5) makes runaway detection very lax",
                    vh.name,
                    "hysteresis",
                    vh.options["hysteresis"].line,
                )
            )
        if cg and cg[0] > 120:
            f.append(
                Finding(
                    "warning",
                    "verify_heater_gain_time",
                    f"[{vh.name}] check_gain_time {cg[0]:g}s is long",
                    vh.name,
                    "check_gain_time",
                )
            )

    # --- pins used twice
    f.extend(_pin_conflicts(eff))

    # --- MCU identity against inventory
    mcu = eff.get("mcu")
    if expected_mcu_serial and mcu is not None:
        serial = mcu.get("serial") or ""
        if expected_mcu_serial not in serial:
            f.append(
                Finding(
                    "danger",
                    "mcu_serial_mismatch",
                    f"[mcu] serial {serial!r} does not contain this printer's USB serial "
                    f"{expected_mcu_serial!r} from the inventory; config may belong to another printer",
                    "mcu",
                    "serial",
                    mcu.options["serial"].line if "serial" in mcu.options else None,
                )
            )

    # --- UI/print dependencies
    if "virtual_sdcard" not in eff:
        f.append(
            Finding(
                "warning",
                "no_virtual_sdcard",
                "no [virtual_sdcard]: Moonraker/Fluidd cannot print files",
            )
        )
    if "pause_resume" not in eff:
        for s in eff.values():
            if s.type in ("filament_switch_sensor", "filament_motion_sensor"):
                f.append(
                    Finding(
                        "error",
                        "filament_sensor_without_pause_resume",
                        f"[{s.name}] pauses on runout but [pause_resume] is missing",
                        s.name,
                    )
                )
    macros = cfg.macros()
    vsd = eff.get("virtual_sdcard")
    if (
        vsd
        and (vsd.get("on_error_gcode") or "").strip().upper().split()[:1] == ["CANCEL_PRINT"]
        and "CANCEL_PRINT" not in macros
    ):
        f.append(
            Finding(
                "warning",
                "on_error_macro_missing",
                "virtual_sdcard on_error_gcode calls CANCEL_PRINT, which is not defined as a macro",
                "virtual_sdcard",
                "on_error_gcode",
            )
        )
    for name, sec in macros.items():
        ren = sec.get("rename_existing")
        if ren and ren.upper() in macros:
            f.append(
                Finding(
                    "error",
                    "rename_collision",
                    f"macro {name} renames to {ren}, which is also defined as a macro",
                    sec.name,
                    "rename_existing",
                )
            )
    for sec in cfg.sections_of_type("delayed_gcode"):
        if not (sec.get("gcode") or "").strip():
            f.append(Finding("info", "empty_delayed_gcode", f"[{sec.name}] has an empty gcode body", sec.name))
    return f


def _axis_limits(eff: dict[str, Section], axis: str) -> tuple[float, float] | None:
    s = eff.get(f"stepper_{axis}")
    if s is None:
        return None
    mn = _floats(s.get("position_min", "0"))
    mx = _floats(s.get("position_max"))
    if not mn or not mx:
        return None
    return mn[0], mx[0]


def _pin_conflicts(eff: dict[str, Section]) -> list[Finding]:
    uses: dict[tuple[str | None, str], list[tuple[str, str]]] = {}
    for sec in eff.values():
        if sec.type == "board_pins" or sec.type == "duplicate_pin_override":
            continue
        for opt in sec.options.values():
            if not _PIN_OPTIONS.search(opt.name) or opt.name.endswith("_pins"):
                continue
            if opt.name in ("endstop_pin",) and "virtual_endstop" in opt.value:
                continue
            parsed = _pin_name(opt.value)
            if parsed is None:
                continue
            uses.setdefault(parsed, []).append((sec.name, opt.name))
    out: list[Finding] = []
    for pin, users in uses.items():
        if len(users) < 2:
            continue
        # TMC UART lines are legitimately shared between drivers that use
        # different uart_address values.
        if all(o in ("uart_pin", "tx_pin") for _, o in users):
            addrs = [eff[s].get("uart_address") for s, _ in users]
            by_opt: dict[str, list[str | None]] = {}
            for (_s, o), a in zip(users, addrs, strict=True):
                by_opt.setdefault(o, []).append(a)
            if all(len(v) == len(set(v)) and None not in v for v in by_opt.values()):
                continue
        label = f"{pin[0]}:{pin[1]}" if pin[0] else pin[1]
        out.append(
            Finding(
                "error",
                "pin_conflict",
                f"pin {label} used by " + ", ".join(f"[{s}] {o}" for s, o in users),
            )
        )
    return out


# ------------------------------------------------------------------- diff


@dataclass(slots=True)
class Change:
    kind: str  # section_added | section_removed | option_added | option_removed | option_changed
    section: str
    option: str | None
    old: str | None
    new: str | None
    risk: RiskLevel
    why: str
    autosave: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "section": self.section,
            "risk": self.risk.name,
            "why": self.why,
        }
        if self.option is not None:
            d["option"] = self.option
        if self.old is not None:
            d["old"] = self.old
        if self.new is not None:
            d["new"] = self.new
        if self.autosave:
            d["in_save_config_block"] = True
        return d


def semantic_diff(old: KlipperConfig, new: KlipperConfig, *, ignore: Iterable[tuple[str, str]] = ()) -> list[Change]:
    ignored = set(ignore)
    a, b = old.effective, new.effective
    changes: list[Change] = []
    for name in sorted(set(a) | set(b)):
        if name not in b:
            risk, why = classify_section_change(name)
            changes.append(Change("section_removed", name, None, None, None, risk, why))
            continue
        if name not in a:
            risk, why = classify_section_change(name)
            changes.append(Change("section_added", name, None, None, None, risk, why))
            continue
        ao, bo = a[name].options, b[name].options
        for opt in sorted(set(ao) | set(bo)):
            if (name, opt) in ignored:
                continue
            ov = ao[opt].value if opt in ao else None
            nv = bo[opt].value if opt in bo else None
            if _norm(ov) == _norm(nv):
                continue
            risk, why = classify_option_change(name, opt)
            kind = "option_added" if ov is None else "option_removed" if nv is None else "option_changed"
            autosave = (opt in bo and bo[opt].autosave) or (opt in ao and ao[opt].autosave)
            changes.append(Change(kind, name, opt, ov, nv, risk, why, autosave))
    return changes


def _norm(v: str | None) -> str | None:
    if v is None:
        return None
    lines = [" ".join(line.split()) for line in v.strip().splitlines()]
    joined = "\n".join(line for line in lines if line)
    try:
        return repr(float(joined))
    except ValueError:
        return joined


def max_risk(changes: Iterable[Change]) -> RiskLevel:
    return max((c.risk for c in changes), default=RiskLevel.READ_ONLY)


# ------------------------------------------------------------------ edits


class EditError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Edit:
    """Set (value is not None) or remove (value is None) one option."""

    section: str
    option: str
    value: str | None


def apply_edits(text: str, edits: Iterable[Edit]) -> str:
    """Apply edits with minimal textual change.

    Edits to an option present in the SAVE_CONFIG block modify the `#*#` line,
    since that value overrides the section above. New options go after the
    last option of their section; new sections go just above SAVE_CONFIG.
    """
    for e in edits:
        text = _apply_one(text, e)
    return text


def _apply_one(text: str, e: Edit) -> str:
    if "\n" in (e.value or "") or (e.value is not None and e.value != e.value.strip()):
        raise EditError("multi-line or padded values are not supported by structured edits")
    option = e.option.strip().lower()
    section = " ".join(e.section.split())
    cfg = parse(text)
    lines = text.splitlines()
    trailing_nl = text.endswith("\n")
    auto = cfg.autosave.get(section)
    user = cfg.user.get(section)

    if auto is not None and option in auto.options:
        opt = auto.options[option]
        if e.value is None:
            del lines[opt.line - 1]
        else:
            lines[opt.line - 1] = f"#*# {option} = {e.value}"
        return _join(lines, trailing_nl)

    if user is not None and option in user.options:
        opt = user.options[option]
        if e.value is None:
            del lines[opt.line - 1 : opt.end_line]
        else:
            old = lines[opt.line - 1]
            key_part = re.split(r"[:=]", old, maxsplit=1)[0]
            uses_equals = old[len(key_part) : len(key_part) + 1] == "="
            comment = _trailing_comment(old)
            del lines[opt.line - 1 : opt.end_line]
            new_line = f"{option} = {e.value}" if uses_equals else f"{option}: {e.value}"
            lines.insert(opt.line - 1, new_line + comment)
        return _join(lines, trailing_nl)

    if e.value is None:
        raise EditError(f"cannot remove [{section}] {option}: option not present")

    if user is not None:
        last = max([o.end_line for o in user.options.values()] or [user.line])
        lines.insert(last, f"{option}: {e.value}")
        return _join(lines, trailing_nl)

    if auto is not None:
        last = max([o.end_line for o in auto.options.values()] or [auto.line])
        lines.insert(last, f"#*# {option} = {e.value}")
        return _join(lines, trailing_nl)

    header_idx = _header_index(lines)
    block = [f"[{section}]", f"{option}: {e.value}", ""]
    if header_idx < len(lines):
        lines[header_idx:header_idx] = block
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block[:2])
    return _join(lines, trailing_nl)


def _trailing_comment(line: str) -> str:
    m = _INLINE_COMMENT_RE.search(line)
    return m.group(0) if m else ""


def _join(lines: list[str], trailing_nl: bool) -> str:
    return "\n".join(lines) + ("\n" if trailing_nl else "")


# ---------------------------------------------------------------- explain


def dependencies(cfg: KlipperConfig) -> list[dict[str, str]]:
    """Relationships between sections that matter when changing one of them."""
    eff = cfg.effective
    deps: list[dict[str, str]] = []
    probe = cfg.probe_section()
    z = eff.get("stepper_z")
    if z and "z_virtual_endstop" in (z.get("endstop_pin") or "") and probe:
        deps.append(
            {
                "from": "stepper_z",
                "to": probe.name,
                "why": "Z homes using the probe as a virtual endstop; probe health == Z homing health",
            }
        )
        if "safe_z_home" in eff:
            deps.append(
                {
                    "from": "safe_z_home",
                    "to": probe.name,
                    "why": "home_xy_position plus probe offset decides where Z homes",
                }
            )
    for s in ("bed_mesh", "screws_tilt_adjust"):
        if s in eff and probe:
            deps.append(
                {
                    "from": s,
                    "to": probe.name,
                    "why": "coordinates are probe positions; offsets matter",
                }
            )
    for sec in eff.values():
        if sec.type.startswith("tmc") and sec.suffix:
            deps.append({"from": sec.name, "to": sec.suffix, "why": "driver configuration for this stepper"})
        if sec.type == "verify_heater" and sec.suffix:
            deps.append(
                {
                    "from": sec.name,
                    "to": sec.suffix,
                    "why": "thermal runaway checks for this heater",
                }
            )
        if sec.type in ("filament_switch_sensor", "filament_motion_sensor"):
            deps.append({"from": sec.name, "to": "pause_resume", "why": "runout pauses the print"})
        if sec.type == "heater_fan" and sec.get("heater"):
            deps.append(
                {
                    "from": sec.name,
                    "to": sec.get("heater") or "",
                    "why": "fan follows heater temperature",
                }
            )
    vsd = eff.get("virtual_sdcard")
    if vsd and vsd.get("on_error_gcode"):
        deps.append(
            {
                "from": "virtual_sdcard",
                "to": f"gcode_macro {vsd.get('on_error_gcode')}",
                "why": "runs when a print errors",
            }
        )
    macros = cfg.macros()
    for name, sec in macros.items():
        body = (sec.get("gcode") or "").upper()
        for other in macros:
            if other != name and re.search(rf"\b{re.escape(other)}\b", body):
                deps.append({"from": sec.name, "to": f"gcode_macro {other}", "why": "macro calls macro"})
    return deps


def explain(cfg: KlipperConfig) -> dict[str, Any]:
    eff = cfg.effective
    sections = []
    for name, sec in eff.items():
        entry: dict[str, Any] = {"section": name, "line": sec.line}
        purpose = SECTION_PURPOSE.get(sec.type)
        if purpose:
            entry["purpose"] = purpose
        auto = [o for o, v in sec.options.items() if v.autosave]
        if auto:
            entry["save_config_overrides"] = auto
        sections.append(entry)
    probe = cfg.probe_section()
    summary: dict[str, Any] = {
        "kinematics": cfg.value("printer", "kinematics"),
        "travel": {a: _axis_limits(eff, a) for a in ("x", "y", "z")},
        "probe": probe.name if probe else None,
        "z_homing": "probe virtual endstop"
        if "z_virtual_endstop" in (cfg.value("stepper_z", "endstop_pin") or "")
        else "physical endstop",
        "includes": cfg.includes,
        "macros": sorted(cfg.macros()),
    }
    if probe:
        summary["probe_offsets"] = {k: probe.get(k) for k in ("x_offset", "y_offset", "z_offset")}
    return {"summary": summary, "sections": sections, "dependencies": dependencies(cfg)}


def bed_mesh_points(cfg: KlipperConfig, profile: str = "default") -> list[list[float]] | None:
    sec = cfg.autosave.get(f"bed_mesh {profile}")
    if sec is None:
        return None
    raw = sec.get("points")
    if not raw:
        return None
    rows: list[list[float]] = []
    for line in raw.splitlines():
        vals = _floats(line.strip().rstrip(","))
        if vals:
            rows.append(vals)
    return rows or None
