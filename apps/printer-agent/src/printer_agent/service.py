"""Shared runtime context and evidence gathering for one printer.

Every collector tolerates partial failure: a source that cannot be read is
recorded as a *data gap* (with the reason) instead of raising, so analyses
can say what they could not see.
"""

from __future__ import annotations

import fnmatch
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from printer_agent import klipper_config, klippy_log
from printer_agent.gitrepo import GitError, GitRepo
from printer_agent.inventory import Inventory, Printer
from printer_agent.kube import KubeError, KubeReader
from printer_agent.moonraker import (
    Clock,
    MoonrakerAPIError,
    MoonrakerClient,
    MoonrakerError,
    MoonrakerUnreachableError,
)
from printer_agent.safety import Auditor, Policy
from printer_agent.settings import Settings
from printer_agent.store import Store, sha256
from printer_agent.taxonomy import Taxonomy

logger = logging.getLogger(__name__)

STATUS_OBJECTS_BASE = (
    "webhooks",
    "print_stats",
    "virtual_sdcard",
    "toolhead",
    "extruder",
    "heater_bed",
    "idle_timeout",
    "pause_resume",
    "display_status",
    "motion_report",
    "fan",
    "system_stats",
    "bed_mesh",
    "probe",
    "bltouch",
    "mcu",
    "exclude_object",
    "gcode_move",
    "stepper_enable",
)
STATUS_OBJECT_PREFIXES = (
    "heater_fan ",
    "fan_generic ",
    "controller_fan ",
    "temperature_sensor ",
    "temperature_fan ",
    "filament_switch_sensor ",
    "filament_motion_sensor ",
    "tmc2209 ",
    "tmc2208 ",
    "tmc2130 ",
    "tmc5160 ",
    "tmc2240 ",
    "mcu ",
    "heater_generic ",
)
CONFIGFILE_FIELDS = ("config", "warnings", "save_config_pending", "save_config_pending_items")


@dataclass(slots=True)
class Gaps:
    items: list[dict[str, str]] = field(default_factory=list)

    def add(self, source: str, err: BaseException | str) -> None:
        self.items.append({"source": source, "reason": str(err)[:300]})

    def to_list(self) -> list[dict[str, str]]:
        return self.items


@dataclass(slots=True)
class Context:
    settings: Settings
    inventory: Inventory
    store: Store
    taxonomy: Taxonomy
    git: GitRepo | None
    kube: KubeReader | None
    policy: Policy
    auditor: Auditor
    clock: Clock
    clients: dict[str, MoonrakerClient] = field(default_factory=dict)

    def printer(self, printer_id: str) -> Printer:
        return self.inventory.get(printer_id)

    def client(self, printer: Printer) -> MoonrakerClient:
        c = self.clients.get(printer.id)
        if c is None:
            import os

            key = os.environ.get(printer.klipper.api_key_env) if printer.klipper.api_key_env else None
            c = MoonrakerClient(printer.klipper.moonraker_url, api_key=key, timeout=self.settings.http_timeout)
            self.clients[printer.id] = c
        return c

    async def aclose(self) -> None:
        for c in self.clients.values():
            await c.aclose()
        if self.kube is not None:
            await self.kube.aclose()


# ------------------------------------------------------------------ status


