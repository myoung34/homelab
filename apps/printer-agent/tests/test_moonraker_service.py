from __future__ import annotations

import httpx
import pytest
from conftest import MakeCtx
from sim import OfflineTransport, SimPrinter, scenario

from printer_agent import service
from printer_agent.moonraker import (
    FileTooLargeError,
    MoonrakerAPIError,
    MoonrakerClient,
    MoonrakerUnreachableError,
)


async def test_unreachable_raises_typed_error() -> None:
    c = MoonrakerClient("http://x:7125", transport=OfflineTransport())
    with pytest.raises(MoonrakerUnreachableError):
        await c.server_info()
    await c.aclose()


async def test_api_error_and_klippy_unavailable() -> None:
    sim = scenario("config_error")
    c = MoonrakerClient("http://x:7125", transport=sim.transport())
    with pytest.raises(MoonrakerAPIError) as ei:
        await c.query_objects({"toolhead": None})
    assert ei.value.klippy_unavailable
    await c.aclose()


async def test_non_json_response_is_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>fluidd</html>")

    c = MoonrakerClient("http://x:7125", transport=httpx.MockTransport(handler))
    with pytest.raises(MoonrakerAPIError):
        await c.server_info()
    await c.aclose()


async def test_tail_and_size_limits() -> None:
    sim = SimPrinter()
    sim.files["gcodes"]["big.gcode"] = b"G1 X1\n" * 10000
    c = MoonrakerClient("http://x:7125", transport=sim.transport())
    tail, truncated = await c.download_tail("gcodes", "big.gcode", 60)
    assert truncated and len(tail) == 60
    with pytest.raises(FileTooLargeError):
        await c.download("gcodes", "big.gcode", max_bytes=1000)
    await c.aclose()


async def test_status_healthy(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("healthy"))
    st = await service.status(ctx, ctx.printer("enderbig"))
    assert st["klippy_state"] == "ready"
    assert st["temperatures"]["extruder"]["stale"] is False
    assert st["probe"]["name"] == "bltouch"
    assert st["filament_sensors"] == {"filament_switch_sensor filament_sensor": True}
    assert st["data_gaps"] == []
    assert st["live_offset"] is not None


async def test_status_partial_response_is_a_gap_not_a_guess(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    sim.missing_objects = {"extruder", "heater_bed"}
    ctx = make_ctx(sim)
    st = await service.status(ctx, ctx.printer("enderbig"))
    # no invented temperatures for objects Klipper did not report
    assert "extruder" not in (st.get("temperatures") or {})
    assert st["klippy_state"] == "ready"


async def test_status_shutdown_marks_telemetry_stale(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("mcu_disconnected"))
    st = await service.status(ctx, ctx.printer("enderbig"))
    assert st["klippy_state"] == "shutdown"
    assert st["temperatures"]["extruder"]["stale"] is True


async def test_status_offline_reports_kubernetes(make_ctx: MakeCtx) -> None:
    class FakeKube:
        async def workload(self, ns: str, sel: str) -> dict:
            return {
                "pods": [
                    {
                        "pod": "enderbig-abc-123",
                        "phase": "Pending",
                        "node": None,
                        "containers": [],
                        "unschedulable": "0/8 nodes are available: 8 node(s) didn't match Pod's node "
                        "affinity/selector.",
                    }
                ],
                "events": [],
            }

        async def aclose(self) -> None: ...

    ctx = make_ctx(scenario("healthy"), kube=FakeKube())
    ctx.clients["enderbig"] = MoonrakerClient("http://x", transport=OfflineTransport())
    st = await service.status(ctx, ctx.printer("enderbig"))
    assert st["moonraker"] == "unreachable" and st["klippy_state"] == "unknown"
    assert "USB serial" in st["kubernetes"]["observations"][0]


async def test_config_sources_and_canonical_loaded(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("healthy"))
    gaps = service.Gaps()
    srcs = await service.config_sources(ctx, ctx.printer("enderbig"), gaps)
    assert set(srcs) == {"file", "loaded"}
    assert gaps.to_list()[0]["source"] == "git seed config"  # no git configured: a gap, not an error
    # loaded config from the log and from configfile hash identically
    log_text = (await ctx.client(ctx.printer("enderbig")).download("logs", "klippy.log", max_bytes=10**7)).decode()
    from printer_agent import klippy_log
    from printer_agent.taxonomy import load_taxonomy

    s = klippy_log.parse(log_text, load_taxonomy()).sessions[0]
    assert service.canonical(s.config_text or "") == srcs["loaded"]
