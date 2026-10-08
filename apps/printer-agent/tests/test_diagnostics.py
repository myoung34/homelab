from __future__ import annotations

from conftest import MakeCtx
from sim import T0, OfflineTransport, fixture, job, klippy_log, scenario, stats_series

from printer_agent import calibration, diagnostics
from printer_agent.moonraker import MoonrakerClient


def _top(res: dict) -> dict:
    return res["hypotheses"][0]


async def test_thermal_runaway_points_at_heater_not_thermistor(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("thermal_runaway"))
    res = await diagnostics.what_happened(ctx, ctx.printer("enderbig"), which="last_failed")
    assert res["classification"]["failure_class"] == "THERMAL.heater_failure"
    assert res["classification"]["domain"] == "hardware"
    prox = res["proximate_cause"]
    assert prox[0]["certainty"] == "OBSERVED" and "verify_heater" in prox[0]["statement"]
    assert prox[1]["certainty"] == "INFERRED"  # this shutdown ended the job
    top = _top(res)
    assert any("PWM was >=95%" in e["statement"] for e in top["supporting"])
    assert res["context"]["thermal_traces"]["extruder"]["shape"] == "falling_at_full_power"
    # verify_heater was loosened on this printer: a config hypothesis exists but ranks low
    classes = [h["failure_class"] for h in res["hypotheses"]]
    assert "THERMAL.thermal_config" in classes
    assert res["actions_taken"].startswith("none")
    assert ctx.store.diagnoses("enderbig")[0]["top_class"] == "THERMAL.heater_failure"


async def test_thermistor_jumps_point_at_sensor(make_ctx: MakeCtx) -> None:
    cfg = fixture("enderbig.cfg")

    def ext(i: int) -> tuple[float, float, float]:
        return (210.0 if i % 7 else 240.0, 210.0, 0.4)

    sim = scenario("thermal_runaway")
    sim.files["logs"]["klippy.log"] = klippy_log(
        cfg,
        stats=stats_series(100, extruder_fn=ext, start=200),
        events=[(299.5, "Transition to shutdown state: Heater extruder not heating at expected rate")],
    ).encode()
    ctx = make_ctx(sim)
    res = await diagnostics.what_happened(ctx, ctx.printer("enderbig"), which="last_failed")
    assert _top(res)["failure_class"] == "THERMAL.thermistor_failure"
    heater = next(h for h in res["hypotheses"] if h["failure_class"] == "THERMAL.heater_failure")
    assert heater["contradicting"]


async def test_mcu_disconnect_uses_link_stats(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("mcu_disconnected"))
    res = await diagnostics.what_happened(ctx, ctx.printer("enderbig"))
    assert res["proximate_cause"][0]["statement"] == "Klipper lost communication with MCU mcu"
    assert res["classification"]["failure_class"] == "FIRMWARE.mcu_disconnect"
    assert res["context"]["mcu_link_before_event"]["retransmit_bytes"] > 100
    # Never claims certainty about the physical cause.
    assert all(h["certainty"] != "OBSERVED" for h in res["hypotheses"])


async def test_probe_failure_is_remapped_from_z_endstop(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("probe_failure"))
    res = await diagnostics.what_happened(ctx, ctx.printer("enderbig"), which="last_failed")
    assert "remapped to the probe" in res["context"]["note"]
    assert res["classification"]["failure_class"].startswith("PROBE.")
    assert "next_test" in _top(res) and _top(res)["next_test"]
    assert any("Least-invasive next test" in r for r in res["recommendations"])


async def test_probe_config_differs_from_working_sibling(make_ctx: MakeCtx) -> None:
    good = scenario("healthy", config_text=fixture("enderleft.cfg"))
    bad_cfg = fixture("enderleft.cfg").replace("probe_with_touch_mode: True", "probe_with_touch_mode: False")
    bad = scenario("probe_failure", config_text=bad_cfg)
    ctx = make_ctx({"enderbig": bad, "enderleft": good})
    # the sibling's last completed job has a recorded config
    from printer_agent import service

    ctx.store.record_config("enderleft", "loaded", service.canonical(fixture("enderleft.cfg")), ts=T0, source="t")
    ctx.store.record_job("enderleft", job("100", "completed", T0 + 10))
    res = await diagnostics.what_happened(ctx, ctx.printer("enderbig"), which="last_failed")
    cfg_h = next(h for h in res["hypotheses"] if h["failure_class"] == "PROBE.probe_configuration")
    assert any("enderleft prints successfully with different" in e["statement"] for e in cfg_h["supporting"])


