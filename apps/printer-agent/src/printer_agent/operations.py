"""Controlled printer operations (phase 3).

Every operation: policy check -> audit -> preconditions -> execute ->
verify by reading the printer back -> audit outcome. A result is only
`verified: true` when the expected state was observed. Human approval
happens before the call reaches this server (kagent requireApproval).

Deliberately absent: arbitrary G-code, raw moves, firmware flashing, file or
history deletion.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from printer_agent import klipper_config, service
from printer_agent.inventory import Printer
from printer_agent.moonraker import MoonrakerAPIError, MoonrakerError
from printer_agent.safety import PolicyDeniedError, PreconditionFailedError, RiskLevel
from printer_agent.service import Context

logger = logging.getLogger(__name__)
_START_MARK = "Start printer at "


async def _sleep(seconds: float) -> None:
    """Indirection so tests can skip waits without patching asyncio globally."""
    await asyncio.sleep(seconds)


class Op:
    """Bookkeeping for one privileged operation."""

    def __init__(self, ctx: Context, printer: Printer, action: str, risk: RiskLevel, params: dict[str, Any]) -> None:
        self.ctx, self.printer, self.action, self.risk, self.params = (
            ctx,
            printer,
            action,
            risk,
            params,
        )

    def authorize(self) -> None:
        try:
            self.ctx.policy.authorize(
                action=self.action,
                printer_id=self.printer.id,
                risk=self.risk,
                printer_max=self.printer.policy.max_risk,
            )
        except PolicyDeniedError as err:
            self.audit("denied", err.reason)
            raise
        self.audit("requested")

    def audit(self, outcome: str, detail: str | None = None) -> None:
        self.ctx.auditor.record(
            action=self.action,
            printer_id=self.printer.id,
            risk=self.risk,
            outcome=outcome,
            params=self.params,
            detail=detail,
        )

    def result(self, *, ok: bool, verified: bool, message: str, **extra: Any) -> dict[str, Any]:
        self.audit("verified" if ok and verified else "executed_unverified" if ok else "failed", message)
        return {
            "printer": self.printer.id,
            "action": self.action,
            "risk": self.risk.name,
            "ok": ok,
            "verified": verified,
            "message": message,
            **extra,
        }


async def _objects(ctx: Context, printer: Printer, objs: dict[str, list[str] | None]) -> dict[str, Any]:
    res = await ctx.client(printer).query_objects(objs)
    return dict(res.get("status", {}))


async def _print_state(ctx: Context, printer: Printer) -> str | None:
    try:
        st = await _objects(ctx, printer, {"print_stats": ["state"]})
        state = st.get("print_stats", {}).get("state")
        return str(state) if state is not None else None
    except MoonrakerError:
        return None


async def _klippy_state(ctx: Context, printer: Printer) -> tuple[str, str | None]:
    info = await ctx.client(printer).server_info()
    state = str(info.get("klippy_state", "unknown"))
    msg = None
    with contextlib.suppress(MoonrakerError):
        msg = (await ctx.client(printer).printer_info()).get("state_message")
    return state, msg


async def poll(check: Callable[[], Awaitable[bool]], *, timeout: float, interval: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if await check():
                return True
        except MoonrakerError:
            pass
        if time.monotonic() >= deadline:
            return False
        await _sleep(interval)


async def _require_idle(ctx: Context, printer: Printer, op: Op) -> None:
    state = await _print_state(ctx, printer)
    if state in ("printing", "paused"):
        op.audit("precondition_failed", f"print is {state}")
        raise PreconditionFailedError(
            f"refusing {op.action}: a print is {state}; pause/cancel it first",
            {"print_state": state},
        )


async def _require_ready(ctx: Context, printer: Printer, op: Op) -> None:
    state, msg = await _klippy_state(ctx, printer)
    if state != "ready":
        op.audit("precondition_failed", f"klippy {state}")
        raise PreconditionFailedError(f"refusing {op.action}: Klipper is '{state}' ({msg})", {"klippy_state": state})


async def _last_start_line(ctx: Context, printer: Printer) -> str | None:
    try:
        data, _ = await ctx.client(printer).download_tail("logs", "klippy.log", 256_000)
    except MoonrakerError:
        return None
    lines = [ln for ln in data.decode("utf-8", "replace").splitlines() if ln.startswith(_START_MARK)]
    return lines[-1] if lines else None


# ------------------------------------------------------------------ ops


async def restart(ctx: Context, printer: Printer, *, firmware: bool = False, timeout: float = 90.0) -> dict[str, Any]:
    action = "firmware_restart" if firmware else "restart"
    op = Op(ctx, printer, action, RiskLevel.LOW_RISK_WRITE, {"firmware": firmware})
    op.authorize()
    await _require_idle(ctx, printer, op)
    before_state, before_msg = await _klippy_state(ctx, printer)
    before_start = await _last_start_line(ctx, printer)
    client = ctx.client(printer)
    try:
        await (client.firmware_restart() if firmware else client.restart())
    except MoonrakerAPIError as err:
        return op.result(ok=False, verified=False, message=f"Moonraker rejected {action}: {err}")
    saw_transition = False

    async def ready() -> bool:
        nonlocal saw_transition
        state, _ = await _klippy_state(ctx, printer)
        if state != "ready":
            saw_transition = True
            return False
        return True

    await _sleep(1.0)
    ok = await poll(ready, timeout=timeout)
    after_state, after_msg = await _klippy_state(ctx, printer)
    after_start = await _last_start_line(ctx, printer)
    restarted = saw_transition or (after_start is not None and after_start != before_start)
    if ok and restarted:
        return op.result(
            ok=True,
            verified=True,
            message=f"Klipper {action} completed and is ready (verified: new start in klippy.log or "
            "observed non-ready transition)",
            before={"state": before_state, "message": before_msg},
            after={"state": after_state, "start": after_start},
        )
    if ok:
        return op.result(
            ok=True,
            verified=False,
            message="Klipper reports ready, but no restart was observed (no state transition and no "
            "new 'Start printer' line); the restart may not have happened",
            after={"state": after_state},
        )
    return op.result(
        ok=False,
        verified=False,
        message=f"Klipper did not become ready within {timeout:g}s: state '{after_state}' ({after_msg})",
        after={"state": after_state, "message": after_msg},
    )


async def pause(ctx: Context, printer: Printer) -> dict[str, Any]:
    return await _print_transition(ctx, printer, "pause", RiskLevel.LOW_RISK_WRITE, ("printing",), ("paused",))


async def resume(ctx: Context, printer: Printer) -> dict[str, Any]:
    return await _print_transition(ctx, printer, "resume", RiskLevel.HIGH_RISK_WRITE, ("paused",), ("printing",))


async def cancel(ctx: Context, printer: Printer) -> dict[str, Any]:
    return await _print_transition(
        ctx,
        printer,
        "cancel",
        RiskLevel.HIGH_RISK_WRITE,
        ("printing", "paused"),
        ("cancelled", "standby", "complete"),
    )


async def _print_transition(
    ctx: Context,
    printer: Printer,
    action: str,
    risk: RiskLevel,
    from_states: tuple[str, ...],
    to_states: tuple[str, ...],
) -> dict[str, Any]:
    op = Op(ctx, printer, f"print_{action}", risk, {})
    op.authorize()
    state = await _print_state(ctx, printer)
    if state not in from_states:
        op.audit("precondition_failed", f"print state {state}")
        raise PreconditionFailedError(
            f"cannot {action}: print state is '{state}', expected one of {from_states}",
            {"print_state": state},
        )
    client = ctx.client(printer)
    call = {
        "pause": client.print_pause,
        "resume": client.print_resume,
        "cancel": client.print_cancel,
    }[action]
    try:
        await call()
    except MoonrakerAPIError as err:
        return op.result(ok=False, verified=False, message=f"Moonraker rejected {action}: {err}")

    async def reached() -> bool:
        return (await _print_state(ctx, printer)) in to_states

    ok = await poll(reached, timeout=60.0)
    after = await _print_state(ctx, printer)
    if ok:
        return op.result(
            ok=True,
            verified=True,
            message=f"print state is now '{after}'",
            before={"print_state": state},
            after={"print_state": after},
        )
    return op.result(
        ok=False,
        verified=False,
        message=f"requested {action} but print state is still '{after}' after 60s",
        before={"print_state": state},
        after={"print_state": after},
    )


async def home(ctx: Context, printer: Printer, axes: str = "xyz") -> dict[str, Any]:
    axes_norm = "".join(sorted(set(axes.lower()) & set("xyz"), key="xyz".index))
    if not axes_norm or len(axes_norm) != len(set(axes.lower())):
        raise PreconditionFailedError(f"axes must be a subset of 'xyz', got {axes!r}")
    op = Op(ctx, printer, "home", RiskLevel.HIGH_RISK_WRITE, {"axes": axes_norm})
    op.authorize()
    await _require_ready(ctx, printer, op)
    await _require_idle(ctx, printer, op)
    cmd = "G28" if axes_norm == "xyz" else "G28 " + " ".join(a.upper() for a in axes_norm)
    try:
        await ctx.client(printer).gcode_script(cmd, timeout=180.0)
    except MoonrakerAPIError as err:
        state, msg = await _klippy_state(ctx, printer)
        return op.result(
            ok=False,
            verified=False,
            message=f"{cmd} failed: {err.message}. Klipper is now '{state}'. This error is diagnostic "
            "evidence; run printer_diagnose before retrying.",
            klippy_state=state,
            state_message=msg,
        )
    th = (await _objects(ctx, printer, {"toolhead": ["homed_axes", "position"]})).get("toolhead", {})
    homed = th.get("homed_axes", "")
    if all(a in homed for a in axes_norm):
        return op.result(
            ok=True,
            verified=True,
            message=f"homed {axes_norm}; toolhead reports homed_axes='{homed}'",
            position=th.get("position"),
        )
    return op.result(
        ok=False,
        verified=False,
        message=f"{cmd} returned but homed_axes is '{homed}'",
        position=th.get("position"),
    )


async def set_temperature(ctx: Context, printer: Printer, heater: str, target: float) -> dict[str, Any]:
    if target < 0:
        raise PreconditionFailedError("target must be >= 0")
    risk = RiskLevel.LOW_RISK_WRITE if target == 0 else RiskLevel.HIGH_RISK_WRITE
    op = Op(ctx, printer, "set_temperature", risk, {"heater": heater, "target": target})
    op.authorize()
    await _require_ready(ctx, printer, op)
    await _require_idle(ctx, printer, op)
    cfg = klipper_config.parse(await service.loaded_config_text(ctx, printer))
    sec = cfg.section(heater)
    if sec is None or sec.type not in ("extruder", "heater_bed", "heater_generic"):
        op.audit("precondition_failed", f"unknown heater {heater}")
        raise PreconditionFailedError(f"{heater!r} is not a heater in this printer's config")
    max_temp = cfg.float_value(heater, "max_temp") or 0.0
    cap = printer.policy.max_extruder_temp if sec.type == "extruder" else printer.policy.max_bed_temp
    limit = min(cap, max_temp - 10.0)
    if target > limit:
        op.audit("precondition_failed", f"target {target} > limit {limit}")
        raise PreconditionFailedError(
            f"target {target:g}C exceeds the allowed limit {limit:g}C (min of printers.yaml policy cap {cap:g}C "
            f"and config max_temp {max_temp:g}C - 10C)"
        )
    name = sec.suffix if sec.type == "heater_generic" else heater
    try:
        await ctx.client(printer).gcode_script(f"SET_HEATER_TEMPERATURE HEATER={name} TARGET={target:g}")
    except MoonrakerAPIError as err:
        return op.result(ok=False, verified=False, message=f"rejected: {err.message}")
    obj = (await _objects(ctx, printer, {heater: ["target", "temperature"]})).get(heater, {})
    if abs(float(obj.get("target", -1)) - target) < 0.01:
        return op.result(
            ok=True,
            verified=True,
            message=f"{heater} target is {target:g}C (current {obj.get('temperature')}C). The target "
            "is set; reaching it is not yet verified - check printer_temperatures.",
            current=obj.get("temperature"),
        )
    return op.result(ok=False, verified=False, message=f"target reads {obj.get('target')} after setting {target}")


async def start_print(
    ctx: Context, printer: Printer, filename: str, *, acknowledge_findings: bool = False
) -> dict[str, Any]:
    from printer_agent import diagnostics
    from printer_agent import gcode as gcode_mod

    op = Op(ctx, printer, "print_start", RiskLevel.HIGH_RISK_WRITE, {"filename": filename})
    op.authorize()
    ready = await diagnostics.readiness(ctx, printer)
    if not ready["ready"]:
        op.audit("precondition_failed", "printer not ready")
        raise PreconditionFailedError("printer is not ready to print", {"blocking": ready["blocking"]})
    client = ctx.client(printer)
    try:
        await client.file_metadata(filename)
    except MoonrakerAPIError as err:
        op.audit("precondition_failed", f"file: {err}")
        raise PreconditionFailedError(f"file {filename!r} not found on the printer: {err.message}") from err
    data = await client.download("gcodes", filename, max_bytes=ctx.settings.max_gcode_bytes)
    cfg = klipper_config.parse(await service.loaded_config_text(ctx, printer))
    rep = gcode_mod.inspect(data.decode("utf-8", "replace"), cfg)
    errors = [f for f in rep.findings if f["severity"] == "error"]
    if errors and not acknowledge_findings:
        op.audit("precondition_failed", "gcode findings")
        raise PreconditionFailedError(
            "the G-code has error-level findings; review them and call again with "
            "acknowledge_findings=true to print anyway",
            {"findings": errors},
        )
    try:
        await client.print_start(filename)
    except MoonrakerAPIError as err:
        return op.result(ok=False, verified=False, message=f"Moonraker rejected print start: {err}")

    async def printing() -> bool:
        return (await _print_state(ctx, printer)) == "printing"

    ok = await poll(printing, timeout=30.0)
    st = await _objects(ctx, printer, {"print_stats": ["state", "filename"]})
    ps = st.get("print_stats", {})
    if ok and ps.get("filename") == filename:
        return op.result(
            ok=True,
            verified=True,
            message=f"printer is printing {filename}",
            acknowledged_findings=errors or None,
        )
    return op.result(
        ok=False,
        verified=False,
        message=f"print_stats is '{ps.get('state')}' / '{ps.get('filename')}' 30s after start",
    )


async def emergency_stop(ctx: Context, printer: Printer) -> dict[str, Any]:
    op = Op(ctx, printer, "emergency_stop", RiskLevel.LOW_RISK_WRITE, {})
    op.authorize()
    try:
        await ctx.client(printer).emergency_stop()
    except MoonrakerError as err:
        return op.result(
            ok=False,
            verified=False,
            message=f"emergency stop request failed: {err}. If the printer is in danger, cut power physically.",
        )

    async def shutdown() -> bool:
        return (await _klippy_state(ctx, printer))[0] == "shutdown"

    ok = await poll(shutdown, timeout=10.0, interval=0.5)
    return op.result(
        ok=ok,
        verified=ok,
        message="Klipper is in shutdown state (heaters and motors off)"
        if ok
        else "emergency stop sent but shutdown state not observed; check the printer physically",
    )


async def probe_query(ctx: Context, printer: Printer) -> dict[str, Any]:
    op = Op(ctx, printer, "probe_query", RiskLevel.SAFE_AUTOMATION, {})
    op.authorize()
    await _require_ready(ctx, printer, op)
    await _require_idle(ctx, printer, op)
    try:
        await ctx.client(printer).gcode_script("QUERY_PROBE")
    except MoonrakerAPIError as err:
        return op.result(ok=False, verified=False, message=f"QUERY_PROBE failed: {err.message}")
    probe = (await _objects(ctx, printer, {"probe": ["last_query", "name"]})).get("probe", {})
    triggered = probe.get("last_query")
    return op.result(
        ok=True,
        verified=triggered is not None,
        message=f"probe reports {'TRIGGERED' if triggered else 'open'} (no motion performed)",
        triggered=triggered,
        probe=probe.get("name"),
    )
