"""Failure taxonomy and log signatures.

A *class* is a failure category (e.g. PROBE.probe_not_triggering) with a
*domain* that answers the operator's real question - is this configuration,
hardware, electrical, mechanical, firmware, slicer or operator? A *signature*
maps a Klipper/Moonraker message to the proximate class it proves, plus the
root-cause candidates that could produce it and how to tell them apart.

Both are extensible: PRINTER_AGENT_TAXONOMY_EXTRA points at a YAML file with
`classes:` and `signatures:` in the same shape as the built-ins below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DOMAINS = (
    "configuration",
    "hardware",
    "electrical",
    "mechanical",
    "firmware",
    "slicer",
    "operator",
    "network",
    "power",
    "unknown",
)


@dataclass(frozen=True, slots=True)
class FailureClass:
    id: str
    domain: str
    description: str


@dataclass(frozen=True, slots=True)
class RootCause:
    failure_class: str
    summary: str
    prior: float  # 0..1 before class-specific analysers adjust it
    test: str
    test_risk: str = "READ_ONLY"


@dataclass(frozen=True, slots=True)
class Signature:
    id: str
    pattern: re.Pattern[str]
    failure_class: str
    statement: str
    root_causes: tuple[RootCause, ...] = field(default_factory=tuple)
    # A shutdown/abort is fatal to a print; warnings are not.
    fatal: bool = True


def _c(id_: str, domain: str, description: str) -> FailureClass:
    return FailureClass(id_, domain, description)


BUILTIN_CLASSES: tuple[FailureClass, ...] = (
    _c(
        "PROBE.probe_not_triggering",
        "hardware",
        "Probe never reported a trigger during a probing move",
    ),
    _c(
        "PROBE.probe_triggering_too_early",
        "configuration",
        "Probe reported triggered before or at the start of a move",
    ),
    _c("PROBE.probe_inconsistent", "mechanical", "Probe samples disagree beyond tolerance"),
    _c("PROBE.probe_offset", "configuration", "Probe offsets wrong (z_offset/x/y)"),
    _c("PROBE.probe_wiring", "electrical", "Probe signal/control wiring or pull-up fault"),
    _c(
        "PROBE.probe_configuration",
        "configuration",
        "Probe pin/mode settings do not match the probe hardware",
    ),
    _c(
        "THERMAL.heater_failure",
        "hardware",
        "Heater cartridge/pad or its wiring not delivering power",
    ),
    _c("THERMAL.thermistor_failure", "hardware", "Thermistor open/short/intermittent"),
    _c(
        "THERMAL.thermal_runaway",
        "hardware",
        "Temperature diverged from target while heating was commanded",
    ),
    _c(
        "THERMAL.temperature_instability",
        "configuration",
        "Oscillation/overshoot; usually PID or airflow",
    ),
    _c(
        "THERMAL.heating_timeout",
        "hardware",
        "Heater could not reach target within the check window",
    ),
    _c("THERMAL.thermal_config", "configuration", "Thermal protection or sensor settings wrong"),
    _c("MOTION.skipped_steps", "mechanical", "Lost steps (layer shift)"),
    _c("MOTION.endstop_failure", "hardware", "Endstop did not trigger / stuck triggered"),
    _c(
        "MOTION.endstop_configuration",
        "configuration",
        "Endstop pin inversion/pull-up/position wrong",
    ),
    _c("MOTION.homing_failure", "unknown", "Homing failed (see more specific evidence)"),
    _c("MOTION.belt_slip", "mechanical", "Belt slipping/loose"),
    _c("MOTION.binding", "mechanical", "Axis binding or obstruction"),
    _c("MOTION.motor_failure", "hardware", "Stepper motor or cable fault"),
    _c("MOTION.driver_fault", "electrical", "TMC driver reported short/overtemp/undervoltage"),
    _c(
        "MOTION.driver_configuration",
        "configuration",
        "Driver chopper/current configuration problem",
    ),
    _c("MOTION.out_of_range", "slicer", "Commanded move outside configured travel"),
    _c("EXTRUSION.clog", "hardware", "Nozzle/hotend clog"),
    _c("EXTRUSION.heat_creep", "hardware", "Filament softening above the heat break"),
    _c(
        "EXTRUSION.under_extrusion",
        "configuration",
        "Insufficient extrusion (calibration/flow/temp)",
    ),
    _c("EXTRUSION.extruder_skip", "mechanical", "Extruder skipping/grinding"),
    _c("EXTRUSION.filament_sensor", "operator", "Runout detected (or sensor false positive)"),
    _c("EXTRUSION.cold_extrusion", "slicer", "Extrusion attempted below min_extrude_temp"),
    _c("BED.leveling", "mechanical", "Bed tram/level off"),
    _c("BED.mesh", "configuration", "Mesh stale, missing, not loaded or wrong area"),
    _c("BED.adhesion", "operator", "First layer did not stick"),
    _c("BED.warped_bed", "mechanical", "Bed surface not flat"),
    _c("FIRMWARE.klipper_crash", "firmware", "Klippy host process error/crash"),
    _c("FIRMWARE.mcu_disconnect", "electrical", "Host lost communication with the MCU"),
    _c("FIRMWARE.mcu_timing", "firmware", "MCU timing shutdown (Timer too close, scheduling)"),
    _c("FIRMWARE.configuration_error", "configuration", "Klipper refused the configuration"),
    _c("FIRMWARE.mcu_protocol", "firmware", "Host/MCU firmware version mismatch"),
    _c("SLICER.start_gcode", "slicer", "Start G-code problem"),
    _c("SLICER.end_gcode", "slicer", "End G-code problem"),
    _c("SLICER.incorrect_profile", "slicer", "Wrong printer/filament profile"),
    _c("SLICER.temperature", "slicer", "Slicer temperatures inappropriate"),
    _c("SLICER.acceleration", "slicer", "Slicer motion settings inappropriate"),
    _c("SLICER.retraction", "slicer", "Retraction settings inappropriate"),
    _c("SLICER.unknown_command", "slicer", "G-code uses commands Klipper does not know"),
    _c("NETWORK.moonraker", "network", "Moonraker unavailable or restarted"),
    _c("NETWORK.websocket", "network", "Client websocket/API connection lost"),
    _c("NETWORK.connectivity", "network", "Network path to printer host failed"),
    _c("NETWORK.host_failure", "network", "Printer host (pod/node) failed"),
    _c("POWER.host_shutdown", "power", "Host lost power or rebooted"),
    _c("POWER.printer_shutdown", "power", "Printer PSU/mainboard lost power"),
    _c("POWER.brownout", "power", "Supply voltage sag (undervoltage, MCU reset)"),
    _c("OPERATOR.cancelled", "operator", "Print cancelled by a person"),
    _c("OPERATOR.emergency_stop", "operator", "Emergency stop requested"),
    _c("OPERATOR.command_error", "operator", "Manual command rejected (e.g. move before homing)"),
    _c("UNKNOWN", "unknown", "Not classifiable from available evidence"),
)


def _rc(cls: str, summary: str, prior: float, test: str, risk: str = "READ_ONLY") -> RootCause:
    return RootCause(cls, summary, prior, test, risk)


def _sig(id_: str, pattern: str, cls: str, statement: str, *rcs: RootCause, fatal: bool = True) -> Signature:
    return Signature(id_, re.compile(pattern, re.IGNORECASE), cls, statement, tuple(rcs), fatal)


BUILTIN_SIGNATURES: tuple[Signature, ...] = (
    _sig(
        "heater_not_heating",
        r"Heater (?P<heater>\S+) not heating at expected rate",
        "THERMAL.thermal_runaway",
        "verify_heater shut down {heater}: temperature did not track the heater output",
        _rc(
            "THERMAL.heater_failure",
            "heater cartridge/pad or connector not delivering power",
            0.4,
            "Inspect the temperature trace before the shutdown: PWM pinned near 1.0 with falling or flat "
            "temperature points to the heater circuit. Check heater resistance with the printer off.",
            "READ_ONLY",
        ),
        _rc(
            "THERMAL.thermistor_failure",
            "thermistor reading intermittently (loose crimp, damaged wire)",
            0.35,
            "Look for single-sample temperature jumps in the trace; flex the hotend cable while watching "
            "the live temperature with heaters off.",
            "READ_ONLY",
        ),
        _rc(
            "THERMAL.temperature_instability",
            "airflow (part fan / draft) overwhelming the heater, or PID badly tuned",
            0.25,
            "Check whether the part fan ramped up just before the fault; re-run PID_CALIBRATE (heats hardware).",
            "HIGH_RISK_WRITE",
        ),
        _rc(
            "THERMAL.thermal_config",
            "verify_heater thresholds too strict for this hotend",
            0.1,
            "Compare verify_heater settings to defaults; only consider loosening after hardware is ruled out.",
            "READ_ONLY",
        ),
    ),
    _sig(
        "adc_out_of_range",
        r"ADC out of range",
        "THERMAL.thermistor_failure",
        "MCU shut down: a thermistor reading was outside min_temp/max_temp",
        _rc(
            "THERMAL.thermistor_failure",
            "thermistor open circuit (reads very cold) or short (reads very hot)",
            0.6,
            "Read the last temperatures before shutdown; check live temperature with heaters off.",
            "READ_ONLY",
        ),
        _rc(
            "THERMAL.thermal_runaway",
            "a real over-temperature exceeded max_temp",
            0.25,
            "Check whether the temperature climbed steadily past target before the shutdown.",
        ),
        _rc(
            "THERMAL.thermal_config",
            "min_temp/max_temp or sensor_type wrong for the sensor",
            0.15,
            "Compare sensor_type and limits with the installed thermistor.",
        ),
    ),
    _sig(
        "lost_comm",
        r"Lost communication with MCU '?(?P<mcu>[\w-]+)'?",
        "FIRMWARE.mcu_disconnect",
        "Klipper lost communication with MCU {mcu}",
        _rc(
            "FIRMWARE.mcu_disconnect",
            "USB cable/connector or EMI interrupting the link",
            0.4,
            "Check bytes_retransmit/bytes_invalid trend in the Stats lines before the event and kernel/USB "
            "resets on the node.",
            "READ_ONLY",
        ),
        _rc(
            "POWER.brownout",
            "MCU reset by supply sag (printer PSU, shared USB 5V)",
            0.3,
            "Look for the MCU re-enumerating / 'Got EOF' and for heater load at the time of the event.",
        ),
        _rc(
            "NETWORK.host_failure",
            "host overloaded or the klipper pod/node restarted",
            0.3,
            "Check sysload/memavail in Stats and the pod restart history.",
        ),
    ),
    _sig(
        "timeout_mcu",
        r"Timeout with MCU '?(?P<mcu>[\w-]+)'?",
        "FIRMWARE.mcu_disconnect",
        "Klipper timed out talking to MCU {mcu}",
        _rc(
            "FIRMWARE.mcu_disconnect",
            "USB link interrupted",
            0.5,
            "Check Stats retransmits and USB events.",
        ),
        _rc(
            "NETWORK.host_failure",
            "host stalled",
            0.3,
            "Check sysload/memavail and pod/node events.",
        ),
        _rc("POWER.brownout", "MCU lost power", 0.2, "Check for MCU reset on reconnect."),
    ),
    _sig(
        "eof_serial",
        r"Got EOF when reading from device|Unable to open serial port|"
        r"device reports readiness to read but returned no data",
        "FIRMWARE.mcu_disconnect",
        "The MCU serial device disappeared from the host",
        _rc(
            "FIRMWARE.mcu_disconnect",
            "USB cable unplugged/intermittent",
            0.45,
            "Check whether the printer pod is Pending (NFD label for the MCU serial gone) or the device re-appeared.",
            "READ_ONLY",
        ),
        _rc(
            "POWER.printer_shutdown",
            "printer mainboard powered off (USB-powered MCU stays up only if the board is bus-powered)",
            0.35,
            "Ask whether the printer PSU was switched off; check uptime.",
        ),
        _rc("POWER.brownout", "MCU reset by supply sag", 0.2, "Correlate with heater turn-on."),
    ),
    _sig(
        "timer_too_close",
        r"Timer too close|Rescheduled timer in the past|Missed scheduling of next|"
        r"Stepper too far in past|Move queue overflow",
        "FIRMWARE.mcu_timing",
        "MCU timing shutdown",
        _rc(
            "NETWORK.host_failure",
            "host CPU starved (other pods on the node, throttling)",
            0.5,
            "Check sysload and cputime in Stats before the shutdown, node load, and CPU throttling.",
        ),
        _rc(
            "FIRMWARE.mcu_timing",
            "step rate too high for the MCU (microsteps x speed)",
            0.3,
            "Compare max_velocity x microsteps / rotation_distance with MCU step-rate benchmarks.",
        ),
        _rc(
            "FIRMWARE.mcu_disconnect",
            "USB retransmits delaying commands",
            0.2,
            "Check bytes_retransmit trend.",
        ),
    ),
    _sig(
        "mcu_protocol",
        r"MCU Protocol error|is not valid for this MCU|"
        r"Please update the micro-controller firmware",
        "FIRMWARE.mcu_protocol",
        "Host and MCU Klipper versions are incompatible",
        _rc(
            "FIRMWARE.mcu_protocol",
            "mkuf/klipper:latest host updated past the flashed MCU firmware",
            0.9,
            "Compare the host version in klippy.log with the MCU version; reflash the MCU (manual).",
            "DANGEROUS",
        ),
    ),
    _sig(
        "probe_prior",
        r"Probe triggered prior to movement",
        "PROBE.probe_triggering_too_early",
        "Probe reported triggered before the probing move started",
        _rc(
            "PROBE.probe_configuration",
            "probe mode mismatch for clone/3DTouch probes "
            "(pin_up_reports_not_triggered / pin_up_touch_mode_reports_triggered / probe_with_touch_mode)",
            0.45,
            "Run QUERY_PROBE with the pin stowed: TRIGGERED at rest means the reported pin state is "
            "inverted relative to the config.",
            "SAFE_AUTOMATION",
        ),
        _rc(
            "PROBE.probe_wiring",
            "sensor wire floating or crossed (missing ^ pull-up)",
            0.3,
            "Repeat QUERY_PROBE a few times; flapping results indicate a floating signal.",
            "SAFE_AUTOMATION",
        ),
        _rc(
            "PROBE.probe_offset",
            "nozzle already at/below bed at probe start (z_offset or position_min)",
            0.25,
            "Check horizontal_move_z / z_hop and recent z_offset changes.",
        ),
    ),
    # "No trigger on z" is ambiguous (physical endstop vs probe virtual
    # endstop); diagnostics remaps endstop_no_trigger on z using the config.
    _sig(
        "probe_no_trigger",
        r"No trigger on probe after full movement",
        "PROBE.probe_not_triggering",
        "Probe never triggered during a full-length probing move",
        _rc(
            "PROBE.probe_wiring",
            "signal wire/connector or wrong sensor_pin",
            0.35,
            "QUERY_PROBE while manually pushing the pin up (BLTOUCH_DEBUG COMMAND=pin_down first) - "
            "a reading that never changes isolates wiring/pin.",
            "SAFE_AUTOMATION",
        ),
        _rc(
            "PROBE.probe_not_triggering",
            "pin not deploying (stuck pin, bad solenoid, control_pin)",
            0.3,
            "Watch the probe during BLTOUCH_DEBUG COMMAND=pin_down / pin_up (actuates the probe only).",
            "LOW_RISK_WRITE",
        ),
        _rc(
            "PROBE.probe_configuration",
            "probe_with_touch_mode/pin_up_* settings wrong for this probe version",
            0.2,
            "Compare probe settings with the printer where the same probe works.",
        ),
        _rc(
            "PROBE.probe_offset",
            "Z started too high / position_min too high to reach the bed",
            0.15,
            "Check stepper_z position_min and the starting Z.",
        ),
    ),
    _sig(
        "bltouch_verify",
        r"BLTouch failed to verify sensor state|BLTouch failed to raise probe|"
        r"BLTouch failed to deploy",
        "PROBE.probe_wiring",
        "BLTouch did not report the expected state",
        _rc(
            "PROBE.probe_wiring",
            "signal/control wiring or pull-up",
            0.4,
            "QUERY_PROBE repeatedly at rest; check sensor_pin pull-up '^'.",
            "SAFE_AUTOMATION",
        ),
        _rc(
            "PROBE.probe_configuration",
            "clone probe needs pin_up_reports_not_triggered: False or pin_up_touch_mode_reports_triggered: False",
            0.35,
            "Compare with the working printer's probe settings and the probe version.",
        ),
        _rc(
            "PROBE.probe_not_triggering",
            "worn/stuck pin",
            0.25,
            "BLTOUCH_DEBUG COMMAND=reset then pin_down/pin_up while watching.",
            "LOW_RISK_WRITE",
        ),
    ),
    _sig(
        "probe_tolerance",
        r"Probe samples exceed (?:samples_)?tolerance",
        "PROBE.probe_inconsistent",
        "Probe samples disagreed beyond samples_tolerance",
        _rc(
            "PROBE.probe_inconsistent",
            "loose probe mount or toolhead play",
            0.35,
            "PROBE_ACCURACY (moves Z) and check range; inspect the mount.",
            "HIGH_RISK_WRITE",
        ),
        _rc(
            "BED.warped_bed",
            "Z axis wobble/binding or bed moving",
            0.3,
            "Check Z rods/eccentric nuts; repeat PROBE_ACCURACY at two locations.",
            "HIGH_RISK_WRITE",
        ),
        _rc(
            "PROBE.probe_configuration",
            "samples_tolerance too tight / speed too high",
            0.2,
            "Compare samples_tolerance and speed with defaults (0.1 mm, 5 mm/s).",
        ),
    ),
    _sig(
        "endstop_no_trigger",
        r"No trigger on (?P<axis>[xyz]) after full movement",
        "MOTION.homing_failure",
        "{axis} endstop never triggered while homing",
        _rc(
            "MOTION.endstop_failure",
            "switch/cable fault",
            0.35,
            "QUERY_ENDSTOPS while pressing the switch by hand.",
            "SAFE_AUTOMATION",
        ),
        _rc(
            "MOTION.endstop_configuration",
            "wrong pin, missing ^ pull-up or inverted (!)",
            0.3,
            "QUERY_ENDSTOPS at rest; compare endstop_pin with a working printer.",
        ),
        _rc(
            "MOTION.binding",
            "carriage stopped short (binding/obstruction) or motor not moving",
            0.2,
            "Check whether the axis moves freely with motors off.",
        ),
        _rc(
            "MOTION.endstop_configuration",
            "homing direction inverted (dir_pin) - axis moves away",
            0.15,
            "Recent dir_pin / homing_positive_dir changes in config history.",
        ),
    ),
    _sig(
        "endstop_still_triggered",
        r"Endstop (?P<axis>[xyz]) still triggered after retract",
        "MOTION.endstop_configuration",
        "{axis} endstop still reported triggered after backing off",
        _rc(
            "MOTION.endstop_configuration",
            "endstop logic inverted (missing/extra '!')",
            0.5,
            "QUERY_ENDSTOPS with the carriage away from the switch: TRIGGERED there means inverted.",
            "SAFE_AUTOMATION",
        ),
        _rc(
            "MOTION.endstop_failure",
            "switch stuck closed or shorted cable",
            0.35,
            "Inspect the switch; QUERY_ENDSTOPS while unplugging it.",
        ),
        _rc(
            "MOTION.homing_failure",
            "homing_retract_dist too small",
            0.15,
            "Check homing_retract_dist.",
        ),
    ),
    _sig(
        "tmc_error",
        r"TMC '(?P<stepper>[^']+)' reports error: (?P<flags>.*)",
        "MOTION.driver_fault",
        "TMC driver for {stepper} reported: {flags}",
        _rc(
            "MOTION.driver_fault",
            "short in motor wiring/connector (s2ga/s2gb/s2vsa/s2vsb)",
            0.35,
            "Inspect the motor cable; measure coil resistance with power off.",
        ),
        _rc(
            "MOTION.driver_configuration",
            "chopper mode/current settings provoking false short detection (e.g. StealthChop at standstill)",
            0.3,
            "Compare the TMC section with Klipper defaults; see commit history for this stepper.",
        ),
        _rc(
            "POWER.brownout",
            "undervoltage (uv_cp) from PSU sag",
            0.2,
            "Check whether uv_cp is among the flags.",
        ),
        _rc(
            "MOTION.driver_fault",
            "driver over-temperature (ot/otpw)",
            0.15,
            "Check ot/otpw flags and current.",
        ),
    ),
    _sig(
        "move_out_of_range",
        r"Move out of range: (?P<pos>.*)",
        "MOTION.out_of_range",
        "A move went outside the configured travel: {pos}",
        _rc(
            "SLICER.incorrect_profile",
            "slicer bed size/origin does not match position_min/max",
            0.5,
            "Inspect the G-code bounds against the config travel limits (printer_gcode_inspect).",
        ),
        _rc(
            "SLICER.start_gcode",
            "start/end G-code moves outside travel",
            0.3,
            "Inspect start/end G-code.",
        ),
        _rc(
            "BED.mesh",
            "mesh/offset pushing Z below position_min",
            0.2,
            "Check z_offset and mesh range.",
        ),
    ),
    _sig(
        "must_home",
        r"Must home axis first",
        "OPERATOR.command_error",
        "A move was rejected because axes were not homed",
        _rc(
            "OPERATOR.command_error",
            "manual move before homing",
            0.5,
            "Check the command source in gcode_store.",
        ),
        _rc(
            "SLICER.start_gcode",
            "start G-code moves before G28",
            0.3,
            "Inspect start G-code order.",
        ),
        _rc(
            "MOTION.homing_failure",
            "steppers disabled mid-print (idle_timeout/M84) losing homed state",
            0.2,
            "Check idle_timeout and M84 in the file.",
        ),
        fatal=False,
    ),
    _sig(
        "cold_extrude",
        r"Extrude below minimum temp",
        "EXTRUSION.cold_extrusion",
        "Extrusion refused below min_extrude_temp",
        _rc(
            "SLICER.start_gcode",
            "extrusion before the wait-for-temperature command",
            0.5,
            "Inspect start G-code ordering of M109 vs first extrusion.",
        ),
        _rc(
            "THERMAL.heater_failure",
            "hotend failed to reach temperature",
            0.3,
            "Check the temperature trace.",
        ),
        _rc("OPERATOR.command_error", "manual extrude while cold", 0.2, "Check gcode_store."),
    ),
    _sig(
        "extrude_too_long",
        r"Extrude only move too long|Move exceeds maximum extrusion",
        "SLICER.incorrect_profile",
        "Extrusion exceeded configured limits",
        _rc(
            "SLICER.incorrect_profile",
            "filament diameter/extrusion mode mismatch (M82 vs M83)",
            0.5,
            "Check the G-code extrusion mode and filament_diameter.",
        ),
        _rc(
            "EXTRUSION.under_extrusion",
            "max_extrude_cross_section too small for wide first layer",
            0.3,
            "Compare first-layer width with max_extrude_cross_section.",
        ),
    ),
    _sig(
        "config_error",
        r"Option '(?P<option>[^']+)' (?:in section '(?P<section>[^']+)' must be specified|"
        r"is not valid in section '(?P<section2>[^']+)')|Section '(?P<section3>[^']+)' is not a valid config "
        r"section|Unknown pin chip name|pin \S+ used multiple times in config|Unable to parse option|"
        r"Error loading template|Config error|must have minimum of|must have maximum of",
        "FIRMWARE.configuration_error",
        "Klipper rejected the configuration",
        _rc(
            "FIRMWARE.configuration_error",
            "an edit to printer.cfg introduced an invalid value",
            0.8,
            "printer_config_drift and printer_config_history: what changed in the file since it last loaded.",
        ),
        _rc(
            "FIRMWARE.klipper_crash",
            "Klipper image updated and an option was deprecated/removed",
            0.2,
            "Compare the Klipper version in klippy.log across restarts.",
        ),
    ),
    _sig(
        "estop",
        r"Shutdown due to webhooks request|Shutdown due to M112|emergency stop",
        "OPERATOR.emergency_stop",
        "Emergency stop was requested",
        _rc(
            "OPERATOR.emergency_stop",
            "a person pressed e-stop / sent M112",
            0.8,
            "Check gcode_store for M112.",
        ),
        _rc(
            "SLICER.start_gcode",
            "M112 in a file or macro",
            0.2,
            "Search the G-code and macros for M112.",
        ),
    ),
    _sig(
        "runout",
        r"Filament runout|runout detected",
        "EXTRUSION.filament_sensor",
        "Filament runout sensor fired",
        _rc("EXTRUSION.filament_sensor", "filament actually ran out", 0.6, "Ask / check the spool."),
        _rc(
            "EXTRUSION.filament_sensor",
            "sensor false trigger (switch/wiring)",
            0.4,
            "Check filament_switch_sensor state in printer_status with filament loaded.",
        ),
        fatal=False,
    ),
    _sig(
        "klippy_exception",
        r"Unhandled exception during run|Internal error|Traceback \(most recent call last\)",
        "FIRMWARE.klipper_crash",
        "Klippy raised an internal exception",
        _rc(
            "FIRMWARE.klipper_crash",
            "Klipper bug or macro raising an exception",
            0.6,
            "Read the traceback in klippy.log.",
        ),
        _rc("FIRMWARE.configuration_error", "macro/template error", 0.4, "Check recent macro edits."),
    ),
)


class Taxonomy:
    def __init__(self, classes: list[FailureClass], signatures: list[Signature]) -> None:
        self.classes = {c.id: c for c in classes}
        self.signatures = signatures

    def domain(self, class_id: str) -> str:
        cls = self.classes.get(class_id)
        return cls.domain if cls else "unknown"

    def match(self, line: str) -> tuple[Signature, dict[str, str]] | None:
        for sig in self.signatures:
            m = sig.pattern.search(line)
            if m:
                groups = {k: v for k, v in m.groupdict().items() if v is not None}
                return sig, groups
        return None

    def to_dict(self) -> dict[str, Any]:
        cats: dict[str, list[dict[str, str]]] = {}
        for c in self.classes.values():
            cat = c.id.split(".")[0]
            cats.setdefault(cat, []).append({"id": c.id, "domain": c.domain, "description": c.description})
        return {
            "domains": list(DOMAINS),
            "categories": cats,
            "signatures": [
                {"id": s.id, "class": s.failure_class, "pattern": s.pattern.pattern} for s in self.signatures
            ],
        }


def load_taxonomy(extra: Path | None = None) -> Taxonomy:
    classes = list(BUILTIN_CLASSES)
    sigs = list(BUILTIN_SIGNATURES)
    if extra is not None and extra.exists():
        data = yaml.safe_load(extra.read_text(encoding="utf-8")) or {}
        for c in data.get("classes", []):
            if c["domain"] not in DOMAINS:
                raise ValueError(f"taxonomy class {c['id']} has unknown domain {c['domain']}")
            classes.append(FailureClass(c["id"], c["domain"], c.get("description", "")))
        known = {c.id for c in classes}
        for s in data.get("signatures", []):
            if s["class"] not in known:
                raise ValueError(f"signature {s['id']} references unknown class {s['class']}")
            rcs = tuple(
                RootCause(
                    r["class"],
                    r["summary"],
                    float(r.get("prior", 0.3)),
                    r.get("test", ""),
                    r.get("test_risk", "READ_ONLY"),
                )
                for r in s.get("root_causes", [])
            )
            # Extra signatures take precedence over built-ins.
            sigs.insert(
                0,
                Signature(
                    s["id"],
                    re.compile(s["pattern"], re.IGNORECASE),
                    s["class"],
                    s.get("statement", s["id"]),
                    rcs,
                    bool(s.get("fatal", True)),
                ),
            )
    return Taxonomy(classes, sigs)