async def status(ctx: Context, printer: Printer) -> dict[str, Any]:
    """Live state with explicit staleness and data gaps."""
    client = ctx.client(printer)
    gaps = Gaps()
    observed_at = ctx.clock.now()
    out: dict[str, Any] = {"printer": printer.id, "observed_at": observed_at}
    try:
        info = await client.server_info()
    except MoonrakerUnreachableError as err:
        out.update({"moonraker": "unreachable", "klippy_state": "unknown", "error": str(err)})
        gaps.add("moonraker /server/info", err)
        out["kubernetes"] = await workload(ctx, printer, gaps)
        out["data_gaps"] = gaps.to_list()
        return out
    except MoonrakerError as err:
        out.update({"moonraker": "error", "klippy_state": "unknown", "error": str(err)})
        gaps.add("moonraker /server/info", err)
        out["data_gaps"] = gaps.to_list()
        return out
    out["moonraker"] = {
        "version": info.get("moonraker_version"),
        "klippy_connected": info.get("klippy_connected"),
        "warnings": info.get("warnings", []),
        "failed_components": info.get("failed_components", []),
    }
    out["klippy_state"] = info.get("klippy_state", "unknown")
    try:
        pinfo = await client.printer_info()
        out["state_message"] = pinfo.get("state_message")
        out["klipper_version"] = pinfo.get("software_version")
    except MoonrakerError as err:
        gaps.add("moonraker /printer/info", err)
    objects: dict[str, Any] = {}
    eventtime: float | None = None
    if out["klippy_state"] in ("ready", "shutdown", "startup"):
        try:
            available = set(await client.objects_list())
            wanted = [o for o in STATUS_OBJECTS_BASE if o in available]
            wanted += sorted(o for o in available if o.startswith(STATUS_OBJECT_PREFIXES))
            res = await client.query_objects(dict.fromkeys(wanted))
            objects = res.get("status", {})
            eventtime = res.get("eventtime")
            missing = [o for o in wanted if o not in objects]
            if missing:
                gaps.add("moonraker objects", f"objects not returned: {', '.join(missing)}")
            cf = await client.query_objects(
                {"configfile": ["warnings", "save_config_pending", "save_config_pending_items"]}
            )
            objects["configfile"] = cf.get("status", {}).get("configfile", {})
        except MoonrakerError as err:
            gaps.add("moonraker /printer/objects/query", err)
    out["live_offset"] = (observed_at - eventtime) if eventtime else None
    out.update(_summarize(objects, out["klippy_state"]))
    out["objects"] = objects
    if out["klippy_state"] != "ready":
        out["kubernetes"] = await workload(ctx, printer, gaps)
    out["data_gaps"] = gaps.to_list()
    return out


def _summarize(objs: dict[str, Any], klippy_state: str) -> dict[str, Any]:
    stale = klippy_state != "ready"
    s: dict[str, Any] = {}
    ps = objs.get("print_stats", {})
    if ps:
        s["print"] = {
            k: ps.get(k)
            for k in (
                "state",
                "filename",
                "print_duration",
                "total_duration",
                "filament_used",
                "message",
            )
        }
        info = ps.get("info") or {}
        if info.get("current_layer") is not None:
            s["print"]["layer"] = f"{info.get('current_layer')}/{info.get('total_layer')}"
    vsd = objs.get("virtual_sdcard", {})
    if vsd:
        s.setdefault("print", {})["progress"] = round(float(vsd.get("progress", 0)) * 100, 1)
    heaters = {}
    for name in ("extruder", "heater_bed"):
        h = objs.get(name)
        if h:
            heaters[name] = {
                "temperature": h.get("temperature"),
                "target": h.get("target"),
                "power": h.get("power"),
                "stale": stale,
            }
    for name, val in objs.items():
        if name.startswith(("temperature_sensor ", "heater_generic ", "temperature_fan ")):
            heaters[name] = {
                "temperature": val.get("temperature"),
                "target": val.get("target"),
                "stale": stale,
            }
    if heaters:
        s["temperatures"] = heaters
    th = objs.get("toolhead", {})
    if th:
        s["toolhead"] = {k: th.get(k) for k in ("homed_axes", "position", "max_velocity", "max_accel")}
    mcus = {}
    for name, val in objs.items():
        if name == "mcu" or name.startswith("mcu "):
            ls = val.get("last_stats", {})
            mcus[name] = {
                "version": val.get("mcu_version"),
                "retransmit_bytes": ls.get("bytes_retransmit"),
                "invalid_bytes": ls.get("bytes_invalid"),
                "srtt": ls.get("srtt"),
            }
    if mcus:
        s["mcus"] = mcus
    probe = objs.get("probe") or {}
    if probe:
        s["probe"] = {
            "last_query": probe.get("last_query"),
            "last_z_result": probe.get("last_z_result"),
            "name": probe.get("name"),
        }
    fans = {
        n: v.get("speed")
        for n, v in objs.items()
        if n == "fan" or n.startswith(("heater_fan ", "fan_generic ", "controller_fan "))
    }
    if fans:
        s["fans"] = fans
    sensors = {
        n: v.get("filament_detected")
        for n, v in objs.items()
        if n.startswith(("filament_switch_sensor ", "filament_motion_sensor "))
    }
    if sensors:
        s["filament_sensors"] = sensors
    tmc = {}
    for n, v in objs.items():
        if n.startswith("tmc"):
            drv = v.get("drv_status") or {}
            flags = [k for k, val in drv.items() if val and k not in ("cs_actual", "sg_result")]
            tmc[n] = {
                "run_current": v.get("run_current"),
                "flags": flags,
                "temperature": v.get("temperature"),
            }
    if tmc:
        s["drivers"] = tmc
    cf = objs.get("configfile") or {}
    if cf:
        s["config"] = {
            "save_config_pending": cf.get("save_config_pending"),
            "pending_items": cf.get("save_config_pending_items"),
            "warnings": cf.get("warnings", []),
        }
    sysst = objs.get("system_stats") or {}
    if sysst:
        s["host"] = {k: sysst.get(k) for k in ("sysload", "cputime", "memavail")}
    if objs.get("idle_timeout"):
        s["idle_state"] = objs["idle_timeout"].get("state")
    return s


