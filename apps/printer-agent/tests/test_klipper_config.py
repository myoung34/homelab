from __future__ import annotations

import pytest
from conftest import ENDERBIG_SERIAL
from sim import fixture

from printer_agent import klipper_config as kc
from printer_agent.safety import RiskLevel


@pytest.fixture
def enderbig() -> kc.KlipperConfig:
    return kc.parse(fixture("enderbig.cfg"))


def test_parses_real_config_with_save_config_overlay(enderbig: kc.KlipperConfig) -> None:
    # z_offset only exists in the SAVE_CONFIG block; the effective view must have it.
    assert "z_offset" not in enderbig.user["bltouch"].options
    probe = enderbig.probe_section()
    assert probe is not None and probe.get("z_offset") == "3.420"
    assert probe.options["z_offset"].autosave
    assert enderbig.value("extruder", "control") == "pid"
    assert enderbig.value("stepper_z", "endstop_pin") == "probe:z_virtual_endstop"
    assert enderbig.value("bltouch", "pin_up_touch_mode_reports_triggered") == "False"  # '=' separator
    assert "\n" in (enderbig.value("gcode_macro CANCEL_PRINT", "gcode") or "")
    assert not enderbig.parse_warnings


def test_bed_mesh_points_from_autosave(enderbig: kc.KlipperConfig) -> None:
    pts = kc.bed_mesh_points(enderbig)
    assert pts is not None and len(pts) == 4 and len(pts[0]) == 4
    assert pts[0][0] == pytest.approx(0.710742)


def test_validation_flags_disabled_thermal_protection(enderbig: kc.KlipperConfig) -> None:
    findings = kc.validate(enderbig, expected_mcu_serial=ENDERBIG_SERIAL)
    codes = {f.code: f for f in findings}
    assert codes["verify_heater_disabled"].severity == "danger"
    assert codes["verify_heater_hysteresis"].severity == "danger"
    assert not [f for f in findings if f.severity == "error"], [f.to_dict() for f in findings if f.severity == "error"]
    # Shared TMC UART pins with distinct addresses are legitimate.
    assert "pin_conflict" not in codes


def test_mcu_serial_mismatch_detects_copied_config() -> None:
    cfg = kc.parse(fixture("enderleft.cfg"))
    codes = {f.code for f in kc.validate(cfg, expected_mcu_serial=ENDERBIG_SERIAL)}
    assert "mcu_serial_mismatch" in codes


def test_probe_geometry_checks() -> None:
    text = fixture("enderbig.cfg").replace("home_xy_position: 120,120", "home_xy_position: 400,120")
    text = text.replace("mesh_max: 335,315", "mesh_max: 395,315")
    codes = {f.code for f in kc.validate(kc.parse(text))}
    assert {"safe_z_home_unreachable", "mesh_unreachable"} <= codes


def test_structural_errors() -> None:
    text = fixture("enderbig.cfg").replace("sensor_pin: ^PC14", "sensor_pin: PC14")
    text = text.replace("endstop_pin: ^PC0", "endstop_pin: ^PC1")  # X and Y now share PC1
    findings = kc.validate(kc.parse(text))
    codes = {f.code for f in findings}
    assert "bltouch_no_pullup" in codes
    assert "pin_conflict" in codes


def test_virtual_endstop_without_probe() -> None:
    text = fixture("enderbig.cfg").replace("[bltouch]", "[bltouch_removed]")
    codes = {f.code for f in kc.validate(kc.parse(text))}
    assert "virtual_endstop_without_probe" in codes


def test_malformed_config_is_reported_not_crashing() -> None:
    cfg = kc.parse("[printer]\nkinematics cartesian\n[stepper_x\nstep_pin: PB13\n")
    assert cfg.parse_warnings
    codes = {f.code for f in kc.validate(cfg)}
    assert "missing_section" in codes  # no [mcu]


