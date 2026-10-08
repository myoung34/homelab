"""MCP tool surface.

Narrow, composable tools. Read tools never change printer state. Write tools
are listed in WRITE_TOOLS; the homelab Agent resource puts every one of them
in `requireApproval`, and the server enforces its own risk policy on top.

Errors are returned as structured results (`ok: false`, `error_kind`), never
as invented data.
"""

from __future__ import annotations

import difflib
import functools
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent, TextContent, ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from printer_agent import (
    calibration,
    diagnostics,
    klipper_config,
    metrics,
    operations,
    remediation,
    service,
    thermal,
)
from printer_agent import gcode as gcode_mod
from printer_agent.evidence import iso
from printer_agent.gitrepo import GitError
from printer_agent.inventory import Printer, UnknownPrinterError
from printer_agent.kube import KubeError
from printer_agent.moonraker import FileTooLargeError, MoonrakerError, MoonrakerUnreachableError
from printer_agent.safety import PolicyDeniedError, PreconditionFailedError
from printer_agent.service import Context, Gaps

logger = logging.getLogger(__name__)

PrinterArg = Annotated[str, Field(description="Printer id from printer_list (e.g. 'enderbig')")]
ConfigSource = Annotated[
    str,
    Field(
        description=(
            "'file' (printer.cfg on the printer's disk), 'loaded' (what Klipper is running), 'seed' (Git ConfigMap "
            "at main), 'git:<ref>' (seed at a commit/branch), 'snapshot:<sha>' (recorded by the agent), or "
            "'known_good' (loaded config of the last successful print)"
        )
    ),
]

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
SAFE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)

WRITE_TOOLS = (
    "printer_restart",
    "printer_print_pause",
    "printer_print_resume",
    "printer_print_cancel",
    "printer_print_start",
    "printer_home",
    "printer_set_temperature",
    "printer_emergency_stop",
    "printer_config_apply",
    "printer_config_open_pr",
)


class EditModel(BaseModel):
    section: str = Field(description="Section name exactly as in printer.cfg, e.g. 'bltouch' or 'tmc2209 extruder'")
    option: str = Field(description="Option name, e.g. 'z_offset'")
    value: str | None = Field(description="New single-line value, or null to remove the option")