async def test_config_change_since_last_success_is_correlated(make_ctx: MakeCtx) -> None:
    from printer_agent import service

    sim = scenario("probe_failure")
    ctx = make_ctx(sim)
    old = fixture("enderbig.cfg").replace("sensor_pin: ^PC14", "sensor_pin: ^PC2")
    ctx.store.record_config("enderbig", "loaded", service.canonical(old), ts=T0 - 10000, source="t")
    ctx.store.record_config("enderbig", "loaded", service.canonical(fixture("enderbig.cfg")), ts=T0 - 100, source="t")
    res = await diagnostics.what_happened(ctx, ctx.printer("enderbig"), which="last_failed")
    changes = res["context"]["config_changes_since_last_success"]
    assert any(c["option"] == "sensor_pin" and c["risk"] == "DANGEROUS" for c in changes)


async def test_cancelled_is_operator(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("cancelled"))
    res = await diagnostics.what_happened(ctx, ctx.printer("enderbig"))
    assert res["classification"]["failure_class"] == "OPERATOR.cancelled"
    assert res["classification"]["domain"] == "operator"
    assert any("why the print was cancelled" in u for u in res["unknowns"])


async def test_klippy_disconnect_with_pod_restart(make_ctx: MakeCtx) -> None:
    import time

    end = T0 + 700
    finished = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end - 5))

    class FakeKube:
        async def workload(self, ns: str, sel: str) -> dict:
            return {
                "pods": [
                    {
                        "pod": "enderbig-a-b",
                        "phase": "Running",
                        "node": "klipper",
                        "containers": [
                            {
                                "name": "klipper",
                                "restarts": 1,
                                "state": "running",
                                "last_termination": {"reason": "OOMKilled", "exitCode": 137, "finishedAt": finished},
                            }
                        ],
                    }
                ],
                "events": [],
            }

        async def aclose(self) -> None: ...

    sim = scenario("healthy")
    sim.jobs = [job("000007", "klippy_disconnect", T0 + 100, duration=600)]
    ctx = make_ctx(sim, kube=FakeKube())
    res = await diagnostics.what_happened(ctx, ctx.printer("enderbig"))
    top = _top(res)
    assert top["failure_class"] == "NETWORK.host_failure" and top["certainty"] == "LIKELY"
    assert "OOMKilled" in top["supporting"][0]["statement"]


async def test_offline_printer(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("healthy"))
    ctx.clients["enderbig"] = MoonrakerClient("http://x", transport=OfflineTransport())
    res = await diagnostics.what_happened(ctx, ctx.printer("enderbig"))
    assert res["subject"] == "printer offline"
    assert res["proximate_cause"][0]["certainty"] == "OBSERVED"
    assert any("Kubernetes" in u for u in res["unknowns"])


async def test_classify_history(make_ctx: MakeCtx) -> None:
    sim = scenario("thermal_runaway")
    sim.jobs.append(job("000001", "cancelled", T0 - 20000))
    ctx = make_ctx(sim)
    res = await diagnostics.classify_history(ctx, ctx.printer("enderbig"), 10)
    by_id = {j["job_id"]: j for j in res["failed_jobs"]}
    assert by_id["000004"]["failure_class"] == "THERMAL.thermal_runaway"
    assert by_id["000004"]["certainty"] == "OBSERVED"
    assert by_id["000001"]["failure_class"] == "OPERATOR.cancelled"


async def test_readiness_healthy(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("healthy"))
    r = await diagnostics.readiness(ctx, ctx.printer("enderbig"))
    assert r["ready"] is True, r["blocking"]
    # enderbig's real config has loosened verify_heater: a safety warning, not a block
    assert any(w["severity"] == "safety" for w in r["warnings"])


