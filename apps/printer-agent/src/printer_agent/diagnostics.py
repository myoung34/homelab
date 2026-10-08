"""Evidence-driven diagnostics.

Pipeline for "what happened?":

  gather (job, status, klippy.log, moonraker.log, gcode_store, pods, config
  history, git)  ->  timeline of OBSERVED events  ->  proximate cause (what
  Klipper reported)  ->  root-cause candidates from the taxonomy  ->
  analysers adjust them with evidence for/against  ->  ranked hypotheses,
  explicit unknowns, least-invasive next test.

Nothing in this module changes printer state. The only Moonraker call that is
not a pure read is QUERY_ENDSTOPS, which moves nothing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from printer_agent import klipper_config, klippy_log, service, thermal
from printer_agent.evidence import Certainty, Evidence, Hypothesis, certainty_for_score, iso
from printer_agent.gitrepo import GitError
from printer_agent.inventory import Printer
from printer_agent.moonraker import MoonrakerError
from printer_agent.service import Context, Gaps
from printer_agent.taxonomy import BUILTIN_CLASSES, Signature

logger = logging.getLogger(__name__)

FAILED_STATUSES = ("error", "klippy_shutdown", "klippy_disconnect", "interrupted", "cancelled")
WINDOW_BEFORE = 600.0
WINDOW_AFTER = 120.0


@dataclass(slots=True)
class Diagnosis:
    printer: str
    subject: str
    timeline: list[Evidence] = field(default_factory=list)
    proximate: list[Evidence] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    gaps: Gaps = field(default_factory=Gaps)
    recommendations: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    def classification(self, domain_of: Any) -> dict[str, Any]:
        if not self.hypotheses:
            return {"failure_class": "UNKNOWN", "domain": "unknown", "certainty": "UNKNOWN"}
        top = self.hypotheses[0]
        return {
            "failure_class": top.failure_class,
            "domain": domain_of(top.failure_class),
            "certainty": str(top.certainty),
        }

    def to_dict(self, ctx: Context) -> dict[str, Any]:
        return {
            "printer": self.printer,
            "subject": self.subject,
            "classification": self.classification(ctx.taxonomy.domain),
            "proximate_cause": [e.to_dict() for e in self.proximate],
            "hypotheses": [{**h.to_dict(), "domain": ctx.taxonomy.domain(h.failure_class)} for h in self.hypotheses],
            "timeline": [e.to_dict() for e in sorted(self.timeline, key=lambda e: e.timestamp or 0)][-60:],
            "unknowns": self.unknowns,
            "data_gaps": self.gaps.to_list(),
            "recommendations": self.recommendations,
            "context": self.context,
            "actions_taken": "none - diagnosis is read-only",
        }


# ======================================================================
# "What happened?"
# ======================================================================


async def what_happened(
    ctx: Context, printer: Printer, *, job_id: str | None = None, which: str = "last"
) -> dict[str, Any]:
    d = Diagnosis(printer.id, "")
    client = ctx.client(printer)
    job: dict[str, Any] | None = None
    jobs: list[dict[str, Any]] = []
    try:
        jobs = await client.history_list(limit=100)
        for j in jobs:
            ctx.store.record_job(printer.id, j)
        if job_id:
            job = await client.history_job(job_id)
        elif which == "last_failed":
            job = next((j for j in jobs if j.get("status") in FAILED_STATUSES), None)
        else:
            job = jobs[0] if jobs else None
    except MoonrakerError as err:
        d.gaps.add("print history", err)

    st = await service.status(ctx, printer)
    d.context["current_state"] = {k: st.get(k) for k in ("klippy_state", "state_message", "moonraker")}
    for g in st.get("data_gaps", []):
        d.gaps.items.append(g)
    if st.get("moonraker") == "unreachable":
        _offline_hypotheses(d, st)
        return _finish(ctx, d, "printer offline")

    now = ctx.clock.now()
    if job:
        start = float(job.get("start_time") or now)
        end = float(job["end_time"]) if job.get("end_time") else now
        d.subject = f"job {job.get('job_id')} ({job.get('filename')}) - {job.get('status')}"
        d.context["job"] = _job_summary(job)
        d.timeline.append(
            Evidence(
                f"print started: {job.get('filename')}",
                Certainty.OBSERVED,
                f"moonraker history job {job.get('job_id')}",
                start,
            )
        )
        if job.get("end_time"):
            d.timeline.append(
                Evidence(
                    f"print ended with status '{job.get('status')}' after {job.get('print_duration', 0) / 60:.1f} "
                    "min printing",
                    Certainty.OBSERVED,
                    f"moonraker history job {job.get('job_id')}",
                    end,
                )
            )
        progress = _job_progress(job)
        if progress is not None:
            d.context["job"]["progress_at_end_pct"] = progress
    else:
        start, end = now - 3600, now
        d.subject = "most recent activity (no job found)"
        d.unknowns.append("no print job in Moonraker history matched the request")

    log = await service.klippy(ctx, printer, d.gaps, live_offset=st.get("live_offset"))
    log = await _log_covering(ctx, printer, log, start, d.gaps, st.get("live_offset"))
    w_start, w_end = start - WINDOW_BEFORE, end + WINDOW_AFTER
    cfg = await _config_at(ctx, printer, start, d.gaps)

    events: list[tuple[klippy_log.LogEvent, klippy_log.Session]] = []
    if log is not None:
        for s in log.sessions:
            for ev in s.events:
                if ev.wall is not None and w_start <= ev.wall <= w_end:
                    events.append((ev, s))
        if not events and any(s.start_wall is None for s in log.sessions):
            d.unknowns.append("part of klippy.log could not be anchored to wall-clock time")
        anchored = [s for s in log.sessions if s.anchored_by == "live_offset"]
        if anchored:
            d.unknowns.append(
                "some klippy.log timestamps were derived from the current monotonic clock "
                "offset; they are wrong if the node rebooted since"
            )
    for ev, _s in events:
        d.timeline.append(
            Evidence(
                ev.statement or ev.text,
                Certainty.OBSERVED,
                f"klippy.log line {ev.line_no}",
                ev.wall,
                ev.approximate,
                {"raw": ev.text[:200]} if ev.statement else {},
            )
        )

    gstore = await _gcode_store_window(ctx, printer, w_start, w_end, d)
    mr_events = service.moonraker_events(await service.moonraker_log_tail(ctx, printer, d.gaps))
    for m in mr_events:
        if m["time"] and w_start <= m["time"] <= w_end:
            d.timeline.append(Evidence(m["line"], Certainty.OBSERVED, "moonraker.log", m["time"]))
    workload = await service.workload(ctx, printer, d.gaps)
    restarts = _restarts_in_window(workload, w_start, w_end)
    for r in restarts:
        d.timeline.append(r)

    # ---------------------------------------------------- classification
    status_ = (job or {}).get("status")
    fatal = _fatal_candidates(events, gstore, ctx, end)
    if fatal:
        fev, sig, groups, session = fatal[0]
        if (
            sig.id == "endstop_no_trigger"
            and groups.get("axis", "").lower() == "z"
            and cfg
            and "z_virtual_endstop" in (cfg.value("stepper_z", "endstop_pin") or "")
        ):
            sig = next(s for s in ctx.taxonomy.signatures if s.id == "probe_no_trigger")
            d.context["note"] = "'No trigger on z' remapped to the probe: stepper_z homes with probe:z_virtual_endstop"
        d.proximate.append(
            Evidence(
                sig.statement.format_map(_Default(groups)),
                Certainty.OBSERVED,
                fev.source,
                fev.timestamp,
                fev.time_approximate,
                {"raw": fev.data.get("raw")},
            )
        )
        if status_ in ("klippy_shutdown", "error") and job:
            d.proximate.append(
                Evidence(
                    f"this event ended job {job.get('job_id')}: job status is '{status_}' and the event is the "
                    "first fatal message before the job's end time",
                    Certainty.INFERRED,
                    "correlation",
                    fev.timestamp,
                )
            )
        hyps = _hypotheses_from_signature(sig, groups)
        if session is not None:
            _analyse(ctx, d, hyps, sig, groups, session, fev, cfg, workload, restarts, printer)
        await _correlate_config_changes(ctx, d, printer, job, jobs, hyps, sig)
        d.hypotheses = _rank(hyps)
    elif status_ == "cancelled":
        who = (job or {}).get("user") or "unknown user"
        d.proximate.append(Evidence(f"job was cancelled (user: {who})", Certainty.OBSERVED, "moonraker history", end))
        cancel_cmd = [g for g in gstore if "CANCEL" in g["message"].upper()]
        sup = [
            Evidence(
                f"'{c['message']}' received at {iso(c['time'])}",
                Certainty.OBSERVED,
                "gcode_store",
                c["time"],
            )
            for c in cancel_cmd
        ]
        d.hypotheses = [
            Hypothesis(
                "OPERATOR.cancelled",
                "a person cancelled the print",
                Certainty.LIKELY,
                0.8,
                sup,
                [],
                "Ask why it was cancelled; check the camera/print if quality was the reason.",
                "READ_ONLY",
            )
        ]
        d.unknowns.append("why the print was cancelled (quality, spaghetti, wrong file) is not recorded")
    elif status_ in ("klippy_disconnect", "interrupted"):
        _disconnect_hypotheses(d, status_, restarts, end)
    elif status_ == "completed":
        d.proximate.append(Evidence("job completed successfully", Certainty.OBSERVED, "moonraker history", end))
    elif status_ == "in_progress":
        d.proximate.append(Evidence("job is still in progress", Certainty.OBSERVED, "moonraker history"))
    else:
        d.unknowns.append(
            "no fatal message found in klippy.log, gcode responses or Moonraker log within the job window"
        )
        d.hypotheses = [Hypothesis("UNKNOWN", "no evidence identifies a cause", Certainty.UNKNOWN, 0.0)]
    d.context["config_at_job_start"] = cfg is not None
    return _finish(ctx, d, d.subject)


class _Default(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return f"<{key}>"


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "job_id",
        "filename",
        "status",
        "start_time",
        "end_time",
        "print_duration",
        "total_duration",
        "filament_used",
        "user",
    )
    out = {k: job.get(k) for k in keep}
    for k in ("start_time", "end_time"):
        if out.get(k):
            out[f"{k}_iso"] = iso(float(out[k]))  # type: ignore[arg-type]
    md = job.get("metadata") or {}
    out["slicer"] = md.get("slicer")
    out["estimated_time"] = md.get("estimated_time")
    return out


def _job_progress(job: dict[str, Any]) -> float | None:
    md = job.get("metadata") or {}
    used, total = job.get("filament_used"), md.get("filament_total")
    if used and total:
        return round(100.0 * float(used) / float(total), 1)
    return None


async def _log_covering(
    ctx: Context,
    printer: Printer,
    log: klippy_log.KlippyLog | None,
    ts: float,
    gaps: Gaps,
    live_offset: float | None,
) -> klippy_log.KlippyLog | None:
    """Fall back to a rotated klippy.log if the current one starts after ts."""

    def covers(lg: klippy_log.KlippyLog | None) -> bool:
        return bool(lg and any(s.start_wall is not None and s.start_wall <= ts for s in lg.sessions))

    if covers(log):
        return log
    try:
        files = await service.log_files(ctx, printer)
    except MoonrakerError as err:
        gaps.add("logs listing", err)
        return log
    for f in files:
        name = f.get("path") or f.get("filename") or ""
        if not name.startswith("klippy.log.") or float(f.get("modified", 0)) < ts:
            continue
        older = await service.klippy(ctx, printer, gaps, filename=name)
        if covers(older):
            return older
    gaps.add("klippy.log", "no retained klippy.log covers the job start (Klipper keeps ~5 days)")
    return log


async def _config_at(ctx: Context, printer: Printer, ts: float, gaps: Gaps) -> klipper_config.KlipperConfig | None:
    snap = ctx.store.config_at(printer.id, "loaded", ts)
    if snap:
        return klipper_config.parse(snap["content"])
    try:
        return klipper_config.parse(await service.loaded_config_text(ctx, printer))
    except MoonrakerError as err:
        gaps.add("config at job start", f"no snapshot and live read failed: {err}")
        return None


async def _gcode_store_window(
    ctx: Context, printer: Printer, start: float, end: float, d: Diagnosis
) -> list[dict[str, Any]]:
    try:
        store = await ctx.client(printer).gcode_store(count=1000)
    except MoonrakerError as err:
        d.gaps.add("gcode_store", err)
        return []
    out = [g for g in store if start <= float(g.get("time", 0)) <= end]
    for g in out:
        msg = str(g.get("message", ""))
        if msg.startswith("!!") or "error" in msg.lower() or g.get("type") == "command":
            d.timeline.append(
                Evidence(
                    msg[:200],
                    Certainty.OBSERVED,
                    f"gcode_store ({g.get('type')})",
                    float(g["time"]),
                )
            )
    return out


def _fatal_candidates(
    events: list[tuple[klippy_log.LogEvent, klippy_log.Session]],
    gstore: list[dict[str, Any]],
    ctx: Context,
    end: float,
) -> list[tuple[Evidence, Signature, dict[str, str], klippy_log.Session | None]]:
    out: list[tuple[Evidence, Signature, dict[str, str], klippy_log.Session | None]] = []
    sigs = {s.id: s for s in ctx.taxonomy.signatures}
    for ev, s in events:
        if ev.signature is None or ev.wall is None:
            continue
        sig = sigs[ev.signature]
        if not sig.fatal and ev.kind != "shutdown":
            continue
        prio = 0 if ev.kind == "shutdown" else 1
        out.append(
            (
                Evidence(
                    ev.text,
                    Certainty.OBSERVED,
                    f"klippy.log line {ev.line_no}",
                    ev.wall,
                    ev.approximate,
                    {"raw": ev.text[:200], "prio": prio},
                ),
                sig,
                ev.groups,
                s,
            )
        )
    for g in gstore:
        msg = str(g.get("message", ""))
        if not msg.startswith("!!"):
            continue
        m = ctx.taxonomy.match(msg)
        if m:
            sig, groups = m
            out.append(
                (
                    Evidence(
                        msg,
                        Certainty.OBSERVED,
                        "gcode_store",
                        float(g["time"]),
                        False,
                        {"raw": msg[:200], "prio": 2},
                    ),
                    sig,
                    groups,
                    None,
                )
            )
    # The cause is the *earliest* fatal message before the end, preferring
    # shutdown transitions; later messages are consequences.
    before = [c for c in out if (c[0].timestamp or 0) <= end + 5]
    before.sort(key=lambda c: (c[0].timestamp or 0, c[0].data.get("prio", 9)))
    if before:
        first_t = before[0][0].timestamp or 0
        near = [c for c in before if (c[0].timestamp or 0) - first_t <= 2.0]
        near.sort(key=lambda c: c[0].data.get("prio", 9))
        return near + [c for c in before if c not in near]
    return out


def _hypotheses_from_signature(sig: Signature, groups: dict[str, str]) -> list[Hypothesis]:
    return [
        Hypothesis(
            rc.failure_class,
            rc.summary.format_map(_Default(groups)),
            Certainty.POSSIBLE,
            rc.prior,
            [],
            [],
            rc.test,
            rc.test_risk,
        )
        for rc in sig.root_causes
    ] or [Hypothesis(sig.failure_class, sig.statement.format_map(_Default(groups)), Certainty.POSSIBLE, 0.5)]


_CLASS_DESCRIPTIONS = {c.id: c.description for c in BUILTIN_CLASSES}


def _bump(hyps: list[Hypothesis], cls: str, delta: float, ev: Evidence, *, against: bool = False) -> None:
    """Apply evidence to a hypothesis. Evidence *for* a class nobody proposed
    adds that hypothesis instead of being dropped."""
    for h in hyps:
        if h.failure_class == cls:
            h.score = max(0.0, min(1.0, h.score + delta))
            (h.contradicting if against else h.supporting).append(ev)
            return
    if not against and delta > 0:
        hyps.append(
            Hypothesis(cls, _CLASS_DESCRIPTIONS.get(cls, cls), Certainty.POSSIBLE, min(1.0, 0.1 + delta), [ev], [])
        )


def _rank(hyps: list[Hypothesis]) -> list[Hypothesis]:
    # Collapse duplicates of the same class (keep best), then rank.
    best: dict[str, Hypothesis] = {}
    for h in hyps:
        cur = best.get(h.failure_class)
        if cur is None or h.score > cur.score:
            if cur is not None:
                h.supporting.extend(cur.supporting)
            best[h.failure_class] = h
    ranked = sorted(best.values(), key=lambda h: h.score, reverse=True)
    for i, h in enumerate(ranked):
        h.certainty = certainty_for_score(h.score)
        # Only one hypothesis can be LIKELY at a time unless clearly separated.
        if i > 0 and h.certainty == Certainty.LIKELY and ranked[0].score - h.score < 0.15:
            h.certainty = Certainty.POSSIBLE
            ranked[0].certainty = Certainty.POSSIBLE
    return ranked


def _analyse(
    ctx: Context,
    d: Diagnosis,
    hyps: list[Hypothesis],
    sig: Signature,
    groups: dict[str, str],
    session: klippy_log.Session,
    ev: Evidence,
    cfg: klipper_config.KlipperConfig | None,
    workload: dict[str, Any] | None,
    restarts: list[Evidence],
    printer: Printer,
) -> None:
    end_mono = session.to_mono(ev.timestamp) if ev.timestamp else None
    if sig.id in ("heater_not_heating", "adc_out_of_range"):
        heaters = [groups["heater"]] if groups.get("heater") else list(klippy_log.HEATER_GROUPS)
        for heater in heaters:
            trace = klippy_log.heater_trace(session, heater, end_mono=end_mono)
            if not trace:
                d.unknowns.append(f"no Stats samples for {heater} before the event")
                continue
            shape = thermal.runaway_shape(trace)
            d.context.setdefault("thermal_traces", {})[heater] = {
                **shape,
                "last_samples": trace[-15:],
            }
            src = f"klippy.log Stats ({heater}, last {len(trace)} s)"
            if shape["shape"] == "sensor_jumps":
                _bump(
                    hyps,
                    "THERMAL.thermistor_failure",
                    0.4,
                    Evidence(
                        f"{heater} reading jumped >10C between consecutive samples {shape['single_sample_jumps']} "
                        "time(s) before the shutdown",
                        Certainty.OBSERVED,
                        src,
                        data=shape,
                    ),
                )
                _bump(
                    hyps,
                    "THERMAL.heater_failure",
                    -0.15,
                    Evidence(
                        "physically impossible temperature jumps implicate the sensor rather than the heater",
                        Certainty.INFERRED,
                        src,
                    ),
                    against=True,
                )
            elif shape["shape"] in ("falling_at_full_power", "flat_below_target_at_full_power"):
                _bump(
                    hyps,
                    "THERMAL.heater_failure",
                    0.35,
                    Evidence(
                        f"{heater} PWM was >=95% for {shape['pwm_saturated_fraction']:.0%} of the last minute while "
                        f"temperature went {shape['temp_first']:.1f}->{shape['temp_last']:.1f}C "
                        f"(target {shape['target']:g}C)",
                        Certainty.OBSERVED,
                        src,
                        data=shape,
                    ),
                )
                _bump(
                    hyps,
                    "THERMAL.temperature_instability",
                    0.1,
                    Evidence(
                        "full power not holding temperature is also consistent with strong airflow on the block",
                        Certainty.POSSIBLE,
                        src,
                    ),
                )
            elif sig.id == "adc_out_of_range":
                lo = cfg.float_value(heater, "min_temp") if cfg else None
                hi = cfg.float_value(heater, "max_temp") if cfg else None
                last = shape.get("temp_last")
                if isinstance(last, float) and hi is not None and last >= hi - 10:
                    _bump(
                        hyps,
                        "THERMAL.thermal_runaway",
                        0.3,
                        Evidence(
                            f"{heater} read {last:.1f}C near max_temp {hi:g}C",
                            Certainty.OBSERVED,
                            src,
                        ),
                    )
                elif isinstance(last, float) and lo is not None and last <= lo + 10:
                    _bump(
                        hyps,
                        "THERMAL.thermistor_failure",
                        0.3,
                        Evidence(
                            f"{heater} read {last:.1f}C near min_temp {lo:g}C: open-circuit thermistor signature",
                            Certainty.OBSERVED,
                            src,
                        ),
                    )
        if cfg is not None:
            for vh in cfg.sections_of_type("verify_heater"):
                me = cfg.float_value(vh.name, "max_error")
                if me is not None and me != 120:
                    _bump(
                        hyps,
                        "THERMAL.thermal_config",
                        0.1,
                        Evidence(
                            f"[{vh.name}] max_error={me:g} (default 120)",
                            Certainty.OBSERVED,
                            "config at job start",
                        ),
                    )
    if sig.id in ("lost_comm", "timeout_mcu", "eof_serial", "timer_too_close"):
        trend = klippy_log.link_trend(session, end_mono=end_mono)
        if trend:
            d.context["mcu_link_before_event"] = trend
            src = "klippy.log Stats (5 min before event)"
            if trend["retransmit_bytes"] > 100 or trend["invalid_bytes"] > 0:
                _bump(
                    hyps,
                    "FIRMWARE.mcu_disconnect",
                    0.2,
                    Evidence(
                        f"MCU link degraded before the event: +{trend['retransmit_bytes']:g} retransmitted bytes, "
                        f"+{trend['invalid_bytes']:g} invalid bytes",
                        Certainty.OBSERVED,
                        src,
                        data=trend,
                    ),
                )
            elif trend["retransmit_bytes"] == 0:
                _bump(
                    hyps,
                    "FIRMWARE.mcu_disconnect",
                    -0.1,
                    Evidence(
                        "no retransmits in the 5 minutes before: the link was clean until it vanished",
                        Certainty.OBSERVED,
                        src,
                    ),
                    against=True,
                )
                _bump(
                    hyps,
                    "POWER.brownout",
                    0.1,
                    Evidence(
                        "an abrupt loss on a clean link is more typical of power loss/reset than a marginal cable",
                        Certainty.POSSIBLE,
                        src,
                    ),
                )
            if (trend.get("max_sysload") or 0) > 3.0 or (trend.get("min_memavail_kb") or 1e12) < 100_000:
                _bump(
                    hyps,
                    "NETWORK.host_failure",
                    0.3,
                    Evidence(
                        f"host under pressure: max sysload {trend.get('max_sysload')}, min memavail "
                        f"{trend.get('min_memavail_kb')} kB",
                        Certainty.OBSERVED,
                        src,
                    ),
                )
            elif trend.get("max_sysload") is not None:
                _bump(
                    hyps,
                    "NETWORK.host_failure",
                    -0.1,
                    Evidence(
                        f"host load normal (max sysload {trend.get('max_sysload')})",
                        Certainty.OBSERVED,
                        src,
                    ),
                    against=True,
                )
        for r in restarts:
            _bump(hyps, "NETWORK.host_failure", 0.4, r)
        bed = klippy_log.heater_trace(session, "heater_bed", end_mono=end_mono, window=30)
        if bed and bed[-1]["pwm"] > 0.8:
            _bump(
                hyps,
                "POWER.brownout",
                0.1,
                Evidence(
                    f"bed heater at {bed[-1]['pwm']:.0%} power at the moment of the event",
                    Certainty.OBSERVED,
                    "klippy.log Stats",
                ),
            )
    if (
        sig.id
        in (
            "probe_prior",
            "probe_no_trigger",
            "bltouch_verify",
            "probe_tolerance",
            "endstop_no_trigger",
            "endstop_still_triggered",
        )
        and cfg is not None
    ):
        for f in klipper_config.validate(cfg):
            if f.code in (
                "bltouch_no_pullup",
                "virtual_endstop_without_probe",
                "safe_z_home_unreachable",
                "mesh_unreachable",
                "probe_z_offset_missing",
            ):
                _bump(
                    hyps,
                    "PROBE.probe_configuration"
                    if "probe" in sig.failure_class.lower() or f.code.startswith("bltouch")
                    else "MOTION.endstop_configuration",
                    0.25,
                    Evidence(f.message, Certainty.OBSERVED, f"config validation ({f.code})"),
                )
        _compare_probe_with_fleet(ctx, d, hyps, printer, cfg)
    if sig.id == "tmc_error":
        flags = groups.get("flags", "")
        stepper = groups.get("stepper", "")
        src = "klippy.log"
        if "uv_cp" in flags:
            _bump(
                hyps,
                "POWER.brownout",
                0.4,
                Evidence("driver reported uv_cp (charge pump undervoltage)", Certainty.OBSERVED, src),
            )
        if re.search(r"s2v?s?[gv]?[ab]", flags):
            _bump(
                hyps,
                "MOTION.driver_fault",
                0.1,
                Evidence(f"short-detection flag in: {flags[:120]}", Certainty.OBSERVED, src),
            )
        if cfg is not None:
            sec = cfg.section(f"tmc2209 {stepper}") or cfg.section(f"tmc2208 {stepper}")
            if sec is not None and float(sec.get("stealthchop_threshold", "0") or 0) > 0:
                _bump(
                    hyps,
                    "MOTION.driver_configuration",
                    0.3,
                    Evidence(
                        f"[{sec.name}] has stealthchop_threshold={sec.get('stealthchop_threshold')} - StealthChop is "
                        "known to cause false short detections at standstill on some motors/extruders",
                        Certainty.OBSERVED,
                        "config at job start",
                    ),
                )


def _compare_probe_with_fleet(
    ctx: Context,
    d: Diagnosis,
    hyps: list[Hypothesis],
    printer: Printer,
    cfg: klipper_config.KlipperConfig,
) -> None:
    """Same probe settings working elsewhere points at hardware; different points at config."""
    mine = cfg.probe_section()
    if mine is None:
        return
    for other in ctx.inventory.enabled():
        if other.id == printer.id:
            continue
        good = [j for j in ctx.store.jobs(other.id, limit=50) if j["status"] == "completed" and j.get("loaded_sha")]
        if not good:
            continue
        blob = ctx.store.config_blob(good[0]["loaded_sha"])
        if blob is None:
            continue
        theirs = klipper_config.parse(blob["content"]).probe_section()
        if theirs is None or theirs.type != mine.type:
            continue
        keys = (
            "sensor_pin",
            "control_pin",
            "pin",
            "pin_up_reports_not_triggered",
            "pin_up_touch_mode_reports_triggered",
            "probe_with_touch_mode",
            "stow_on_each_sample",
            "speed",
            "samples_tolerance",
            "pin_move_time",
        )
        diffs = {k: (mine.get(k), theirs.get(k)) for k in keys if mine.get(k) != theirs.get(k)}
        src = f"config comparison with {other.id} (last completed print)"
        if diffs:
            _bump(
                hyps,
                "PROBE.probe_configuration",
                0.25,
                Evidence(
                    f"{other.id} prints successfully with different [{mine.type}] settings: "
                    + ", ".join(f"{k}: {a!r} here vs {b!r} there" for k, (a, b) in diffs.items()),
                    Certainty.OBSERVED,
                    src,
                    data={"differences": diffs},
                ),
            )
        else:
            _bump(
                hyps,
                "PROBE.probe_wiring",
                0.2,
                Evidence(
                    f"{other.id} prints successfully with identical [{mine.type}] trigger settings, which points away "
                    "from configuration and toward this printer's probe hardware or wiring",
                    Certainty.INFERRED,
                    src,
                ),
            )
            _bump(
                hyps,
                "PROBE.probe_configuration",
                -0.15,
                Evidence(
                    f"probe settings identical to working printer {other.id}",
                    Certainty.OBSERVED,
                    src,
                ),
                against=True,
            )
        return


async def _correlate_config_changes(
    ctx: Context,
    d: Diagnosis,
    printer: Printer,
    job: dict[str, Any] | None,
    jobs: list[dict[str, Any]],
    hyps: list[Hypothesis],
    sig: Signature,
) -> None:
    if not job or not job.get("start_time"):
        return
    start = float(job["start_time"])
    last_good = next(
        (j for j in jobs if j.get("status") == "completed" and float(j.get("start_time") or 0) < start),
        None,
    )
    if last_good is None:
        d.unknowns.append("no earlier successful print to compare configuration against")
        return
    d.context["last_successful_job"] = _job_summary(last_good)
    good_cfg = ctx.store.config_at(printer.id, "loaded", float(last_good["start_time"]))
    bad_cfg = ctx.store.config_at(printer.id, "loaded", start)
    if good_cfg and bad_cfg:
        if good_cfg["sha"] == bad_cfg["sha"]:
            ev = Evidence(
                "the loaded configuration was identical for the last successful print and this one",
                Certainty.OBSERVED,
                "config snapshots",
            )
            d.context["config_changed_since_last_success"] = False
            for h in hyps:
                if ctx.taxonomy.domain(h.failure_class) == "configuration":
                    _bump(hyps, h.failure_class, -0.15, ev, against=True)
        else:
            changes = klipper_config.semantic_diff(
                klipper_config.parse(good_cfg["content"]), klipper_config.parse(bad_cfg["content"])
            )
            d.context["config_changes_since_last_success"] = [c.to_dict() for c in changes][:40]
            related = [c for c in changes if _related(c.section, sig)]
            if related:
                for h in hyps:
                    if ctx.taxonomy.domain(h.failure_class) == "configuration":
                        _bump(
                            hyps,
                            h.failure_class,
                            0.3,
                            Evidence(
                                "related configuration changed between the last successful print and this one: "
                                + "; ".join(f"[{c.section}] {c.option}: {c.old!r} -> {c.new!r}" for c in related[:5]),
                                Certainty.OBSERVED,
                                "config snapshots",
                            ),
                        )
    else:
        d.unknowns.append(
            "no config snapshot for one of the jobs (agent was not running yet, or older than "
            "retained klippy.log); cannot say whether the configuration changed"
        )
    if ctx.git is not None and printer.git is not None:
        try:
            commits = await ctx.git.log(
                printer.git.path,
                since=str(int(float(last_good["start_time"]))),
                until=str(int(start)),
                limit=20,
            )
            if commits:
                d.context["git_commits_between"] = [c.to_dict() for c in commits]
                d.context["git_note"] = (
                    "these commits change the *seed* ConfigMap; they only affect the printer "
                    "if the PVC copy was re-seeded or edited to match"
                )
        except GitError as err:
            d.gaps.add("git log", err)


def _related(section: str, sig: Signature) -> bool:
    stype = section.split()[0]
    cls = sig.failure_class.split(".")[0]
    groups = {
        "PROBE": ("bltouch", "probe", "safe_z_home", "stepper_z", "bed_mesh"),
        "MOTION": (
            "stepper_x",
            "stepper_y",
            "stepper_z",
            "tmc2209",
            "tmc2208",
            "printer",
            "safe_z_home",
        ),
        "THERMAL": ("extruder", "heater_bed", "verify_heater", "fan", "heater_fan"),
        "FIRMWARE": ("mcu",),
        "EXTRUSION": ("extruder", "filament_switch_sensor"),
    }
    return stype in groups.get(cls, ())


def _restarts_in_window(workload: dict[str, Any] | None, start: float, end: float) -> list[Evidence]:
    import calendar
    import time as _t

    out = []
    for p in (workload or {}).get("pods", []):
        for c in p.get("containers", []):
            lt = c.get("last_termination") or {}
            fin = lt.get("finishedAt")
            if not fin:
                continue
            try:
                ts = float(calendar.timegm(_t.strptime(fin, "%Y-%m-%dT%H:%M:%SZ")))
            except ValueError:
                continue
            if start <= ts <= end:
                out.append(
                    Evidence(
                        f"container {c['name']} in pod {p['pod']} terminated: {lt.get('reason')} "
                        f"(exit {lt.get('exitCode')})",
                        Certainty.OBSERVED,
                        "kubernetes pod status",
                        ts,
                    )
                )
    return out


def _disconnect_hypotheses(d: Diagnosis, status_: str, restarts: list[Evidence], end: float) -> None:
    d.proximate.append(
        Evidence(
            f"Moonraker recorded the job as '{status_}'",
            Certainty.OBSERVED,
            "moonraker history",
            end,
        )
    )
    hyps = [
        Hypothesis(
            "NETWORK.host_failure",
            "klipper/moonraker container or its node restarted",
            Certainty.POSSIBLE,
            0.35,
            list(restarts),
            [],
            "Check pod restarts and node events around the end time.",
        ),
        Hypothesis(
            "POWER.host_shutdown",
            "the node lost power or rebooted",
            Certainty.POSSIBLE,
            0.3,
            [],
            [],
            "Check node uptime / Talos events (homelab-agent can read nodes).",
        ),
        Hypothesis(
            "FIRMWARE.klipper_crash",
            "Klippy process exited unexpectedly",
            Certainty.POSSIBLE,
            0.2,
            [],
            [],
            "Read the end of the previous klippy.log session for a traceback.",
        ),
    ]
    if restarts:
        hyps[0].score = 0.8
    d.hypotheses = _rank(hyps)
    if not restarts:
        d.unknowns.append(
            "no container termination was recorded in the window; a node reboot replaces pod "
            "status, so a power loss can leave no trace here"
        )


def _offline_hypotheses(d: Diagnosis, st: dict[str, Any]) -> None:
    d.proximate.append(
        Evidence(
            f"Moonraker is unreachable: {st.get('error')}",
            Certainty.OBSERVED,
            "moonraker /server/info",
            st.get("observed_at"),
        )
    )
    k = st.get("kubernetes") or {}
    notes = k.get("observations", [])
    hyps = [
        Hypothesis(
            "POWER.printer_shutdown",
            "printer powered off/unplugged, so its MCU is not on USB and the pod cannot schedule",
            Certainty.POSSIBLE,
            0.3,
        ),
        Hypothesis(
            "NETWORK.host_failure",
            "klipper pod crashed or its node is down",
            Certainty.POSSIBLE,
            0.3,
        ),
        Hypothesis("NETWORK.connectivity", "service/DNS path to Moonraker broken", Certainty.POSSIBLE, 0.15),
    ]
    for n in notes:
        ev = Evidence(n, Certainty.OBSERVED, "kubernetes")
        if "USB serial" in n:
            _bump(hyps, "POWER.printer_shutdown", 0.5, ev)
        elif "OOMKilled" in n or "CrashLoop" in n or "terminated" in n:
            _bump(hyps, "NETWORK.host_failure", 0.4, ev)
    if not notes:
        d.unknowns.append("Kubernetes workload state unavailable (no RBAC/kube access or not configured)")
    d.hypotheses = _rank(hyps)


def _finish(ctx: Context, d: Diagnosis, subject: str) -> dict[str, Any]:
    d.subject = d.subject or subject
    if d.hypotheses and d.hypotheses[0].next_test:
        top = d.hypotheses[0]
        d.recommendations.append(f"Least-invasive next test ({top.next_test_risk}): {top.next_test}")
    if any(h.certainty == Certainty.LIKELY for h in d.hypotheses) is False and d.hypotheses:
        d.recommendations.append(
            "No single root cause is LIKELY yet; run the next test before changing configuration or replacing hardware."
        )
    out = d.to_dict(ctx)
    cls = out["classification"]
    ctx.store.record_diagnosis(d.printer, "what_happened", d.subject, cls["failure_class"], out)
    return out


# ======================================================================
# Failure history classification
# ======================================================================


async def classify_history(ctx: Context, printer: Printer, limit: int = 10) -> dict[str, Any]:
    gaps = Gaps()
    try:
        jobs = await ctx.client(printer).history_list(limit=200)
    except MoonrakerError as err:
        return {
            "printer": printer.id,
            "error": str(err),
            "data_gaps": [{"source": "history", "reason": str(err)}],
        }
    for j in jobs:
        ctx.store.record_job(printer.id, j)
    failed = [j for j in jobs if j.get("status") in FAILED_STATUSES][:limit]
    st = await service.status(ctx, printer)
    log = await service.klippy(ctx, printer, gaps, live_offset=st.get("live_offset"))
    out = []
    counts: dict[str, int] = {}
    for j in failed:
        start = float(j.get("start_time") or 0)
        end = float(j.get("end_time") or start)
        entry: dict[str, Any] = {
            "job_id": j.get("job_id"),
            "filename": j.get("filename"),
            "status": j.get("status"),
            "end_time": iso(end) if end else None,
        }
        cls, certainty, evidence = "UNKNOWN", Certainty.UNKNOWN, None
        if j.get("status") == "cancelled":
            cls, certainty, evidence = (
                "OPERATOR.cancelled",
                Certainty.OBSERVED,
                "Moonraker status 'cancelled'",
            )
        if log is not None:
            covered = any(s.start_wall is not None and s.start_wall <= start for s in log.sessions)
            hits = [
                e
                for s in log.sessions
                for e in s.events
                if e.signature and e.wall and start - 60 <= e.wall <= end + 5 and (e.kind in ("shutdown", "error"))
            ]
            if hits:
                first = sorted(hits, key=lambda e: e.wall or 0)[0]
                cls = first.failure_class or "UNKNOWN"
                certainty = Certainty.OBSERVED
                evidence = f"klippy.log line {first.line_no}: {first.text[:160]}"
            elif not covered and j.get("status") != "cancelled":
                evidence = "outside retained klippy.log"
        entry.update(
            {
                "failure_class": cls,
                "domain": ctx.taxonomy.domain(cls),
                "certainty": str(certainty),
                "evidence": evidence,
            }
        )
        counts[cls] = counts.get(cls, 0) + 1
        out.append(entry)
    totals = {s: sum(1 for j in jobs if j.get("status") == s) for s in {str(j.get("status")) for j in jobs}}
    return {
        "printer": printer.id,
        "jobs_considered": len(jobs),
        "status_totals": totals,
        "failed_jobs": out,
        "by_class": counts,
        "data_gaps": gaps.to_list(),
        "note": "classification here is the proximate cause only; run printer_what_happened on a job for "
        "root-cause analysis",
    }


# ======================================================================
# Readiness
# ======================================================================


async def readiness(ctx: Context, printer: Printer) -> dict[str, Any]:
    blocking: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    recs: list[str] = []
    checks: dict[str, str] = {}

    def block(reason: str, severity: str = "critical") -> None:
        blocking.append({"reason": reason, "severity": severity})

    def warn(reason: str, severity: str = "warning") -> None:
        warnings.append({"reason": reason, "severity": severity})

    st = await service.status(ctx, printer)
    if st.get("moonraker") in ("unreachable", "error"):
        block(f"Moonraker unreachable: {st.get('error')}")
        for n in (st.get("kubernetes") or {}).get("observations", []):
            block(n, "critical")
        return {
            "printer": printer.id,
            "ready": False,
            "blocking": blocking,
            "warnings": warnings,
            "recommendations": ["Check printer power/USB and the klipper pod"],
            "checks": {"moonraker": "fail"},
            "data_gaps": st.get("data_gaps", []),
        }
    checks["moonraker"] = "ok"
    ks = st.get("klippy_state")
    if ks != "ready":
        block(f"Klipper state is '{ks}': {st.get('state_message') or ''}".strip())
        if ks == "shutdown":
            recs.append("Run printer_what_happened to find the shutdown cause before restarting")
        checks["klipper"] = "fail"
    else:
        checks["klipper"] = "ok"
        checks["mcu"] = "ok (Klipper ready implies all MCUs connected)"
    for comp in (st.get("moonraker") or {}).get("failed_components", []) or []:
        warn(f"Moonraker component failed to load: {comp}")
    pstate = (st.get("print") or {}).get("state")
    if pstate in ("printing", "paused"):
        block(f"printer is busy ({pstate}: {(st.get('print') or {}).get('filename')})", "info")
    elif pstate == "error":
        warn(f"print_stats reports last print ended in error: {(st.get('print') or {}).get('message')}")
    temps = st.get("temperatures") or {}
    for name, t in temps.items():
        temp, target = t.get("temperature"), t.get("target")
        if temp is None:
            block(f"{name} has no temperature reading")
            continue
        if (target or 0) == 0 and not (5 <= temp <= 50) and name in ("extruder", "heater_bed"):
            warn(f"{name} reads {temp:.1f}C while off: implausible for idle (thermistor/wiring?)")
    try:
        store = await ctx.client(printer).temperature_store()
        for heater in ("extruder", "heater_bed"):
            series = store.get(heater)
            if not series:
                continue
            a = thermal.analyse(
                heater,
                series.get("temperatures", []),
                series.get("targets", []),
                series.get("powers"),
            )
            if a.verdict in ("fault_suspected", "unstable"):
                warn(f"{heater}: " + "; ".join(a.findings))
        checks["temperatures"] = "ok" if not warnings else "see warnings"
    except MoonrakerError as err:
        warn(f"temperature history unavailable: {err}", "info")
    for name, d in (st.get("drivers") or {}).items():
        bad = [f for f in d.get("flags", []) if f in ("ot", "s2ga", "s2gb", "s2vsa", "s2vsb", "uv_cp", "ola", "olb")]
        if bad:
            block(f"{name} driver reports {', '.join(bad)}")
    for name, present in (st.get("filament_sensors") or {}).items():
        if present is False:
            block(f"{name}: no filament detected", "warning")
    conf = st.get("config") or {}
    if conf.get("save_config_pending"):
        warn("SAVE_CONFIG pending: calibration results are not yet saved to printer.cfg")
    for w in conf.get("warnings", []) or []:
        warn(f"Klipper config warning: {w.get('message', w) if isinstance(w, dict) else w}")
    gaps = Gaps()
    srcs = await service.config_sources(ctx, printer, gaps)
    if "file" in srcs:
        cfg = klipper_config.parse(srcs["file"])
        findings = klipper_config.validate(cfg, expected_mcu_serial=printer.hardware.mcu.get("serial"))
        errors = [f for f in findings if f.severity == "error"]
        dangers = [f for f in findings if f.severity == "danger"]
        for f in errors:
            block(f"config: {f.message}", "critical")
        for f in dangers:
            warn(f"config safety: {f.message}", "safety")
        checks["config_valid"] = "ok" if not errors else "fail"
        if "loaded" in srcs:
            changes = klipper_config.semantic_diff(klipper_config.parse(srcs["loaded"]), cfg)
            if changes:
                warn(
                    f"printer.cfg on disk differs from the running config in {len(changes)} place(s); a "
                    "restart will load them (see printer_config_drift)"
                )
        if cfg.probe_section() is not None:
            probe = st.get("probe") or {}
            if probe and probe.get("last_query") is None:
                recs.append(
                    "Probe state never queried this session; QUERY_PROBE (printer_probe_query) is a no-motion check"
                )
    for g in gaps.to_list():
        warn(f"could not read {g['source']}: {g['reason']}", "info")
    try:
        du = await ctx.client(printer).directory("gcodes")
        free = (du.get("disk_usage") or {}).get("free")
        if free is not None:
            mb = free / 1e6
            checks["storage_free_mb"] = f"{mb:.0f}"
            if mb < 50:
                block(f"only {mb:.0f} MB free for G-code files")
            elif mb < 300:
                warn(f"only {mb:.0f} MB free for G-code files")
    except MoonrakerError as err:
        warn(f"disk usage unavailable: {err}", "info")
    host = st.get("host") or {}
    if (host.get("memavail") or 1e12) < 100_000:
        warn(f"host memory low ({host.get('memavail')} kB available)")
    last_jobs = [j for j in ctx.store.jobs(printer.id, limit=5)]
    if last_jobs and last_jobs[0]["status"] in ("error", "klippy_shutdown"):
        warn(
            f"the most recent job ({last_jobs[0]['job_id']}) ended '{last_jobs[0]['status']}' and nothing has "
            "printed since; consider printer_what_happened first"
        )
    homed = (st.get("toolhead") or {}).get("homed_axes") or ""
    checks["homed_axes"] = homed or "none (start G-code is expected to home)"
    return {
        "printer": printer.id,
        "ready": not blocking,
        "blocking": blocking,
        "warnings": warnings,
        "recommendations": recs,
        "checks": checks,
        "observed_at": iso(st["observed_at"]),
        "data_gaps": st.get("data_gaps", []),
    }


# ======================================================================
# Symptom workflows
# ======================================================================

TOPICS: dict[str, tuple[str, ...]] = {
    # Phrases that ask for a post-mortem of a print, whatever the subsystem.
    "failure": (
        "why did",
        "what happened",
        "stopped",
        "shutdown",
        "shut down",
        "died",
        "crash",
        "failed at",
        "last print",
    ),
    "probe": ("probe", "bltouch", "3dtouch", "3d touch", "z offset", "z_offset", "home z", "g28", "homing z"),
    "homing": ("home", "homing", "endstop"),
    "thermal": ("temp", "heater", "thermal", "thermistor", "pid", "heating", "runaway"),
    "mcu": ("mcu", "disconnect", "lost communication", "usb", "timer too close", "serial"),
    "first_layer": ("first layer", "adhesion", "level", "mesh", "squish", "elephant", "not sticking"),
}
TOPIC_CLASSES = {
    "probe": ("PROBE.", "MOTION.homing_failure"),
    "homing": ("MOTION.", "PROBE."),
    "thermal": ("THERMAL.",),
    "mcu": ("FIRMWARE.mcu", "NETWORK.host_failure", "POWER."),
    "first_layer": ("BED.", "PROBE.probe_offset", "PROBE.probe_inconsistent"),
}
_PROBE_ACCURACY_RE = re.compile(
    r"probe accuracy results: maximum (?P<max>[-\d.]+), minimum (?P<min>[-\d.]+), "
    r"range (?P<range>[-\d.]+), average (?P<avg>[-\d.]+), median (?P<med>[-\d.]+), "
    r"standard deviation (?P<std>[-\d.]+)"
)


def topic_of(symptom: str) -> str:
    """Route a symptom to a workflow: post-mortem phrasing first, then the most
    specific subsystem, then a bare "fail" falls back to the post-mortem."""
    s = symptom.lower()
    for topic in ("failure", "probe", "mcu", "thermal", "first_layer", "homing"):
        if any(k in s for k in TOPICS[topic]):
            return topic
    if "fail" in s:
        return "failure"
    return "general"


async def diagnose_symptom(ctx: Context, printer: Printer, symptom: str) -> dict[str, Any]:
    topic = topic_of(symptom)
    if topic == "failure":
        return await what_happened(ctx, printer, which="last_failed" if "fail" in symptom.lower() else "last")
    d = Diagnosis(printer.id, f"{symptom} (workflow: {topic})")
    st = await service.status(ctx, printer)
    for g in st.get("data_gaps", []):
        d.gaps.items.append(g)
    d.context["current_state"] = {k: st.get(k) for k in ("klippy_state", "state_message")}
    srcs = await service.config_sources(ctx, printer, d.gaps)
    cfg = klipper_config.parse(srcs["file"]) if "file" in srcs else None
    log = await service.klippy(ctx, printer, d.gaps, live_offset=st.get("live_offset"))
    prefixes = TOPIC_CLASSES.get(topic, ())
    occurrences = []
    if log is not None:
        for s in log.sessions:
            for ev in s.events:
                if ev.failure_class and ev.failure_class.startswith(prefixes):
                    occurrences.append(ev)
    if occurrences and log is not None:
        d.timeline.extend(
            Evidence(
                e.statement or e.text,
                Certainty.OBSERVED,
                f"klippy.log line {e.line_no}",
                e.wall,
                e.approximate,
            )
            for e in occurrences[-15:]
        )
        by_class: dict[str, int] = {}
        for e in occurrences:
            by_class[e.failure_class or "?"] = by_class.get(e.failure_class or "?", 0) + 1
        d.context["occurrences_in_retained_log"] = by_class
        n_sessions = sum(1 for s in log.sessions if any(e in occurrences for e in s.events))
        d.context["intermittency"] = f"seen in {n_sessions} of {len(log.sessions)} Klipper sessions in the retained log"
    elif log is not None:
        d.unknowns.append(
            f"no {topic}-related errors in the retained klippy.log (~5 days); the problem may be "
            "older, or not one Klipper reports as an error"
        )
    hyps: list[Hypothesis] = []
    if topic in ("probe", "homing"):
        hyps = await _probe_homing_workflow(ctx, d, printer, cfg, st, occurrences)
    elif topic == "thermal":
        hyps = await _thermal_workflow(ctx, d, printer, cfg)
    elif topic == "mcu":
        hyps = _mcu_workflow(ctx, d, printer, log, occurrences, st)
    elif topic == "first_layer":
        hyps = await _first_layer_workflow(ctx, d, printer, cfg, log)
    else:
        d.context["readiness"] = await readiness(ctx, printer)
        d.unknowns.append("symptom did not match a specific workflow; returned readiness and recent events")
    d.hypotheses = _rank(hyps)
    if cfg is not None:
        await _recent_changes(ctx, d, printer, topic)
    return _finish(ctx, d, d.subject)


async def _probe_homing_workflow(
    ctx: Context,
    d: Diagnosis,
    printer: Printer,
    cfg: klipper_config.KlipperConfig | None,
    st: dict[str, Any],
    occurrences: list[klippy_log.LogEvent],
) -> list[Hypothesis]:
    sigs = {s.id: s for s in ctx.taxonomy.signatures}
    seen = [e.signature for e in occurrences if e.signature]
    if seen:
        dominant = max(set(seen), key=seen.count)
        hyps = _hypotheses_from_signature(sigs[dominant], {})
        d.proximate.append(
            Evidence(
                f"most frequent related error: {sigs[dominant].statement} ({seen.count(dominant)}x in retained log)",
                Certainty.OBSERVED,
                "klippy.log",
            )
        )
    else:
        hyps = _hypotheses_from_signature(sigs["probe_no_trigger"], {})
        for h in hyps:
            h.score *= 0.5
    if cfg is not None:
        probe = cfg.probe_section()
        d.context["probe_config"] = {k: v.value for k, v in probe.options.items()} if probe else None
        d.context["z_homing"] = cfg.value("stepper_z", "endstop_pin")
        d.context["safe_z_home"] = cfg.to_dict().get("safe_z_home")
        for f in klipper_config.validate(cfg, expected_mcu_serial=printer.hardware.mcu.get("serial")):
            if f.section in (
                "bltouch",
                "probe",
                "safe_z_home",
                "stepper_z",
                "stepper_x",
                "stepper_y",
                "bed_mesh",
            ) and f.severity in ("error", "warning", "danger"):
                _bump(
                    hyps,
                    "PROBE.probe_configuration",
                    0.2,
                    Evidence(f.message, Certainty.OBSERVED, f"config validation ({f.code})"),
                )
        _compare_probe_with_fleet(ctx, d, hyps, printer, cfg)
    if st.get("klippy_state") == "ready" and (st.get("print") or {}).get("state") not in (
        "printing",
        "paused",
    ):
        try:
            endstops = await ctx.client(printer).query_endstops()
            d.context["endstops_now"] = endstops
            d.timeline.append(
                Evidence(
                    f"QUERY_ENDSTOPS now: {endstops}",
                    Certainty.OBSERVED,
                    "/printer/query_endstops/status (no motion)",
                    ctx.clock.now(),
                )
            )
            for axis, state in endstops.items():
                if state == "TRIGGERED" and axis in ("x", "y"):
                    _bump(
                        hyps,
                        "MOTION.endstop_configuration",
                        0.3,
                        Evidence(
                            f"{axis} endstop reports TRIGGERED now; if the carriage is not resting on the switch the "
                            "logic is inverted or the switch is stuck",
                            Certainty.OBSERVED,
                            "QUERY_ENDSTOPS",
                        ),
                    )
        except MoonrakerError as err:
            d.gaps.add("query_endstops", err)
    probe_state = st.get("probe") or {}
    if probe_state.get("last_query") is not None:
        d.context["probe_last_query"] = probe_state
    d.recommendations.append(
        "QUERY_PROBE (printer_probe_query, no motion) with the pin stowed should report 'open'. TRIGGERED at "
        "rest points to probe mode settings or wiring, not to homing logic."
    )
    return hyps


async def _thermal_workflow(
    ctx: Context, d: Diagnosis, printer: Printer, cfg: klipper_config.KlipperConfig | None
) -> list[Hypothesis]:
    hyps = [
        Hypothesis(
            "THERMAL.temperature_instability",
            "PID tuning or airflow",
            Certainty.POSSIBLE,
            0.2,
            next_test="PID_CALIBRATE at the printing temperature (heats hardware)",
            next_test_risk="HIGH_RISK_WRITE",
        ),
        Hypothesis(
            "THERMAL.thermistor_failure",
            "intermittent thermistor",
            Certainty.POSSIBLE,
            0.15,
            next_test="Watch live temperature with heaters off while flexing the cable",
            next_test_risk="READ_ONLY",
        ),
        Hypothesis(
            "THERMAL.heater_failure",
            "heater not delivering expected power",
            Certainty.POSSIBLE,
            0.15,
            next_test="Check the heating rate from cold against previous heat-ups",
            next_test_risk="READ_ONLY",
        ),
    ]
    try:
        store = await ctx.client(printer).temperature_store()
    except MoonrakerError as err:
        d.gaps.add("temperature_store", err)
        return hyps
    analyses = {}
    for heater in ("extruder", "heater_bed"):
        series = store.get(heater)
        if not series:
            continue
        a = thermal.analyse(heater, series.get("temperatures", []), series.get("targets", []), series.get("powers"))
        analyses[heater] = a.to_dict()
        src = f"temperature_store ({heater}, last {a.samples} s)"
        if a.verdict == "stable":
            for cls in (
                "THERMAL.temperature_instability",
                "THERMAL.heater_failure",
                "THERMAL.thermistor_failure",
            ):
                _bump(
                    hyps,
                    cls,
                    -0.1,
                    Evidence(f"{heater} stable at target: {a.stats}", Certainty.OBSERVED, src),
                    against=True,
                )
        for f in a.findings:
            ev = Evidence(f"{heater}: {f}", Certainty.OBSERVED, src, data=a.stats)
            if "jumps" in f:
                _bump(hyps, "THERMAL.thermistor_failure", 0.45, ev)
            elif "oscillating" in f:
                _bump(hyps, "THERMAL.temperature_instability", 0.45, ev)
            elif "without the temperature rising" in f or "average power" in f:
                _bump(hyps, "THERMAL.heater_failure", 0.35, ev)
            else:
                _bump(hyps, "THERMAL.temperature_instability", 0.2, ev)
        if a.verdict in ("idle", "insufficient_data"):
            d.unknowns.append(f"{heater} is not currently heating; stability can only be judged while at a target")
    d.context["analysis"] = analyses
    if cfg is not None:
        d.context["pid"] = {
            h: {k: cfg.value(h, k) for k in ("control", "pid_kp", "pid_ki", "pid_kd")}
            for h in ("extruder", "heater_bed")
        }
        for finding in klipper_config.validate(cfg):
            if finding.code.startswith("verify_heater"):
                d.proximate.append(Evidence(finding.message, Certainty.OBSERVED, "config validation"))
    return hyps


def _mcu_workflow(
    ctx: Context,
    d: Diagnosis,
    printer: Printer,
    log: klippy_log.KlippyLog | None,
    occurrences: list[klippy_log.LogEvent],
    st: dict[str, Any],
) -> list[Hypothesis]:
    sigs = {s.id: s for s in ctx.taxonomy.signatures}
    hyps = _hypotheses_from_signature(sigs["lost_comm"], {"mcu": "mcu"})
    if log is not None and log.sessions:
        s = log.sessions[-1]
        trend = klippy_log.link_trend(s)
        if trend:
            d.context["mcu_link_now"] = trend
            if trend["retransmit_bytes"] > 100:
                _bump(
                    hyps,
                    "FIRMWARE.mcu_disconnect",
                    0.25,
                    Evidence(
                        f"ongoing retransmits: +{trend['retransmit_bytes']:g} bytes in {trend['window_s']} s",
                        Certainty.OBSERVED,
                        "klippy.log Stats",
                    ),
                )
            else:
                d.timeline.append(
                    Evidence(
                        f"MCU link currently clean ({trend})",
                        Certainty.OBSERVED,
                        "klippy.log Stats",
                    )
                )
    if occurrences:
        d.proximate.append(
            Evidence(
                f"{len(occurrences)} MCU/timing events in the retained log",
                Certainty.OBSERVED,
                "klippy.log",
            )
        )
    for n in (st.get("kubernetes") or {}).get("observations", []):
        _bump(hyps, "NETWORK.host_failure", 0.3, Evidence(n, Certainty.OBSERVED, "kubernetes"))
    return hyps


async def _first_layer_workflow(
    ctx: Context,
    d: Diagnosis,
    printer: Printer,
    cfg: klipper_config.KlipperConfig | None,
    log: klippy_log.KlippyLog | None,
) -> list[Hypothesis]:
    hyps = [
        Hypothesis(
            "BED.leveling",
            "bed out of tram (mesh compensating a large tilt)",
            Certainty.POSSIBLE,
            0.2,
            next_test="SCREWS_TILT_CALCULATE (moves the toolhead and probes)",
            next_test_risk="HIGH_RISK_WRITE",
        ),
        Hypothesis(
            "PROBE.probe_offset",
            "z_offset wrong for the current nozzle/bed",
            Certainty.POSSIBLE,
            0.2,
            next_test="PROBE_CALIBRATE + paper test (moves, needs operator)",
            next_test_risk="HIGH_RISK_WRITE",
        ),
        Hypothesis(
            "BED.mesh",
            "mesh stale or not applied",
            Certainty.POSSIBLE,
            0.15,
            next_test="Check the start G-code loads/calibrates a mesh (printer_gcode_inspect)",
        ),
        Hypothesis(
            "PROBE.probe_inconsistent",
            "probe repeatability poor",
            Certainty.POSSIBLE,
            0.15,
            next_test="PROBE_ACCURACY (moves Z)",
            next_test_risk="HIGH_RISK_WRITE",
        ),
        Hypothesis(
            "BED.adhesion",
            "surface prep / temperature / slicer first-layer settings",
            Certainty.POSSIBLE,
            0.15,
            next_test="Inspect the last G-code's first-layer settings",
        ),
    ]
    if cfg is None:
        return hyps
    pts = klipper_config.bed_mesh_points(cfg)
    if pts:
        flat = [v for row in pts for v in row]
        rng = max(flat) - min(flat)
        # Average left-to-right slope across rows: a consistent slope is tilt
        # (fixable with screws), not warp.
        slopes = [row[-1] - row[0] for row in pts if len(row) > 1]
        avg_slope = sum(slopes) / len(slopes) if slopes else 0.0
        cols = list(zip(*pts, strict=False))
        fb = [c[-1] - c[0] for c in cols if len(c) > 1]
        avg_fb = sum(fb) / len(fb) if fb else 0.0
        d.context["bed_mesh"] = {
            "range_mm": round(rng, 3),
            "x_slope_mm": round(avg_slope, 3),
            "y_slope_mm": round(avg_fb, 3),
            "points": pts,
        }
        src = "SAVE_CONFIG [bed_mesh default]"
        if rng > 0.5:
            tilt = max(abs(avg_slope), abs(avg_fb))
            if tilt > 0.6 * rng:
                _bump(
                    hyps,
                    "BED.leveling",
                    0.45,
                    Evidence(
                        f"saved mesh spans {rng:.2f} mm and is dominated by a consistent tilt "
                        f"(X {avg_slope:+.2f} mm, Y {avg_fb:+.2f} mm across the mesh): the mesh is compensating a bed "
                        "that is out of tram",
                        Certainty.OBSERVED,
                        src,
                    ),
                )
            else:
                _bump(
                    hyps,
                    "BED.warped_bed",
                    0.3,
                    Evidence(
                        f"saved mesh spans {rng:.2f} mm without a dominant tilt: surface warp",
                        Certainty.OBSERVED,
                        src,
                    ),
                )
        else:
            _bump(
                hyps,
                "BED.leveling",
                -0.1,
                Evidence(f"saved mesh range {rng:.2f} mm is small", Certainty.OBSERVED, src),
                against=True,
            )
    else:
        _bump(
            hyps,
            "BED.mesh",
            0.25,
            Evidence("no saved default bed mesh", Certainty.OBSERVED, "SAVE_CONFIG block"),
        )
    probe = cfg.probe_section()
    if probe:
        d.context["z_offset"] = probe.get("z_offset")
    if log is not None:
        accs = [
            (m, line_no)
            for sess in log.sessions
            for line_no, _t, text in sess.notes
            if (m := _PROBE_ACCURACY_RE.search(text)) is not None
        ]
        if accs:
            m, line_no = accs[-1]
            rng = float(m.group("range"))
            ev = Evidence(
                f"last PROBE_ACCURACY: range {rng} mm, std {m.group('std')} mm",
                Certainty.OBSERVED,
                f"klippy.log line {line_no}",
            )
            _bump(
                hyps,
                "PROBE.probe_inconsistent",
                0.35 if rng > 0.025 else -0.1,
                ev,
                against=rng <= 0.025,
            )
    try:
        jobs = await ctx.client(printer).history_list(limit=1)
        if jobs:
            from printer_agent import gcode as gcode_mod

            data = await ctx.client(printer).download(
                "gcodes", jobs[0]["filename"], max_bytes=ctx.settings.max_gcode_bytes
            )
            rep = gcode_mod.inspect(data.decode("utf-8", "replace"), cfg)
            sc = rep.slicer_config
            d.context["last_gcode_first_layer"] = {
                k: sc.get(k)
                for k in (
                    "first_layer_height",
                    "first_layer_temperature",
                    "first_layer_bed_temperature",
                    "first_layer_speed",
                    "z_offset",
                    "first_layer_extrusion_width",
                    "filament_type",
                )
            }
            d.context["last_gcode_mesh_handling"] = [o.text for o in rep.mesh_ops]
            for f in rep.findings:
                if f.get("failure_class", "").startswith(("SLICER", "BED")):
                    d.timeline.append(Evidence(f["message"], Certainty.OBSERVED, f"G-code {jobs[0]['filename']}"))
    except (MoonrakerError, KeyError) as err:
        d.gaps.add("last G-code file", err)
    return hyps


async def _recent_changes(ctx: Context, d: Diagnosis, printer: Printer, topic: str) -> None:
    events = ctx.store.config_events(printer.id, "loaded", limit=10)
    if len(events) >= 2:
        newer = ctx.store.config_blob(events[0]["sha"])
        older = ctx.store.config_blob(events[1]["sha"])
        if newer and older:
            changes = klipper_config.semantic_diff(
                klipper_config.parse(older["content"]), klipper_config.parse(newer["content"])
            )
            d.context["last_loaded_config_change"] = {
                "at": iso(events[0]["ts"]),
                "changes": [c.to_dict() for c in changes][:30],
            }
    else:
        d.unknowns.append("fewer than two loaded-config snapshots recorded; config history is not yet available")