@pytest.mark.parametrize(
    ("section", "option", "risk"),
    [
        ("bltouch", "sensor_pin", RiskLevel.DANGEROUS),
        ("verify_heater extruder", "max_error", RiskLevel.DANGEROUS),
        ("extruder", "max_temp", RiskLevel.DANGEROUS),
        ("stepper_z", "rotation_distance", RiskLevel.DANGEROUS),
        ("stepper_x", "position_endstop", RiskLevel.DANGEROUS),
        ("printer", "max_accel", RiskLevel.DANGEROUS),
        ("mcu", "serial", RiskLevel.DANGEROUS),
        ("bltouch", "z_offset", RiskLevel.HIGH_RISK_WRITE),
        ("extruder", "pid_kp", RiskLevel.HIGH_RISK_WRITE),
        ("extruder", "pressure_advance", RiskLevel.HIGH_RISK_WRITE),
        ("bed_mesh", "probe_count", RiskLevel.HIGH_RISK_WRITE),
        ("gcode_macro PRINT_START", "gcode", RiskLevel.HIGH_RISK_WRITE),
        ("bed_screws", "screw1_name", RiskLevel.LOW_RISK_WRITE),
        ("display", "lcd_type", RiskLevel.LOW_RISK_WRITE),
    ],
)
def test_risk_classification(section: str, option: str, risk: RiskLevel) -> None:
    assert kc.classify_option_change(section, option)[0] == risk


def test_semantic_diff_between_printers() -> None:
    a, b = kc.parse(fixture("enderleft.cfg")), kc.parse(fixture("enderright.cfg"))
    changes = kc.semantic_diff(a, b)
    keys = {(c.section, c.option) for c in changes}
    assert ("mcu", "serial") in keys
    assert ("bltouch", "z_offset") in keys
    z = next(c for c in changes if c.option == "z_offset")
    assert z.autosave and z.old == "4.455" and z.new == "3.510"
    # comments-only differences (header) are not changes
    assert all(c.option is not None for c in changes)


def test_semantic_diff_ignores_number_formatting() -> None:
    a = kc.parse("[bed_mesh]\nbicubic_tension: .2\n")
    b = kc.parse("[bed_mesh]\nbicubic_tension: 0.2\n")
    assert kc.semantic_diff(a, b) == []


def test_edit_changes_exactly_one_line() -> None:
    text = fixture("enderbig.cfg")
    new = kc.apply_edits(text, [kc.Edit("bltouch", "speed", "5.0")])
    diff = [ln for ln in zip(text.splitlines(), new.splitlines(), strict=True) if ln[0] != ln[1]]
    assert diff == [("speed: 10.0", "speed: 5.0")]


def test_edit_targets_save_config_block_when_value_lives_there() -> None:
    text = fixture("enderbig.cfg")
    new = kc.apply_edits(text, [kc.Edit("bltouch", "z_offset", "3.380")])
    assert "#*# z_offset = 3.380" in new
    assert kc.parse(new).value("bltouch", "z_offset") == "3.380"
    assert len(new.splitlines()) == len(text.splitlines())


def test_edit_add_remove_and_new_section() -> None:
    text = fixture("enderbig.cfg")
    new = kc.apply_edits(
        text,
        [
            kc.Edit("extruder", "pressure_advance", "0.05"),
            kc.Edit("verify_heater extruder", "max_error", None),
            kc.Edit("input_shaper", "shaper_freq_x", "48.2"),
        ],
    )
    cfg = kc.parse(new)
    assert cfg.value("extruder", "pressure_advance") == "0.05"
    assert cfg.value("verify_heater extruder", "max_error") is None
    assert cfg.value("input_shaper", "shaper_freq_x") == "48.2"
    # the new section goes above the SAVE_CONFIG header, never inside it
    assert new.index("[input_shaper]") < new.index(kc.AUTOSAVE_HEADER)
    assert "input_shaper" not in cfg.autosave


def test_edit_rejects_multiline_and_missing_removal() -> None:
    with pytest.raises(kc.EditError):
        kc.apply_edits("[printer]\nkinematics: cartesian\n", [kc.Edit("printer", "max_accel", None)])
    with pytest.raises(kc.EditError):
        kc.apply_edits("[printer]\n", [kc.Edit("printer", "x", "a\nb")])


def test_explain_reports_dependencies(enderbig: kc.KlipperConfig) -> None:
    ex = kc.explain(enderbig)
    assert ex["summary"]["z_homing"] == "probe virtual endstop"
    deps = {(d["from"], d["to"]) for d in ex["dependencies"]}
    assert ("stepper_z", "bltouch") in deps
    assert ("verify_heater extruder", "extruder") in deps
    assert ("filament_switch_sensor filament_sensor", "pause_resume") in deps
