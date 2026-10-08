from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from conftest import MakeCtx
from sim import fixture, scenario

from printer_agent import klipper_config, remediation
from printer_agent.gitrepo import extract_configmap_key
from printer_agent.safety import PolicyDeniedError, PreconditionFailedError, RiskLevel

EVIDENCE = ["klippy.log line 1234: Probe samples exceed tolerance (3x in 2 days)"]


async def _propose(ctx, edits, summary="slow bltouch probing speed") -> dict:  # type: ignore[no-untyped-def]
    return await remediation.propose(
        ctx,
        ctx.printer("enderbig"),
        edits,
        summary=summary,
        rationale="tolerance failures at 10 mm/s",
        evidence=EVIDENCE,
    )


async def test_propose_is_minimal_and_side_effect_free(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    ctx = make_ctx(sim)
    before = sim.files["config"]["printer.cfg"]
    res = await _propose(ctx, [{"section": "bltouch", "option": "speed", "value": "5.0"}])
    assert sim.files["config"]["printer.cfg"] == before
    assert [c["option"] for c in res["changes"]] == ["speed"]
    assert res["risk"] == "HIGH_RISK_WRITE" and res["dangerous_changes"] == []
    assert res["diff"].count("\n-speed") == 1 and res["diff"].count("\n+speed") == 1
    assert res["validation"]["passed"]
    assert not any(m == "POST" for m, _, _ in sim.calls)


async def test_propose_requires_evidence_and_detects_noop(make_ctx: MakeCtx) -> None:
    ctx = make_ctx()
    with pytest.raises(PreconditionFailedError, match="evidence"):
        await remediation.propose(
            ctx,
            ctx.printer("enderbig"),
            [{"section": "bltouch", "option": "speed", "value": "5"}],
            summary="x",
            rationale="y",
            evidence=[],
        )
    with pytest.raises(PreconditionFailedError, match="do not change"):
        await _propose(ctx, [{"section": "bltouch", "option": "speed", "value": "10.0"}])


async def test_propose_flags_dangerous_and_validation(make_ctx: MakeCtx) -> None:
    ctx = make_ctx()
    res = await _propose(ctx, [{"section": "bltouch", "option": "sensor_pin", "value": "PC14"}])
    assert res["risk"] == "DANGEROUS" and res["dangerous_changes"] == ["bltouch/sensor_pin"]
    assert any(p["code"] == "bltouch_no_pullup" for p in res["validation"]["introduced_problems"])
    assert res["validation"]["passed"] is True  # a warning, not an error/danger
    res = await _propose(
        ctx,
        [
            {"section": "verify_heater extruder", "option": "max_error", "value": "120"},
            {"section": "verify_heater extruder", "option": "hysteresis", "value": "5"},
        ],
        summary="restore verify_heater defaults",
    )
    resolved = {p["code"] for p in res["validation"]["resolved_problems"]}
    assert {"verify_heater_disabled", "verify_heater_hysteresis"} <= resolved


async def test_apply_happy_path_verifies_running_config(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    ctx = make_ctx(sim)
    prop = await _propose(ctx, [{"section": "bltouch", "option": "speed", "value": "5.0"}])
    res = await remediation.apply(ctx, ctx.printer("enderbig"), prop["proposal_id"])
    assert res["ok"] and res["verified"], res
    assert sim.loaded["bltouch"]["speed"] == "5.0"
    backups = [k for k in sim.files["config"] if k.startswith("printer-agent-backups/")]
    assert len(backups) == 1 and sim.files["config"][backups[0]] == fixture("enderbig.cfg").encode()
    # a second apply of the same proposal is refused
    with pytest.raises(PreconditionFailedError):
        await remediation.apply(ctx, ctx.printer("enderbig"), prop["proposal_id"])


async def test_apply_rolls_back_when_klipper_rejects(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    ctx = make_ctx(sim)
    # removing safe_z_home is fine statically, removing [printer] kinematics is an error the sim's
    # Klipper rejects on restart; propose() catches it first, so bypass validation to model a
    # Klipper-only failure.
    prop = await _propose(ctx, [{"section": "printer", "option": "max_accel", "value": "2500"}])
    stored = ctx.store.get_proposal(prop["proposal_id"])
    assert stored is not None
    stored["new_text"] = stored["new_text"].replace("kinematics: cartesian", "")
    ctx.store.save_proposal(stored)
    ctx.printer("enderbig").policy.max_risk = RiskLevel.DANGEROUS
    res = await remediation.apply(
        ctx, ctx.printer("enderbig"), prop["proposal_id"], acknowledge_dangerous=["printer/max_accel"]
    )
    assert not res["ok"] and res["rolled_back"] is True
    assert "Rolled back" in res["message"]
    assert sim.klippy_state == "ready"
    assert sim.files["config"]["printer.cfg"] == fixture("enderbig.cfg").encode()
    assert ctx.store.get_proposal(prop["proposal_id"])["status"] == "rolled_back"  # type: ignore[index]


async def test_apply_requires_ack_policy_and_unchanged_base(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    ctx = make_ctx(sim)  # server allows DANGEROUS; printers.yaml default (HIGH_RISK_WRITE) does not
    prop = await _propose(ctx, [{"section": "bltouch", "option": "sensor_pin", "value": "^PC2"}])
    assert prop["policy_allows_apply"] is False
    with pytest.raises(PolicyDeniedError):
        await remediation.apply(ctx, ctx.printer("enderbig"), prop["proposal_id"])
    ctx.printer("enderbig").policy.max_risk = RiskLevel.DANGEROUS
    with pytest.raises(PreconditionFailedError) as ei:
        await remediation.apply(ctx, ctx.printer("enderbig"), prop["proposal_id"])
    assert ei.value.details["unacknowledged"] == ["bltouch/sensor_pin"]
    sim.files["config"]["printer.cfg"] += b"\n# edited in fluidd\n"
    with pytest.raises(PreconditionFailedError, match="changed since the proposal"):
        await remediation.apply(
            ctx, ctx.printer("enderbig"), prop["proposal_id"], acknowledge_dangerous=["bltouch/sensor_pin"]
        )


async def test_apply_refused_while_printing(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("printing"))
    prop = await _propose(ctx, [{"section": "bltouch", "option": "speed", "value": "5.0"}])
    with pytest.raises(PreconditionFailedError, match="printing"):
        await remediation.apply(ctx, ctx.printer("enderbig"), prop["proposal_id"])


class FakeGitHub:
    """Enough of the GitHub REST API to exercise open_pr, recording writes."""

    def __init__(self, manifest: str) -> None:
        self.manifest = manifest
        self.refs: dict[str, str] = {"main": "a" * 40}
        self.puts: list[dict] = []
        self.prs: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.replace("/repos/myoung34/homelab", "")
        if request.method == "GET" and path == "/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": self.refs["main"]}})
        if request.method == "GET" and path.startswith("/contents/"):
            return httpx.Response(
                200, json={"sha": "blobsha", "content": base64.b64encode(self.manifest.encode()).decode()}
            )
        if request.method == "POST" and path == "/git/refs":
            body = json.loads(request.content)
            self.refs[body["ref"].removeprefix("refs/heads/")] = body["sha"]
            return httpx.Response(201, json={})
        if request.method == "PUT" and path.startswith("/contents/"):
            self.puts.append(json.loads(request.content))
            return httpx.Response(200, json={})
        if request.method == "POST" and path == "/pulls":
            body = json.loads(request.content)
            self.prs.append(body)
            return httpx.Response(201, json={"number": 99})
        if request.method == "GET" and path == "/pulls/99":
            return httpx.Response(
                200,
                json={
                    "state": "open",
                    "head": {"ref": self.prs[0]["head"]},
                    "html_url": "https://github.com/myoung34/homelab/pull/99",
                },
            )
        if request.method == "GET" and path == "/pulls/99/files":
            return httpx.Response(200, json=[{"filename": "k8s/prod/klipper/enderbig-configmap.yaml"}])
        return httpx.Response(404, json={"message": f"unexpected {request.method} {path}"})


async def test_open_pr_syncs_seed_and_never_touches_main(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    ctx = make_ctx(sim, github_token="t0ken")
    manifest = (Path(__file__).parent / "fixtures" / "enderbig-configmap.yaml").read_text()
    gh = FakeGitHub(manifest)
    prop = await _propose(
        ctx, [{"section": "bltouch", "option": "z_offset", "value": "3.380"}], summary="lower bltouch z_offset"
    )
    with pytest.raises(PreconditionFailedError, match="expected one of"):
        await remediation.open_pr(
            ctx, ctx.printer("enderbig"), prop["proposal_id"], transport=httpx.MockTransport(gh.handler)
        )
    await remediation.apply(ctx, ctx.printer("enderbig"), prop["proposal_id"])
    res = await remediation.open_pr(
        ctx, ctx.printer("enderbig"), prop["proposal_id"], transport=httpx.MockTransport(gh.handler)
    )
    assert res["ok"] and res["verified"], res
    put = gh.puts[0]
    assert put["branch"].startswith("printer-agent/enderbig-") and put["branch"] != "main"
    assert put["message"].startswith("fix(klipper): lower bltouch z_offset for enderbig")
    assert "Evidence:" in put["message"] and EVIDENCE[0] in put["message"]
    new_manifest = base64.b64decode(put["content"]).decode()
    new_seed = extract_configmap_key(new_manifest, "printer.cfg")
    assert klipper_config.parse(new_seed).value("bltouch", "z_offset") == "3.380"
    # only the one line of the manifest changed (comments/formatting preserved)
    changed = [a for a, b in zip(manifest.splitlines(), new_manifest.splitlines(), strict=True) if a != b]
    assert changed == ["    #*# z_offset = 3.420"]
    assert gh.refs["main"] == "a" * 40
    assert not gh.prs[0].get("draft")


async def test_open_pr_without_token(make_ctx: MakeCtx) -> None:
    ctx = make_ctx()
    prop = await _propose(ctx, [{"section": "bltouch", "option": "speed", "value": "5.0"}])
    with pytest.raises(PreconditionFailedError, match="GITHUB_TOKEN"):
        await remediation.open_pr(ctx, ctx.printer("enderbig"), prop["proposal_id"], allow_unapplied=True)