async def workload(ctx: Context, printer: Printer, gaps: Gaps) -> dict[str, Any] | None:
    from printer_agent.kube import interpret

    if ctx.kube is None or printer.kubernetes is None:
        return None
    try:
        w = await ctx.kube.workload(printer.kubernetes.namespace, printer.kubernetes.selector)
    except KubeError as err:
        gaps.add("kubernetes", err)
        return None
    w["observations"] = interpret(w)
    return w


# ----------------------------------------------------------------- configs


async def live_config_text(ctx: Context, printer: Printer) -> str:
    """The on-disk printer.cfg with [include] files inlined."""
    client = ctx.client(printer)
    root_file = printer.klipper.config_file
    raw = (await client.download("config", root_file, max_bytes=2_000_000)).decode("utf-8", "replace")
    return await _inline_includes(client, raw, base_dir="", depth=0)


async def _inline_includes(client: MoonrakerClient, text: str, *, base_dir: str, depth: int) -> str:
    if "[include " not in text or depth > 4:
        return text
    listing: list[str] | None = None
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[include ") and stripped.endswith("]"):
            pattern = stripped[len("[include ") : -1].strip()
            path = f"{base_dir}/{pattern}".lstrip("/") if base_dir else pattern
            targets = [path]
            if any(ch in path for ch in "*?["):
                if listing is None:
                    listing = [f["path"] for f in await client.files_list("config")]
                targets = sorted(p for p in listing if fnmatch.fnmatch(p, path))
            out.append(f"# --- [include {pattern}] inlined by printer-agent ---")
            for t in targets:
                body = (await client.download("config", t, max_bytes=1_000_000)).decode("utf-8", "replace")
                sub_dir = t.rpartition("/")[0]
                out.append(await _inline_includes(client, body, base_dir=sub_dir, depth=depth + 1))
            continue
        out.append(line)
    return "\n".join(out) + "\n"


async def loaded_config_text(ctx: Context, printer: Printer) -> str:
    """The config Klipper is actually running (configfile.config), as cfg text."""
    res = await ctx.client(printer).query_objects({"configfile": ["config"]})
    config = res.get("status", {}).get("configfile", {}).get("config", {})
    if not config:
        raise MoonrakerAPIError(503, "configfile.config empty (Klipper not ready?)", "configfile")
    return canonical(config_dict_to_text(config))


def config_dict_to_text(config: dict[str, dict[str, str]]) -> str:
    lines: list[str] = []
    for section, opts in config.items():
        lines.append(f"[{section}]")
        for k, v in opts.items():
            v = str(v)
            if "\n" in v:
                first, *rest = v.split("\n")
                lines.append(f"{k}: {first}")
                lines.extend(f"  {r}" for r in rest)
            else:
                lines.append(f"{k}: {v}")
        lines.append("")
    return "\n".join(lines)


