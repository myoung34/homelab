from __future__ import annotations

import pytest
from conftest import MakeCtx
from sim import scenario

from printer_agent import operations
from printer_agent.safety import PolicyDeniedError, PreconditionFailedError, RiskLevel


async def test_policy_denies_and_audits(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    ctx = make_ctx(sim, max_risk=RiskLevel.SAFE_AUTOMATION)
    with pytest.raises(PolicyDeniedError):
        await operations.home(ctx, ctx.printer("enderbig"))
    entry = ctx.store.audit("enderbig")[0]
    assert entry["action"] == "home" and entry["outcome"] == "denied"
    assert sim.calls == []  # denied before anything reached the printer


async def test_per_printer_policy_is_also_enforced(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("healthy"))
    ctx.printer("enderbig").policy.max_risk = RiskLevel.LOW_RISK_WRITE
    with pytest.raises(PolicyDeniedError):
        await operations.set_temperature(ctx, ctx.printer("enderbig"), "extruder", 200)
    # turning a heater OFF is LOW_RISK and still allowed
    res = await operations.set_temperature(ctx, ctx.printer("enderbig"), "extruder", 0)
    assert res["ok"] and res["verified"]


async def test_restart_verified(make_ctx: MakeCtx) -> None:
    sim = scenario("mcu_disconnected")
    sim.print_state = "error"
    ctx = make_ctx(sim)
    res = await operations.restart(ctx, ctx.printer("enderbig"), firmware=True)
    assert res["ok"] and res["verified"], res
    assert sim.klippy_state == "ready"
    outcomes = [a["outcome"] for a in ctx.store.audit("enderbig")]
    assert outcomes[:2] == ["verified", "requested"]


async def test_restart_not_observed_is_not_claimed(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    sim.restart_ignored = True
    ctx = make_ctx(sim)
    res = await operations.restart(ctx, ctx.printer("enderbig"))
    assert res["ok"] and not res["verified"]
    assert "no restart was observed" in res["message"]


async def test_restart_failure_reported(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    sim.files["config"]["printer.cfg"] = b"[printer]\nkinematics: cartesian\n"
    ctx = make_ctx(sim)
    res = await operations.restart(ctx, ctx.printer("enderbig"))
    assert not res["ok"] and "did not become ready" in res["message"]


async def test_refuses_while_printing(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("printing"))
    for coro in (
        operations.restart(ctx, ctx.printer("enderbig")),
        operations.home(ctx, ctx.printer("enderbig")),
        operations.set_temperature(ctx, ctx.printer("enderbig"), "extruder", 0),
        operations.probe_query(ctx, ctx.printer("enderbig")),
    ):
        with pytest.raises(PreconditionFailedError):
            await coro
    assert all(a["outcome"] in ("requested", "precondition_failed") for a in ctx.store.audit("enderbig"))


async def test_home_success_and_failure(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    ctx = make_ctx(sim)
    res = await operations.home(ctx, ctx.printer("enderbig"), "xy")
    assert res["verified"] and sim.homed_axes == "xy"
    sim.home_fails_with = "No trigger on z after full movement"
    res = await operations.home(ctx, ctx.printer("enderbig"), "z")
    assert not res["ok"] and "diagnostic evidence" in res["message"]
    with pytest.raises(PreconditionFailedError):
        await operations.home(ctx, ctx.printer("enderbig"), "xa")


async def test_temperature_limits(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("healthy"))
    p = ctx.printer("enderbig")
    with pytest.raises(PreconditionFailedError, match="exceeds the allowed limit"):
        await operations.set_temperature(ctx, p, "extruder", 290)  # policy cap 260
    with pytest.raises(PreconditionFailedError, match="not a heater"):
        await operations.set_temperature(ctx, p, "fan", 50)
    res = await operations.set_temperature(ctx, p, "heater_bed", 60)
    assert res["verified"] and "not yet verified" in res["message"]  # never claims temp reached


async def test_print_lifecycle(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    sim.files["gcodes"]["ok.gcode"] = b"G28\nM109 S200\nG1 X10 Y10 E1\n"
    sim.files["gcodes"]["bad.gcode"] = b"G28\nG1 X10 Y10 E1\nM109 S200\nG1 X999 Y10 E1\n"
    ctx = make_ctx(sim)
    p = ctx.printer("enderbig")
    with pytest.raises(PreconditionFailedError, match="error-level findings"):
        await operations.start_print(ctx, p, "bad.gcode")
    with pytest.raises(PreconditionFailedError, match="not found"):
        await operations.start_print(ctx, p, "missing.gcode")
    res = await operations.start_print(ctx, p, "ok.gcode")
    assert res["verified"] and sim.print_state == "printing"
    assert (await operations.pause(ctx, p))["verified"] and sim.print_state == "paused"
    assert (await operations.resume(ctx, p))["verified"]
    assert (await operations.cancel(ctx, p))["verified"] and sim.print_state == "cancelled"
    with pytest.raises(PreconditionFailedError):
        await operations.pause(ctx, p)


async def test_start_refused_when_not_ready(make_ctx: MakeCtx) -> None:
    sim = scenario("mcu_disconnected")
    sim.files["gcodes"]["ok.gcode"] = b"G28\n"
    ctx = make_ctx(sim)
    with pytest.raises(PreconditionFailedError, match="not ready"):
        await operations.start_print(ctx, ctx.printer("enderbig"), "ok.gcode")


async def test_emergency_stop_and_probe_query(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    sim.probe_triggered = True
    ctx = make_ctx(sim)
    res = await operations.probe_query(ctx, ctx.printer("enderbig"))
    assert res["triggered"] is True and "TRIGGERED" in res["message"]
    res = await operations.emergency_stop(ctx, ctx.printer("enderbig"))
    assert res["verified"] and sim.klippy_state == "shutdown"