async def test_readiness_blocks(make_ctx: MakeCtx) -> None:
    for name, needle in (("printing", "busy"), ("mcu_disconnected", "shutdown"), ("config_error", "'error'")):
        ctx = make_ctx(scenario(name))
        r = await diagnostics.readiness(ctx, ctx.printer("enderbig"))
        assert r["ready"] is False
        assert any(needle in b["reason"] for b in r["blocking"]), (name, r["blocking"])
    sim = scenario("healthy")
    sim.free_bytes = 10_000_000
    ctx = make_ctx(sim)
    r = await diagnostics.readiness(ctx, ctx.printer("enderbig"))
    assert any("MB free" in b["reason"] for b in r["blocking"])
    ctx = make_ctx(scenario("healthy"))
    ctx.clients["enderbig"] = MoonrakerClient("http://x", transport=OfflineTransport())
    r = await diagnostics.readiness(ctx, ctx.printer("enderbig"))
    assert r["ready"] is False and "unreachable" in r["blocking"][0]["reason"]


async def test_diagnose_first_layer_detects_tilt(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("healthy"))
    res = await diagnostics.diagnose_symptom(ctx, ctx.printer("enderbig"), "why is my first layer bad?")
    assert res["classification"]["failure_class"] == "BED.leveling"
    mesh = res["context"]["bed_mesh"]
    assert mesh["range_mm"] > 1.5 and abs(mesh["x_slope_mm"]) > 1.0


async def test_diagnose_homing_reads_endstops(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    sim.endstops = {"x": "TRIGGERED", "y": "open", "z": "open"}
    ctx = make_ctx(sim)
    res = await diagnostics.diagnose_symptom(ctx, ctx.printer("enderbig"), "G28 fails intermittently")
    assert res["context"]["endstops_now"]["x"] == "TRIGGERED"
    assert any(h["failure_class"] == "MOTION.endstop_configuration" for h in res["hypotheses"])


async def test_calibration_detects_copied_values(make_ctx: MakeCtx) -> None:
    right = scenario("healthy", config_text=fixture("enderright.cfg"))
    left = scenario("healthy", config_text=fixture("enderleft.cfg"))
    sims = {"enderright": right, "enderleft": left}
    ctx = make_ctx(sims)
    ctx.store.record_config("enderleft", "file", fixture("enderleft.cfg"), source="t")
    res = await calibration.status(ctx, ctx.printer("enderright"))
    items = {i["item"]: i for i in res["items"]}
    assert items["pid_extruder"]["state"] == "inherited"
    assert items["pressure_advance"]["state"] == "default"
    assert items["input_shaper"]["state"] == "not_configured"
    # all three real configs loosen verify_heater, so safety comes first...
    assert res["recommendations"][0]["calibrate"] == "restore thermal runaway protection"
    # ...then the PID values copied from enderleft
    pid = res["recommendations"][1]
    assert pid["calibrate"].startswith("PID") and "enderleft" in pid["why"]


async def test_calibration_puts_safety_first(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("healthy"))
    res = await calibration.status(ctx, ctx.printer("enderbig"))
    assert res["recommendations"][0]["calibrate"] == "restore thermal runaway protection"
    tram = next(i for i in res["items"] if i["item"] == "bed_tram")
    assert tram["state"] == "needs_attention"


def test_topic_routing() -> None:
    assert diagnostics.topic_of("Why did my Ender 5 stop during the last print?") == "failure"
    assert diagnostics.topic_of("Why did the print fail at 63%?") == "failure"
    assert diagnostics.topic_of("Why does G28 fail intermittently?") == "probe"
    assert diagnostics.topic_of("Why is my BLTouch failing to trigger?") == "probe"
    assert diagnostics.topic_of("Is my bed temperature stable?") == "thermal"
    assert diagnostics.topic_of("Why is my first layer bad?") == "first_layer"
    assert diagnostics.topic_of("X endstop not working") == "homing"
    assert diagnostics.topic_of("it keeps failing") == "failure"
