"""Calibration state and "what should I calibrate next?".

State is derived only from evidence: the effective config (including the
SAVE_CONFIG block), recorded config history (when a value last changed and
how many prints ran since), calibration output found in klippy.log, the
last G-code's slicer settings, other printers' configs (values copied from a
sibling printer are not a calibration), and recent failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from printer_agent import gcode as gcode_mod
from printer_agent import klipper_config, service
from printer_agent.evidence import iso
from printer_agent.inventory import Printer
from printer_agent.moonraker import MoonrakerError
from printer_agent.service import Context, Gaps

STALE_DAYS = {"bed_mesh": 30, "z_offset": 60, "pid_extruder": 180, "pid_bed": 365}


@dataclass(slots=True)
class Item:
    name: str
    state: str  # known | inherited | default | not_configured | unknown | stale
    value: Any = None
    last_changed: str | None = None
    prints_since_change: int | None = None
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in {
                "item": self.name,
                "state": self.state,
                "value": self.value,
                "last_changed": self.last_changed,
                "prints_since_change": self.prints_since_change,
                "evidence": self.evidence,
            }.items()
            if v not in (None, [])
        }


def _history_of(ctx: Context, printer_id: str, getter: Any) -> tuple[float | None, int]:
    """(time the value last changed, number of loaded-config snapshots examined)."""
    events = list(reversed(ctx.store.config_events(printer_id, "loaded", limit=200)))
    sentinel = object()
    last: Any = sentinel
    changed_at: float | None = None
    for ev in events:
        blob = ctx.store.config_blob(ev["sha"])
        if blob is None:
            continue
        val = getter(klipper_config.parse(blob["content"]))
        if last is not sentinel and val != last:
            changed_at = ev["ts"]
        last = val
    return changed_at, len(events)


def _prints_since(ctx: Context, printer_id: str, ts: float | None) -> int | None:
    if ts is None:
        return None
    return sum(
        1
        for j in ctx.store.jobs(printer_id, limit=500)
        if j.get("start_time") and float(j["start_time"]) > ts and j["status"] == "completed"
    )


async def status(ctx: Context, printer: Printer) -> dict[str, Any]:
    gaps = Gaps()
    srcs = await service.config_sources(ctx, printer, gaps)
    text = srcs.get("file") or srcs.get("loaded")
    if text is None:
        return {
            "printer": printer.id,
            "error": "printer config unavailable",
            "data_gaps": gaps.to_list(),
        }
    cfg = klipper_config.parse(text)
    now = ctx.clock.now()
    items: list[Item] = []
    st = await service.status(ctx, printer)
    log = await service.klippy(ctx, printer, gaps, live_offset=st.get("live_offset"))
    notes = [n for s in (log.sessions if log else []) for n in s.notes]
    siblings = await _sibling_configs(ctx, printer, gaps)

    def changed(getter: Any) -> tuple[str | None, int | None, float | None]:
        ts, n = _history_of(ctx, printer.id, getter)
        if n < 2:
            return None, None, None
        return (iso(ts) if ts else None), _prints_since(ctx, printer.id, ts), ts

    # PID
    for heater, key in (("extruder", "pid_extruder"), ("heater_bed", "pid_bed")):
        vals = {k: cfg.value(heater, k) for k in ("control", "pid_kp", "pid_ki", "pid_kd")}
        it = Item(key, "unknown", vals)
        if vals["control"] != "pid" or not vals["pid_kp"]:
            it.state = "not_configured" if vals["control"] is None else "known"
            it.evidence.append(f"control={vals['control']}")
        else:
            it.state = "known"
            sec = cfg.autosave.get(heater)
            it.evidence.append(
                "PID values in SAVE_CONFIG block (written by PID_CALIBRATE)"
                if sec and "pid_kp" in sec.options
                else "PID values set by hand in the section"
            )
            for sib_id, sib in siblings.items():
                if all(sib.value(heater, k) == vals[k] for k in ("pid_kp", "pid_ki", "pid_kd")):
                    it.state = "inherited"
                    it.evidence.append(
                        f"identical to {sib_id}'s PID values: copied from another printer, not calibrated on this one"
                    )
        pid_notes = [t for _, _, t in notes if "PID parameters" in t]
        if pid_notes:
            it.evidence.append(f"last PID_CALIBRATE output in log: {pid_notes[-1][:120]}")
        it.last_changed, it.prints_since_change, ts = changed(
            lambda c, h=heater: tuple(c.value(h, k) for k in ("pid_kp", "pid_ki", "pid_kd"))
        )
        if ts and (now - ts) / 86400 > STALE_DAYS[key] and it.state == "known":
            it.state = "stale"
        items.append(it)

    # Probe z offset
    probe = cfg.probe_section()
    if probe is not None:
        z = probe.get("z_offset")
        it = Item("z_offset", "known" if z else "not_configured", z)
        if z:
            it.evidence.append(
                f"[{probe.name}] z_offset={z}"
                + (" (SAVE_CONFIG)" if probe.options["z_offset"].autosave else " (set by hand)")
            )
            for sib_id, sib in siblings.items():
                sp = sib.probe_section()
                if sp and sp.get("z_offset") == z:
                    it.state = "inherited"
                    it.evidence.append(f"identical to {sib_id}'s z_offset; probe mounts differ per printer")
        it.last_changed, it.prints_since_change, ts = changed(
            lambda c: c.probe_section().get("z_offset") if c.probe_section() else None
        )
        items.append(it)
        acc = [t for _, _, t in notes if "probe accuracy results" in t]
        items.append(
            Item(
                "probe_accuracy",
                "known" if acc else "unknown",
                acc[-1][:160] if acc else None,
                evidence=["from PROBE_ACCURACY output in klippy.log"]
                if acc
                else ["no PROBE_ACCURACY result in the retained log"],
            )
        )

    # Bed mesh / tram
    pts = klipper_config.bed_mesh_points(cfg)
    mesh_it = Item("bed_mesh", "not_configured" if "bed_mesh" not in cfg.effective else "unknown")
    tram_it = Item("bed_tram", "unknown")
    if pts:
        flat = [v for row in pts for v in row]
        rng = max(flat) - min(flat)
        x_slope = sum(r[-1] - r[0] for r in pts) / len(pts)
        cols = list(zip(*pts, strict=False))
        y_slope = sum(c[-1] - c[0] for c in cols) / len(cols)
        mesh_it.state = "known"
        mesh_it.value = {
            "profile": "default",
            "range_mm": round(rng, 3),
            "points": f"{len(pts[0])}x{len(pts)}",
        }
        mesh_it.last_changed, mesh_it.prints_since_change, ts = changed(lambda c: klipper_config.bed_mesh_points(c))
        if ts and (now - ts) / 86400 > STALE_DAYS["bed_mesh"]:
            mesh_it.state = "stale"
        tram_it.value = {"x_slope_mm": round(x_slope, 3), "y_slope_mm": round(y_slope, 3)}
        tilt = max(abs(x_slope), abs(y_slope))
        tram_it.state = "known" if tilt < 0.3 else "needs_attention"
        tram_it.evidence.append(f"saved mesh tilt X {x_slope:+.2f} mm, Y {y_slope:+.2f} mm across the probed area")
        if any("adjust" in t for _, _, t in notes):
            tram_it.evidence.append("SCREWS_TILT_CALCULATE output present in the retained log")
    items += [mesh_it, tram_it]

    # Extruder
    rd = cfg.value("extruder", "rotation_distance")
    rd_it = Item(
        "extruder_rotation_distance",
        "unknown",
        rd,
        evidence=["configured value; no record of a measured-extrusion calibration"],
    )
    rd_it.last_changed, rd_it.prints_since_change, _ = changed(lambda c: c.value("extruder", "rotation_distance"))
    items.append(rd_it)
    pa = cfg.value("extruder", "pressure_advance")
    items.append(
        Item(
            "pressure_advance",
            "known" if pa and float(pa) > 0 else "default",
            pa or "0 (default)",
            evidence=["not set: Klipper default 0 means pressure advance is off"] if not pa else [],
        )
    )
    shaper = cfg.section("input_shaper")
    items.append(
        Item(
            "input_shaper",
            "known" if shaper else "not_configured",
            {k: v.value for k, v in shaper.options.items()} if shaper else None,
            evidence=[]
            if shaper
            else [
                "no [input_shaper] section"
                + (
                    ""
                    if printer.capabilities.accelerometer
                    else "; no accelerometer in inventory, so tuning means a ringing tower print"
                )
            ],
        )
    )

    # Slicer-side (flow, retraction, temperature) from the last G-code
    slicer: dict[str, Any] = {}
    try:
        jobs = await ctx.client(printer).history_list(limit=1)
        if jobs and jobs[0].get("exists", True):
            data = await ctx.client(printer).download(
                "gcodes", jobs[0]["filename"], max_bytes=ctx.settings.max_gcode_bytes
            )
            rep = gcode_mod.inspect(data.decode("utf-8", "replace"), cfg)
            sc = rep.slicer_config
            slicer = {
                k: sc.get(k)
                for k in (
                    "extrusion_multiplier",
                    "retract_length",
                    "retract_speed",
                    "temperature",
                    "filament_settings_id",
                    "printer_settings_id",
                )
            }
            slicer["mesh_in_start_gcode"] = [o.text for o in rep.mesh_ops]
    except MoonrakerError as err:
        gaps.add("last G-code", err)
    em = slicer.get("extrusion_multiplier")
    items.append(
        Item(
            "flow",
            "unknown",
            em,
            evidence=[
                "slicer extrusion_multiplier from the last print; 1 usually means never tuned for this filament"
                if em
                else "no slicer settings available"
            ],
        )
    )
    items.append(
        Item(
            "retraction",
            "unknown",
            {k: slicer.get(k) for k in ("retract_length", "retract_speed")} if slicer else None,
            evidence=["slicer values; no record of a retraction test"],
        )
    )
    items.append(
        Item(
            "temperature_tower",
            "unknown",
            slicer.get("temperature"),
            evidence=["no record of a temperature tower for this filament"],
        )
    )
    recs = recommend(ctx, printer, cfg, items, slicer)
    return {
        "printer": printer.id,
        "items": [i.to_dict() for i in items],
        "recommendations": recs,
        "slicer_from_last_print": slicer or None,
        "data_gaps": gaps.to_list(),
        "note": "prints_since_change/last_changed exist only once the agent has recorded config history",
    }


async def _sibling_configs(ctx: Context, printer: Printer, gaps: Gaps) -> dict[str, klipper_config.KlipperConfig]:
    out = {}
    for other in ctx.inventory.printers:
        if other.id == printer.id:
            continue
        snap = ctx.store.config_events(other.id, "file", limit=1)
        blob = ctx.store.config_blob(snap[0]["sha"]) if snap else None
        if blob is not None:
            out[other.id] = klipper_config.parse(blob["content"])
            continue
        try:
            out[other.id] = klipper_config.parse(await service.seed_config_text(ctx, other))
        except Exception as err:
            gaps.add(f"sibling config {other.id}", err)
    return out


def recommend(
    ctx: Context,
    printer: Printer,
    cfg: klipper_config.KlipperConfig,
    items: list[Item],
    slicer: dict[str, Any],
) -> list[dict[str, Any]]:
    by = {i.name: i for i in items}
    recs: list[dict[str, Any]] = []

    def add(priority: int, what: str, why: str, how: str, risk: str, after: str | None = None) -> None:
        recs.append(
            {
                "priority": priority,
                "calibrate": what,
                "why": why,
                "how": how,
                "risk": risk,
                **({"after": after} if after else {}),
            }
        )

    for f in klipper_config.validate(cfg):
        if f.code == "verify_heater_disabled":
            add(
                0,
                "restore thermal runaway protection",
                f.message,
                "Propose a config change restoring verify_heater defaults (printer_config_propose); PID tuning "
                "with protection disabled is exactly when a fault goes unnoticed",
                "DANGEROUS (config)",
            )
    recent = ctx.store.diagnoses(printer.id, limit=10)
    thermal_fail = any((d.get("top_class") or "").startswith("THERMAL.") for d in recent)
    for key, heater in (("pid_extruder", "extruder"), ("pid_bed", "heater_bed")):
        it = by.get(key)
        if it is None:
            continue
        if it.state in ("inherited", "stale", "not_configured") or (thermal_fail and key == "pid_extruder"):
            why = "; ".join(it.evidence)
            if thermal_fail and key == "pid_extruder":
                why = "recent diagnoses include thermal failures. " + why
            add(
                1 if it.state == "inherited" else 2,
                f"PID ({heater})",
                why,
                f"PID_CALIBRATE HEATER={heater} TARGET={'215' if heater == 'extruder' else '60'} then SAVE_CONFIG "
                "(fans as during printing)",
                "HIGH_RISK_WRITE (heats hardware)",
            )
    tram = by.get("bed_tram")
    if tram and tram.state == "needs_attention":
        add(
            2,
            "bed tram (screws)",
            "; ".join(tram.evidence) + ". The mesh is compensating mechanical tilt, which "
            "costs first-layer consistency and wastes probe range",
            "SCREWS_TILT_CALCULATE, adjust screws, repeat until within ~0.05 mm, then re-mesh",
            "HIGH_RISK_WRITE (motion + probing)",
        )
    z = by.get("z_offset")
    if z and z.state in ("inherited", "not_configured"):
        add(
            3,
            "probe Z offset",
            "; ".join(z.evidence),
            "PROBE_CALIBRATE with a paper test, then SAVE_CONFIG",
            "HIGH_RISK_WRITE (motion)",
            after="bed tram" if tram and tram.state == "needs_attention" else None,
        )
    elif z and z.prints_since_change is not None and z.prints_since_change < 3:
        add(
            4,
            "first-layer verification",
            f"z_offset changed {z.last_changed} with only {z.prints_since_change} successful prints since",
            "Print a single-layer test patch and inspect squish",
            "HIGH_RISK_WRITE (print)",
        )
    mesh = by.get("bed_mesh")
    if mesh and mesh.state in ("stale", "not_configured") and not slicer.get("mesh_in_start_gcode"):
        add(
            4,
            "bed mesh",
            f"mesh state {mesh.state} and the start G-code does not calibrate one",
            "BED_MESH_CALIBRATE then SAVE_CONFIG",
            "HIGH_RISK_WRITE (motion + probing)",
        )
    rd = by.get("extruder_rotation_distance")
    if rd and rd.state == "unknown":
        add(
            5,
            "extruder rotation_distance",
            "no record that it was measured; flow and pressure advance tuning build on it",
            "Mark 120 mm of filament, extrude 100 mm slowly at temperature, measure the remainder; "
            "new = old * actual/100",
            "HIGH_RISK_WRITE (heats + extrudes)",
        )
    pa = by.get("pressure_advance")
    if pa and pa.state == "default":
        add(
            6,
            "pressure advance",
            "pressure_advance is not set (0)",
            "Klipper's tuning tower method (TUNING_TOWER COMMAND=SET_PRESSURE_ADVANCE ...), then set it in [extruder]",
            "HIGH_RISK_WRITE (print)",
            after="extruder rotation_distance",
        )
    sh = by.get("input_shaper")
    if sh and sh.state == "not_configured":
        add(
            7,
            "input shaper",
            "; ".join(sh.evidence),
            "Ringing tower print per Klipper's Resonance_Compensation guide, then add [input_shaper]",
            "HIGH_RISK_WRITE (print)",
        )
    if slicer.get("extrusion_multiplier") in ("1", "1.0", None):
        add(
            8,
            "flow / retraction / temperature (per filament)",
            "slicer values look untuned for this filament",
            "Temperature tower, then flow cube, then retraction test",
            "HIGH_RISK_WRITE (prints)",
        )
    recs.sort(key=lambda r: r["priority"])
    for i, r in enumerate(recs, start=1):
        r["rank"] = i
    return recs