async def seed_config_text(ctx: Context, printer: Printer, ref: str | None = None) -> str:
    if ctx.git is None or printer.git is None:
        raise GitError("no git seed configured for this printer")
    return await ctx.git.seed_config(printer.git.path, printer.git.key, ref)


async def config_sources(ctx: Context, printer: Printer, gaps: Gaps) -> dict[str, str]:
    """file / loaded / seed config texts, each optional."""
    out: dict[str, str] = {}
    try:
        out["file"] = await live_config_text(ctx, printer)
    except MoonrakerError as err:
        gaps.add("live printer.cfg", err)
    try:
        out["loaded"] = await loaded_config_text(ctx, printer)
    except MoonrakerError as err:
        gaps.add("loaded config (configfile.config)", err)
    try:
        out["seed"] = await seed_config_text(ctx, printer)
    except GitError as err:
        gaps.add("git seed config", err)
    now = ctx.clock.now()
    for kind in ("file", "loaded"):
        if kind in out:
            ctx.store.record_config(printer.id, kind, out[kind], ts=now, source="read")
    return out


def parse_config(text: str) -> klipper_config.KlipperConfig:
    return klipper_config.parse(text)


# -------------------------------------------------------------------- logs


async def klippy(
    ctx: Context,
    printer: Printer,
    gaps: Gaps,
    *,
    max_bytes: int = 4_000_000,
    live_offset: float | None = None,
    filename: str = "klippy.log",
) -> klippy_log.KlippyLog | None:
    try:
        data, truncated = await ctx.client(printer).download_tail("logs", filename, max_bytes)
    except MoonrakerError as err:
        gaps.add(f"logs/{filename}", err)
        return None
    text = data.decode("utf-8", "replace")
    if truncated:
        # Drop the partial first line of a tail read.
        text = text.split("\n", 1)[1] if "\n" in text else ""
    log = klippy_log.parse(text, ctx.taxonomy, truncated=truncated, live_offset=live_offset)
    for s in log.sessions:
        if s.config_text and s.start_wall and s.anchored_by == "start_line":
            ctx.store.record_config(
                printer.id, "loaded", canonical(s.config_text), ts=s.start_wall, source="klippy.log"
            )
    return log


def canonical(config_text: str) -> str:
    """One text form for "the config Klipper loaded", whatever its source.

    configfile.config (live) and klippy.log dumps format values differently;
    both are normalized here so their hashes are comparable. Comments and
    line layout are not preserved - the on-disk file keeps those.
    """
    cfg = klipper_config.parse(config_text)
    return config_dict_to_text(cfg.to_dict())


async def log_files(ctx: Context, printer: Printer) -> list[dict[str, Any]]:
    files = await ctx.client(printer).files_list("logs")
    return sorted(files, key=lambda f: f.get("modified", 0), reverse=True)


async def moonraker_log_tail(ctx: Context, printer: Printer, gaps: Gaps, max_bytes: int = 500_000) -> list[str]:
    try:
        data, truncated = await ctx.client(printer).download_tail("logs", "moonraker.log", max_bytes)
    except MoonrakerError as err:
        gaps.add("logs/moonraker.log", err)
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    return lines[1:] if truncated else lines


def moonraker_events(lines: list[str]) -> list[dict[str, Any]]:
    """Notable Moonraker log lines with their wall-clock timestamps."""
    keys = (
        "Klippy Disconnected",
        "Klippy Connection Removed",
        "Klippy Connection Established",
        "Klippy ready",
        "Klippy has disconnected",
        "Job State Changed",
        "Error",
        "error",
        "Unable to",
        "Server Shutdown",
        "Starting Moonraker",
        "Webcam",
        "Exception",
        "timed out",
        "Changes to klippy",
    )
    out = []
    for line in lines:
        if not any(k in line for k in keys):
            continue
        ts = _moonraker_ts(line)
        out.append({"time": ts, "line": line[:300]})
    return out[-200:]


def _moonraker_ts(line: str) -> float | None:
    # "2026-10-08 14:30:00,123 [file.py:func()] - message"
    if len(line) < 23 or line[4] != "-" or line[10] != " ":
        return None
    try:
        return time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None


def digest(text: str) -> str:
    return sha256(text)