def _err(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error_kind": kind, "error": message, **extra}


def build_server(ctx: Context) -> MCPServer:
    server = MCPServer(
        name="printer-agent",
        instructions=(
            "Tools for operating Klipper printers through Moonraker. Read tools are free to use and never change "
            "printer state. Results carry certainty levels (OBSERVED/INFERRED/LIKELY/POSSIBLE/UNKNOWN) and "
            "data_gaps - repeat them honestly. Write tools need human approval and verify their own outcome."
        ),
        version="0.1.0",
    )

    def tool(name: str, annotations: ToolAnnotations) -> Callable[[Callable[..., Awaitable[Any]]], Any]:
        def deco(fn: Callable[..., Awaitable[Any]]) -> Any:
            @functools.wraps(fn)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                t0 = time.monotonic()
                outcome = "ok"
                try:
                    res = await fn(*args, **kwargs)
                    if isinstance(res, dict) and res.get("ok") is False:
                        outcome = "failed"
                    return res
                except UnknownPrinterError as err:
                    outcome = "error"
                    return _err("unknown_printer", str(err))
                except PolicyDeniedError as err:
                    outcome = "denied"
                    return _err("policy_denied", err.reason, risk=err.risk.name, allowed=err.allowed.name)
                except PreconditionFailedError as err:
                    outcome = "precondition_failed"
                    return _err("precondition_failed", err.reason, details=err.details)
                except MoonrakerUnreachableError as err:
                    outcome = "error"
                    return _err(
                        "printer_unreachable",
                        str(err),
                        hint="printer_status includes Kubernetes pod state that explains why",
                    )
                except FileTooLargeError as err:
                    outcome = "error"
                    return _err("file_too_large", str(err))
                except MoonrakerError as err:
                    outcome = "error"
                    return _err("moonraker_error", str(err))
                except GitError as err:
                    outcome = "error"
                    return _err("git_error", str(err))
                except KubeError as err:
                    outcome = "error"
                    return _err("kubernetes_error", str(err))
                except Exception as err:
                    outcome = "error"
                    logger.exception("tool %s crashed", name)
                    return _err("internal_error", f"{type(err).__name__}: {err}")
                finally:
                    metrics.TOOL_CALLS.labels(name, outcome).inc()
                    metrics.TOOL_DURATION.labels(name).observe(time.monotonic() - t0)

            server.add_tool(wrapper, name=name, description=(fn.__doc__ or "").strip(), annotations=annotations)
            return fn

        return deco

    def P(printer: str) -> Printer:
        return ctx.printer(printer)

    # ================================================================ READ

    @tool("printer_list", READ)
    async def printer_list() -> dict[str, Any]:
        """List printers from the inventory with live reachability and Klipper state."""
        out = []
        for p in ctx.inventory.printers:
            entry: dict[str, Any] = {
                "id": p.id,
                "name": p.name,
                "model": p.model,
                "enabled": p.enabled,
                "board": p.hardware.board,
                "probe": p.hardware.probe,
                "capabilities": p.capabilities.model_dump(),
                "policy_max_risk": min(ctx.policy.max_risk, p.policy.max_risk).name,
            }
            if p.enabled:
                try:
                    info = await ctx.client(p).server_info()
                    entry["klippy_state"] = info.get("klippy_state")
                except MoonrakerError as err:
                    entry["klippy_state"] = "unreachable"
                    entry["error"] = str(err)[:200]
            out.append(entry)
        return {"printers": out, "server_max_risk": ctx.policy.max_risk.name}

    @tool("printer_status", READ)
    async def printer_status(printer: PrinterArg, include_raw_objects: bool = False) -> dict[str, Any]:
        """Live state: Klipper/Moonraker state, print progress, temperatures, toolhead/homing, MCUs, probe,
        fans, filament sensors, TMC driver flags, pending SAVE_CONFIG, host load. Temperatures are marked
        stale when Klipper is not ready. When Moonraker is unreachable, includes Kubernetes pod state."""
        st = await service.status(ctx, P(printer))
        if not include_raw_objects:
            st.pop("objects", None)
        st["observed_at_iso"] = iso(st["observed_at"])
        return st

    @tool("printer_readiness", READ)
    async def printer_readiness(printer: PrinterArg) -> dict[str, Any]:
        """Is the printer ready to print? Returns {ready, blocking[], warnings[], recommendations[], checks}."""
        return await diagnostics.readiness(ctx, P(printer))

    @tool("printer_temperatures", READ)
    async def printer_temperatures(printer: PrinterArg) -> dict[str, Any]:
        """Analyse the last ~20 minutes of heater data (1 Hz): stability at target, oscillation, power headroom,
        impossible jumps (thermistor), failure to heat."""
        p = P(printer)
        store = await ctx.client(p).temperature_store()
        out = {}
        for name, series in store.items():
            if "targets" not in series:
                temps = [t for t in series.get("temperatures", []) if t is not None]
                out[name] = {
                    "latest": temps[-1] if temps else None,
                    "min": min(temps) if temps else None,
                    "max": max(temps) if temps else None,
                }
                continue
            out[name] = thermal.analyse(
                name,
                series.get("temperatures", []),
                series.get("targets", []),
                series.get("powers"),
            ).to_dict()
        return {
            "printer": p.id,
            "window_s": max((len(s.get("temperatures", [])) for s in store.values()), default=0),
            "sensors": out,
        }

    @tool("printer_logs", READ)
    async def printer_logs(
        printer: PrinterArg,
        source: Literal["klippy", "moonraker"] = "klippy",
        mode: Literal["events", "raw"] = "events",
        grep: Annotated[str | None, Field(description="Regex filter for raw mode")] = None,
        lines: Annotated[int, Field(ge=1, le=2000)] = 200,
        filename: Annotated[str | None, Field(description="Rotated log name, e.g. klippy.log.2026-10-07")] = None,
    ) -> dict[str, Any]:
        """Klipper or Moonraker logs. mode=events parses klippy.log into sessions (start time, version),
        classified errors/shutdowns with wall-clock times, calibration output and the G-code dump before a
        shutdown. mode=raw returns the last N (optionally grep-filtered) lines."""
        p = P(printer)
        gaps = Gaps()
        if source == "moonraker":
            raw = await service.moonraker_log_tail(ctx, p, gaps)
            if mode == "events":
                return {
                    "printer": p.id,
                    "events": service.moonraker_events(raw)[-lines:],
                    "data_gaps": gaps.to_list(),
                }
            return {
                "printer": p.id,
                "lines": _filter(raw, grep)[-lines:],
                "data_gaps": gaps.to_list(),
            }
        if mode == "raw":
            data, truncated = await ctx.client(p).download_tail("logs", filename or "klippy.log", 2_000_000)
            raw = data.decode("utf-8", "replace").splitlines()
            raw = [ln for ln in raw if not ln.startswith("Stats ")] if not grep else raw
            return {
                "printer": p.id,
                "file": filename or "klippy.log",
                "truncated": truncated,
                "note": "Stats lines omitted unless grep is used" if not grep else None,
                "lines": _filter(raw, grep)[-lines:],
            }
        st = await service.status(ctx, p)
        log = await service.klippy(ctx, p, gaps, live_offset=st.get("live_offset"), filename=filename or "klippy.log")
        if log is None:
            return {"printer": p.id, "data_gaps": gaps.to_list()}
        sessions = []
        for s in log.sessions[-8:]:
            sessions.append(
                {
                    "started": iso(s.start_wall) if s.start_wall else None,
                    "time_anchor": s.anchored_by,
                    "klipper_version": s.version,
                    "events": [
                        {
                            "time": iso(e.wall) if e.wall else None,
                            "approximate_time": e.approximate,
                            "kind": e.kind,
                            "class": e.failure_class,
                            "statement": e.statement or e.text[:200],
                            "line": e.line_no,
                        }
                        for e in s.events
                    ][-40:],
                    "notes": [{"line": n, "text": t[:200]} for n, _, t in s.notes][-15:],
                    "gcode_before_shutdown": [g for _, g in s.gcode_dump][-15:] if s.shutdown else None,
                    "stats_samples": len(s.stats),
                }
            )
        return {
            "printer": p.id,
            "truncated_head": log.truncated,
            "sessions": sessions,
            "data_gaps": gaps.to_list(),
        }

    @tool("printer_gcode_console", READ)
    async def printer_gcode_console(
        printer: PrinterArg, count: Annotated[int, Field(ge=1, le=500)] = 50
    ) -> dict[str, Any]:
        """Recent G-code commands and Klipper responses (Fluidd console history) with timestamps; errors start
        with '!!'."""
        p = P(printer)
        items = await ctx.client(p).gcode_store(count=count)
        return {
            "printer": p.id,
            "entries": [
                {
                    "time": iso(float(g["time"])),
                    "type": g.get("type"),
                    "message": str(g.get("message"))[:300],
                }
                for g in items
            ],
        }

    @tool("printer_print_history", READ)
    async def printer_print_history(
        printer: PrinterArg,
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
        status: Annotated[
            str | None,
            Field(
                description="Filter: completed, cancelled, error, klippy_shutdown, "
                "klippy_disconnect, interrupted, in_progress"
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Print jobs from Moonraker history (newest first) with status, duration and filament."""
        p = P(printer)
        jobs = await ctx.client(p).history_list(limit=200 if status else limit)
        for j in jobs:
            ctx.store.record_job(p.id, j)
        if status:
            jobs = [j for j in jobs if j.get("status") == status][:limit]
        return {"printer": p.id, "jobs": [diagnostics._job_summary(j) for j in jobs]}

    @tool("printer_classify_failures", READ)
    async def printer_classify_failures(
        printer: PrinterArg, limit: Annotated[int, Field(ge=1, le=50)] = 10
    ) -> dict[str, Any]:
        """The last N failed/cancelled jobs, each classified (taxonomy class + domain) from klippy.log evidence."""
        return await diagnostics.classify_history(ctx, P(printer), limit)

    @tool("printer_what_happened", READ)
    async def printer_what_happened(
        printer: PrinterArg,
        job_id: Annotated[str | None, Field(description="Moonraker job id; default chooses by 'which'")] = None,
        which: Literal["last", "last_failed"] = "last",
    ) -> dict[str, Any]:
        """Explain a print outcome. Gathers job metadata, klippy.log (incl. rotated), Moonraker log, G-code
        console, temperature traces, MCU link stats, pod restarts, config at job start, config changes and Git
        commits since the last successful print; builds a timeline; reports the proximate cause (OBSERVED) and
        ranked root-cause hypotheses with evidence for/against and the least-invasive next test."""
        res = await diagnostics.what_happened(ctx, P(printer), job_id=job_id, which=which)
        metrics.DIAGNOSES.labels(printer, res["classification"]["failure_class"]).inc()
        return res

    @tool("printer_diagnose", READ)
    async def printer_diagnose(
        printer: PrinterArg,
        symptom: Annotated[
            str,
            Field(
                description="The symptom in the operator's words, e.g. 'G28 fails "
                "intermittently' or 'first layer is bad'"
            ),
        ],
    ) -> dict[str, Any]:
        """Symptom-driven diagnosis (probe/homing, thermal, MCU/connection, first layer, or 'why did it fail').
        Collects topic-specific evidence (log history/intermittency, config validation, fleet comparison,
        QUERY_ENDSTOPS, temperature analysis, mesh shape) and ranks hypotheses. Changes nothing."""
        res = await diagnostics.diagnose_symptom(ctx, P(printer), symptom)
        metrics.DIAGNOSES.labels(printer, res["classification"]["failure_class"]).inc()
        return res

    async def _config_text(p: Printer, source: str) -> tuple[str, str]:
        if source == "file":
            return await service.live_config_text(ctx, p), "printer.cfg on the printer (includes inlined)"
        if source == "loaded":
            return await service.loaded_config_text(ctx, p), "running config (Klipper configfile)"
        if source == "seed":
            return await service.seed_config_text(ctx, p), f"Git seed {p.git.path if p.git else ''} @ main"
        if source.startswith("git:"):
            ref = source[4:]
            return await service.seed_config_text(ctx, p, ref), f"Git seed @ {ref}"
        if source.startswith("snapshot:"):
            blob = ctx.store.config_blob(source[9:])
            if blob is None:
                raise PreconditionFailedError(f"no unique snapshot matching {source[9:]!r}")
            return blob["content"], f"agent snapshot {blob['sha'][:12]}"
        if source == "known_good":
            good = next(
                (j for j in ctx.store.jobs(p.id, 500) if j["status"] == "completed" and j.get("loaded_sha")),
                None,
            )
            if good is None:
                raise PreconditionFailedError("no completed job with a recorded config yet (known-good unknown)")
            blob = ctx.store.config_blob(good["loaded_sha"])
            assert blob is not None
            return blob["content"], f"loaded config of last successful job {good['job_id']}"
        raise PreconditionFailedError(f"unknown config source {source!r}")

    @tool("printer_config_get", READ)
    async def printer_config_get(
        printer: PrinterArg,
        source: ConfigSource = "file",
        section: Annotated[str | None, Field(description="Only this section (effective values)")] = None,
    ) -> dict[str, Any]:
        """Retrieve configuration text (or one section's effective values) from a named source."""
        p = P(printer)
        text, desc = await _config_text(p, source)
        if section:
            cfg = klipper_config.parse(text)
            sec = cfg.section(section)
            if sec is None:
                return _err("not_found", f"no [{section}] in {desc}", sections=sorted(cfg.effective)[:80])
            return {
                "printer": p.id,
                "source": desc,
                "section": section,
                "line": sec.line,
                "options": {
                    k: {"value": o.value, "line": o.line, "from_save_config": o.autosave}
                    for k, o in sec.options.items()
                },
            }
        return {"printer": p.id, "source": desc, "sha256": service.digest(text)[:12], "text": text}

    @tool("printer_config_explain", READ)
    async def printer_config_explain(printer: PrinterArg, source: ConfigSource = "file") -> dict[str, Any]:
        """Semantic summary of a config: kinematics, travel, probe and Z-homing method, offsets, macros, each
        section's purpose, SAVE_CONFIG overrides, and dependencies between sections."""
        p = P(printer)
        text, desc = await _config_text(p, source)
        return {
            "printer": p.id,
            "source": desc,
            **klipper_config.explain(klipper_config.parse(text)),
        }

    @tool("printer_config_validate", READ)
    async def printer_config_validate(
        printer: PrinterArg,
        source: ConfigSource = "file",
        text: Annotated[str | None, Field(description="Validate this text instead of a source")] = None,
    ) -> dict[str, Any]:
        """Static validation: missing/invalid options, pin conflicts, probe/mesh/safe_z_home reachability,
        disabled thermal protection, MCU serial vs inventory, UI prerequisites. Klipper's own startup check
        is authoritative; this catches problems before a restart."""
        p = P(printer)
        desc = "provided text"
        if text is None:
            text, desc = await _config_text(p, source)
        findings = klipper_config.validate(klipper_config.parse(text), expected_mcu_serial=p.hardware.mcu.get("serial"))
        order = {"error": 0, "danger": 1, "warning": 2, "info": 3}
        findings.sort(key=lambda f: order.get(f.severity, 9))
        return {
            "printer": p.id,
            "source": desc,
            "valid": not any(f.severity == "error" for f in findings),
            "counts": {s: sum(1 for f in findings if f.severity == s) for s in order},
            "findings": [f.to_dict() for f in findings],
        }

    @tool("printer_config_diff", READ)
    async def printer_config_diff(
        printer: PrinterArg,
        base: ConfigSource,
        head: ConfigSource = "file",
        include_text_diff: bool = False,
    ) -> dict[str, Any]:
        """Semantic diff between two config sources with each change risk-classified (e.g. probe pin, max_temp,
        verify_heater, rotation_distance are DANGEROUS)."""
        p = P(printer)
        a, da = await _config_text(p, base)
        b, db = await _config_text(p, head)
        ignore: list[tuple[str, str]] = []
        changes = klipper_config.semantic_diff(klipper_config.parse(a), klipper_config.parse(b), ignore=ignore)
        out: dict[str, Any] = {
            "printer": p.id,
            "base": da,
            "head": db,
            "identical": not changes,
            "max_risk": klipper_config.max_risk(changes).name,
            "changes": [c.to_dict() for c in changes],
        }
        if include_text_diff:
            out["text_diff"] = "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), base, head))[:20000]
        return out

    @tool("printer_config_drift", READ)
    async def printer_config_drift(printer: PrinterArg) -> dict[str, Any]:
        """Compare the three configs that exist for a printer: the Git seed (ConfigMap), the on-disk file (PVC,
        edited by SAVE_CONFIG/Fluidd), and what Klipper is running. Explains which differences matter."""
        p = P(printer)
        gaps = Gaps()
        srcs = await service.config_sources(ctx, p, gaps)
        parsed = {k: klipper_config.parse(v) for k, v in srcs.items()}
        out: dict[str, Any] = {
            "printer": p.id,
            "sources_read": sorted(srcs),
            "data_gaps": gaps.to_list(),
        }
        if "file" in parsed and "loaded" in parsed:
            ch = klipper_config.semantic_diff(parsed["loaded"], parsed["file"])
            out["file_vs_running"] = {
                "meaning": "edits on disk that Klipper has not loaded yet; a RESTART applies them",
                "changes": [c.to_dict() for c in ch],
            }
        if "seed" in parsed and "file" in parsed:
            ch = klipper_config.semantic_diff(parsed["seed"], parsed["file"])
            auto = [c for c in ch if c.autosave]
            manual = [c for c in ch if not c.autosave]
            out["seed_vs_file"] = {
                "meaning": "the Git ConfigMap is only a first-boot seed; differences here mean Git no longer "
                "describes the printer. Calibration values (SAVE_CONFIG block) are expected to "
                "diverge unless synced back deliberately",
                "calibration_differences": [c.to_dict() for c in auto],
                "configuration_differences": [c.to_dict() for c in manual],
            }
        return out

    @tool("printer_config_history", READ)
    async def printer_config_history(
        printer: PrinterArg, limit: Annotated[int, Field(ge=1, le=100)] = 20
    ) -> dict[str, Any]:
        """Recorded config versions (on-disk and loaded) over time joined with job outcomes: which config was
        running for each print, the known-good (last success) and known-bad (configs with failures)."""
        p = P(printer)
        loaded = ctx.store.config_events(p.id, "loaded", limit)
        files = ctx.store.config_events(p.id, "file", limit)
        jobs = ctx.store.jobs(p.id, 200)
        by_sha: dict[str, dict[str, int]] = {}
        for j in jobs:
            if j.get("loaded_sha"):
                by_sha.setdefault(j["loaded_sha"], {}).setdefault(j["status"], 0)
                by_sha[j["loaded_sha"]][j["status"]] += 1
        good = next((j for j in jobs if j["status"] == "completed" and j.get("loaded_sha")), None)
        bad = sorted(
            {j["loaded_sha"] for j in jobs if j.get("loaded_sha") and j["status"] in ("error", "klippy_shutdown")}
        )
        return {
            "printer": p.id,
            "loaded_versions": [
                {
                    "sha": e["sha"][:12],
                    "since": iso(e["ts"]),
                    "source": e["source"],
                    "job_outcomes": by_sha.get(e["sha"], {}),
                }
                for e in loaded
            ],
            "file_versions": [{"sha": e["sha"][:12], "since": iso(e["ts"]), "source": e["source"]} for e in files],
            "known_good": {"sha": good["loaded_sha"][:12], "job_id": good["job_id"]} if good else None,
            "known_bad": [s[:12] for s in bad],
            "jobs_without_config_record": sum(1 for j in jobs if not j.get("loaded_sha")),
            "note": "history starts when the agent first ran (plus ~5 days backfilled from klippy.log)",
        }

    @tool("printer_compare", READ)
    async def printer_compare(
        printer_a: PrinterArg, printer_b: PrinterArg, source: ConfigSource = "file"
    ) -> dict[str, Any]:
        """Compare two printers: semantic config diff (risk-classified, MCU serial ignored), validation of each,
        and job outcome totals. Useful when 'identical' printers behave differently."""
        pa, pb = P(printer_a), P(printer_b)
        ta, _ = await _config_text(pa, source)
        tb, _ = await _config_text(pb, source)
        ca, cb = klipper_config.parse(ta), klipper_config.parse(tb)
        changes = klipper_config.semantic_diff(ca, cb, ignore=[("mcu", "serial")])
        groups: dict[str, list[dict[str, Any]]] = {}
        for c in changes:
            groups.setdefault(c.section.split()[0], []).append(c.to_dict())

        def outcomes(p: Printer) -> dict[str, int]:
            out: dict[str, int] = {}
            for j in ctx.store.jobs(p.id, 200):
                out[j["status"]] = out.get(j["status"], 0) + 1
            return out

        return {
            "a": pa.id,
            "b": pb.id,
            "source": source,
            "differences_by_section": groups,
            "validation": {
                pa.id: [f.to_dict() for f in klipper_config.validate(ca) if f.severity != "info"],
                pb.id: [f.to_dict() for f in klipper_config.validate(cb) if f.severity != "info"],
            },
            "job_outcomes": {pa.id: outcomes(pa), pb.id: outcomes(pb)},
            "hardware": {pa.id: pa.hardware.model_dump(), pb.id: pb.hardware.model_dump()},
        }

    @tool("printer_gcode_inspect", READ)
    async def printer_gcode_inspect(
        printer: PrinterArg,
        filename: Annotated[str | None, Field(description="Path in the gcodes root")] = None,
        job_id: Annotated[str | None, Field(description="Inspect the file of this history job")] = None,
        text: Annotated[str | None, Field(description="G-code text pasted by the operator")] = None,
    ) -> dict[str, Any]:
        """Static G-code analysis against this printer's running config: homing count and source (incl. macros),
        bed mesh handling (e.g. invalid BED_MESH_CALIBRATE params), temperature order, unknown/Marlin-only
        commands, move bounds vs travel limits, temperatures vs max_temp, slicer profile settings. Never
        executes anything. Defaults to the most recent job's file."""
        p = P(printer)
        client = ctx.client(p)
        if text is None:
            if job_id:
                filename = (await client.history_job(job_id)).get("filename")
            if not filename:
                jobs = await client.history_list(limit=1)
                if not jobs:
                    return _err("not_found", "no file given and no print history")
                filename = jobs[0]["filename"]
            assert filename is not None
            text = (await client.download("gcodes", filename, max_bytes=ctx.settings.max_gcode_bytes)).decode(
                "utf-8", "replace"
            )
        gaps = Gaps()
        cfg = None
        try:
            cfg = klipper_config.parse(await service.loaded_config_text(ctx, p))
        except MoonrakerError as err:
            gaps.add("loaded config", err)
        rep = gcode_mod.inspect(text, cfg)
        return {
            "printer": p.id,
            "file": filename or "(pasted)",
            **rep.to_dict(),
            "data_gaps": gaps.to_list(),
            "cross_checked_against_config": cfg is not None,
        }

    @tool("printer_git_log", READ)
    async def printer_git_log(
        printer: Annotated[str | None, Field(description="Limit to this printer's seed ConfigMap")] = None,
        path: Annotated[str | None, Field(description="Repo path (must be under an allowed prefix)")] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
        since: Annotated[str | None, Field(description="git --since value, e.g. '2 weeks ago' or a date")] = None,
    ) -> dict[str, Any]:
        """Commit history of the homelab repo for printer-related paths (read-only clone of main)."""
        if ctx.git is None:
            return _err("git_disabled", "git integration is not configured")
        if printer and not path:
            pr = P(printer)
            path = pr.git.path if pr.git else None
        commits = await ctx.git.log(path, limit=limit, since=since)
        return {
            "status": await ctx.git.status(),
            "path": path or list(ctx.git.allowed),
            "commits": [c.to_dict(with_body=True) for c in commits],
        }

    @tool("printer_git_show", READ)
    async def printer_git_show(sha: str) -> dict[str, Any]:
        """One commit's message and diff (restricted to printer-related paths)."""
        if ctx.git is None:
            return _err("git_disabled", "git integration is not configured")
        return await ctx.git.show(sha)

    @tool("printer_git_diff", READ)
    async def printer_git_diff(base: str, head: str | None = None, path: str | None = None) -> dict[str, Any]:
        """git diff between two refs (default head: main) for printer-related paths."""
        if ctx.git is None:
            return _err("git_disabled", "git integration is not configured")
        return {
            "base": base,
            "head": head or ctx.git.branch,
            "diff": await ctx.git.diff(base, head, path),
        }

    @tool("printer_git_blame", READ)
    async def printer_git_blame(
        printer: PrinterArg,
        section: Annotated[str | None, Field(description="Blame the lines of this config section")] = None,
        start: int = 1,
        end: int | None = None,
    ) -> dict[str, Any]:
        """Who changed which lines of a printer's seed ConfigMap, and in which commit."""
        if ctx.git is None:
            return _err("git_disabled", "git integration is not configured")
        p = P(printer)
        if p.git is None:
            return _err("not_configured", f"{p.id} has no git seed path")
        if section:
            manifest = await ctx.git.file_at(p.git.path)
            idx = next(
                (i for i, ln in enumerate(manifest.splitlines(), 1) if ln.strip() == f"[{section}]"),
                None,
            )
            if idx is None:
                return _err("not_found", f"[{section}] not found in {p.git.path}")
            lines = manifest.splitlines()
            # idx is the 1-based header line; scan 0-based indexes after it for
            # the next section header (0-based j == line j + 1).
            start = idx
            end = next(
                (j for j in range(idx, len(lines)) if lines[j].strip().startswith("[")),
                min(len(lines), idx + 60),
            )
        return {"path": p.git.path, "lines": await ctx.git.blame(p.git.path, start=start, end=end)}

    @tool("printer_calibration", READ)
    async def printer_calibration(printer: PrinterArg) -> dict[str, Any]:
        """Calibration state (PID, Z offset, probe accuracy, bed mesh, bed tram, rotation distance, pressure
        advance, input shaper, flow/retraction/temperature) with evidence, plus a ranked, reasoned list of what
        to calibrate next. Detects values copied from another printer."""
        return await calibration.status(ctx, P(printer))

    @tool("printer_taxonomy", READ)
    async def printer_taxonomy() -> dict[str, Any]:
        """The failure taxonomy: categories, classes with their domain (configuration / hardware / electrical /
        mechanical / firmware / slicer / operator / network / power) and the log signatures that map to them."""
        return ctx.taxonomy.to_dict()

    @tool("printer_endstops", READ)
    async def printer_endstops(printer: PrinterArg) -> dict[str, Any]:
        """Current endstop states (QUERY_ENDSTOPS via Moonraker; no motion)."""
        p = P(printer)
        return {
            "printer": p.id,
            "endstops": await ctx.client(p).query_endstops(),
            "observed_at": iso(ctx.clock.now()),
        }

    @tool("printer_camera_snapshot", READ)
    async def printer_camera_snapshot(
        printer: PrinterArg,
    ) -> list[TextContent | ImageContent] | dict[str, Any]:
        """Current camera image, if a webcam is configured in Moonraker. Visual inferences from it are
        INFERRED at best and must not be reported as confirmed printer state."""
        import base64

        p = P(printer)
        cams = await ctx.client(p).webcams_list()
        if not cams:
            return _err(
                "no_camera",
                f"{p.id} has no webcam configured in Moonraker; the inventory says camera={p.capabilities.camera}",
            )
        cam = next((c for c in cams if c.get("enabled", True)), cams[0])
        url = cam.get("snapshot_url") or ""
        if url.startswith("/"):
            url = p.klipper.moonraker_url.rstrip("/") + url
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(url)
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
            return _err("camera_error", f"snapshot {url} returned {r.status_code}")
        return [
            TextContent(
                type="text",
                text=f"{p.id} camera '{cam.get('name')}' at {iso(ctx.clock.now())}. "
                "Treat what you see as visual inference, not confirmed state.",
            ),
            ImageContent(
                type="image",
                data=base64.b64encode(r.content).decode(),
                mime_type=r.headers["content-type"].split(";")[0],
            ),
        ]

    @tool("printer_audit_log", READ)
    async def printer_audit_log(
        printer: str | None = None, limit: Annotated[int, Field(ge=1, le=200)] = 30
    ) -> dict[str, Any]:
        """Privileged action attempts (requested/denied/verified/failed) recorded by this server."""
        rows = ctx.store.audit(printer, limit)
        for r in rows:
            r["time"] = iso(r["ts"])
        return {"entries": rows}

    # ====================================================== SAFE_AUTOMATION

    @tool("printer_probe_query", SAFE)
    async def printer_probe_query(printer: PrinterArg) -> dict[str, Any]:
        """QUERY_PROBE: reports whether the probe reads TRIGGERED or open. No motion, no heating. Refused while
        printing."""
        return await operations.probe_query(ctx, P(printer))

    @tool("printer_config_propose", SAFE)
    async def printer_config_propose(
        printer: PrinterArg,
        edits: Annotated[list[EditModel], Field(description="Minimal option-level edits")],
        summary: Annotated[str, Field(description="Commit-style summary, e.g. 'correct bltouch sensor pin'")],
        rationale: Annotated[str, Field(description="Why this change fixes the diagnosed problem")],
        evidence: Annotated[list[str], Field(description="Observations supporting the change (with sources)")],
    ) -> dict[str, Any]:
        """Propose a configuration change. Produces a minimal diff of printer.cfg, validation (problems
        introduced/resolved), and a risk level computed from the semantic diff. Changes NOTHING on the printer;
        returns a proposal_id for printer_config_apply."""
        return await remediation.propose(
            ctx,
            P(printer),
            [e.model_dump() for e in edits],
            summary=summary,
            rationale=rationale,
            evidence=evidence,
        )

    # =============================================================== WRITE

    @tool("printer_restart", WRITE)
    async def printer_restart(printer: PrinterArg, firmware: bool = False) -> dict[str, Any]:
        """[approval] RESTART (host; reloads printer.cfg) or FIRMWARE_RESTART (also resets MCUs). Refused while
        printing. Verifies Klipper actually restarted and is ready."""
        return await operations.restart(ctx, P(printer), firmware=firmware)

    @tool("printer_print_pause", WRITE)
    async def printer_print_pause(printer: PrinterArg) -> dict[str, Any]:
        """[approval] Pause the current print; verifies print_stats becomes 'paused'."""
        return await operations.pause(ctx, P(printer))

    @tool("printer_print_resume", WRITE)
    async def printer_print_resume(printer: PrinterArg) -> dict[str, Any]:
        """[approval] Resume a paused print; verifies print_stats becomes 'printing'."""
        return await operations.resume(ctx, P(printer))

    @tool("printer_print_cancel", WRITE)
    async def printer_print_cancel(printer: PrinterArg) -> dict[str, Any]:
        """[approval] Cancel the current print; verifies the print is no longer active."""
        return await operations.cancel(ctx, P(printer))

    @tool("printer_print_start", WRITE)
    async def printer_print_start(
        printer: PrinterArg, filename: str, acknowledge_findings: bool = False
    ) -> dict[str, Any]:
        """[approval] Start printing a file. Requires readiness to pass and the G-code inspection to show no
        error-level findings (unless acknowledged). Verifies the printer enters 'printing' with that file."""
        return await operations.start_print(ctx, P(printer), filename, acknowledge_findings=acknowledge_findings)

    @tool("printer_home", WRITE)
    async def printer_home(
        printer: PrinterArg, axes: Annotated[str, Field(description="Subset of 'xyz'")] = "xyz"
    ) -> dict[str, Any]:
        """[approval] Home axes (PHYSICAL MOTION). Refused while printing or if Klipper is not ready. Verifies
        homed_axes. A homing failure is returned as diagnostic evidence."""
        return await operations.home(ctx, P(printer), axes)

    @tool("printer_set_temperature", WRITE)
    async def printer_set_temperature(
        printer: PrinterArg,
        heater: Annotated[str, Field(description="'extruder', 'heater_bed', or a heater_generic section name")],
        target: Annotated[float, Field(ge=0)],
    ) -> dict[str, Any]:
        """[approval] Set a heater target (0 = off). Capped by printers.yaml policy and config max_temp - 10C.
        Refused while printing. Verifies the target was accepted; does not claim the temperature was reached."""
        return await operations.set_temperature(ctx, P(printer), heater, target)

    @tool("printer_emergency_stop", WRITE)
    async def printer_emergency_stop(printer: PrinterArg) -> dict[str, Any]:
        """[approval] Emergency stop (M112): Klipper shuts down, heaters and motors off, print lost. Verifies the
        shutdown state."""
        return await operations.emergency_stop(ctx, P(printer))

    @tool("printer_config_apply", WRITE)
    async def printer_config_apply(
        printer: PrinterArg,
        proposal_id: str,
        acknowledge_dangerous: Annotated[
            list[str] | None,
            Field(description="Every 'section/option' listed as dangerous in the proposal, acknowledged explicitly"),
        ] = None,
    ) -> dict[str, Any]:
        """[approval] Apply a proposal to the live printer: verify the file is unchanged since the proposal,
        printer idle, back up printer.cfg, upload, RESTART, verify the running config contains the change.
        Rolls back automatically if Klipper does not come back ready. No motion or heating."""
        return await remediation.apply(ctx, P(printer), proposal_id, acknowledge_dangerous=acknowledge_dangerous)

    @tool("printer_config_open_pr", WRITE)
    async def printer_config_open_pr(
        printer: PrinterArg, proposal_id: str, allow_unapplied: bool = False
    ) -> dict[str, Any]:
        """[approval] Open a pull request against the homelab repo applying the same edits to the printer's
        Git seed ConfigMap, with a descriptive commit message and the evidence. Never merges; Argo CD deploys
        only after the operator merges (and the seed only matters on re-seed)."""
        return await remediation.open_pr(ctx, P(printer), proposal_id, allow_unapplied=allow_unapplied)

    # ============================================================ HTTP

    @server.custom_route("/healthz", methods=["GET"])  # type: ignore[untyped-decorator]
    async def healthz(_: Request) -> Response:
        return JSONResponse({"ok": True, "printers": [p.id for p in ctx.inventory.enabled()]})

    @server.custom_route("/metrics", methods=["GET"])  # type: ignore[untyped-decorator]
    async def metrics_route(_: Request) -> Response:
        return Response(metrics.render(), media_type="text/plain; version=0.0.4")

    return server


def _filter(lines: list[str], grep: str | None) -> list[str]:
    if not grep:
        return lines
    try:
        rx = re.compile(grep, re.IGNORECASE)
    except re.error as err:
        raise PreconditionFailedError(f"invalid regex: {err}") from err
    return [ln for ln in lines if rx.search(ln)]
