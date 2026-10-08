from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import MakeCtx
from mcp import Client
from sim import fixture, scenario

from printer_agent.gitrepo import (
    GitError,
    GitPathNotAllowedError,
    GitRepo,
    extract_configmap_key,
    replace_configmap_key,
)
from printer_agent.safety import RiskLevel
from printer_agent.server import WRITE_TOOLS, build_server

FIXTURES = Path(__file__).parent / "fixtures"
SEED = "k8s/prod/klipper/enderbig-configmap.yaml"

EXPECTED_TOOLS = {
    "printer_list",
    "printer_status",
    "printer_readiness",
    "printer_temperatures",
    "printer_logs",
    "printer_gcode_console",
    "printer_print_history",
    "printer_classify_failures",
    "printer_what_happened",
    "printer_diagnose",
    "printer_config_get",
    "printer_config_explain",
    "printer_config_validate",
    "printer_config_diff",
    "printer_config_drift",
    "printer_config_history",
    "printer_compare",
    "printer_gcode_inspect",
    "printer_git_log",
    "printer_git_show",
    "printer_git_diff",
    "printer_git_blame",
    "printer_calibration",
    "printer_taxonomy",
    "printer_endstops",
    "printer_camera_snapshot",
    "printer_audit_log",
    "printer_probe_query",
    "printer_config_propose",
    *WRITE_TOOLS,
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
            "HOME": str(cwd),
        },
    ).stdout


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    repo = tmp_path / "origin"
    (repo / "k8s/prod/klipper").mkdir(parents=True)
    (repo / "secrets").mkdir()
    _git(repo, "init", "-q", "-b", "main")
    manifest = (FIXTURES / "enderbig-configmap.yaml").read_text()
    (repo / SEED).write_text(manifest)
    (repo / "secrets/x.txt").write_text("nope")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add klipper for ender5")
    (repo / SEED).write_text(manifest.replace("    sensor_pin: ^PC14", "    sensor_pin: ^PC2"))
    _git(repo, "commit", "-q", "-am", "fix(klipper): move bltouch sensor pin on enderbig")
    return repo


async def test_git_reads(origin: Path, tmp_path: Path) -> None:
    repo = GitRepo(f"file://{origin}", tmp_path / "clone.git", allowed_paths=("k8s/prod/klipper",))
    commits = await repo.log(SEED)
    assert [c.subject for c in commits] == [
        "fix(klipper): move bltouch sensor pin on enderbig",
        "add klipper for ender5",
    ]
    shown = await repo.show(commits[0].sha)
    assert "+    sensor_pin: ^PC2" in shown["diff"]
    diff = await repo.diff(commits[1].sha, commits[0].sha, SEED)
    assert "-    sensor_pin: ^PC14" in diff
    seed = await repo.seed_config(SEED)
    assert "sensor_pin: ^PC2" in seed
    old = await repo.seed_config(SEED, ref=commits[1].sha)
    assert "sensor_pin: ^PC14" in old
    blame = await repo.blame(SEED, start=1, end=400)
    pin = next(b for b in blame if "sensor_pin: ^PC2" in b["text"])
    assert pin["summary"].startswith("fix(klipper)")
    status = await repo.status()
    assert status["branch"] == "main"


async def test_git_refuses_paths_and_bad_refs(origin: Path, tmp_path: Path) -> None:
    repo = GitRepo(f"file://{origin}", tmp_path / "clone.git", allowed_paths=("k8s/prod/klipper",))
    with pytest.raises(GitPathNotAllowedError):
        await repo.file_at("secrets/x.txt")
    with pytest.raises(GitPathNotAllowedError):
        await repo.file_at("k8s/prod/klipper/../../../secrets/x.txt")
    for ref in ("--output=/tmp/x", "main;rm -rf /", "-p"):
        with pytest.raises(GitError):
            await repo.log(ref=ref)


def test_configmap_rewrite_round_trips_real_manifest() -> None:
    manifest = (FIXTURES / "enderbig-configmap.yaml").read_text()
    seed = extract_configmap_key(manifest, "printer.cfg")
    assert seed == fixture("enderbig.cfg")
    new = replace_configmap_key(manifest, "printer.cfg", seed.replace("speed: 10.0", "speed: 5.0"))
    changed = [(a, b) for a, b in zip(manifest.splitlines(), new.splitlines(), strict=True) if a != b]
    assert changed == [("    speed: 10.0", "    speed: 5.0")]
    with pytest.raises(GitError):
        replace_configmap_key("kind: ConfigMap\ndata: {}\n", "printer.cfg", "x")


# --------------------------------------------------------------- MCP surface


def _payload(result) -> dict:  # type: ignore[no-untyped-def]
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


async def test_tool_surface_and_annotations(make_ctx: MakeCtx) -> None:
    server = build_server(make_ctx())
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS
    assert len(names) <= 50  # kagent toolNames maxItems
    for t in tools:
        assert t.description, t.name
        assert "." not in t.name  # Anthropic tool names forbid dots
        ann = t.annotations
        assert ann is not None
        if t.name in WRITE_TOOLS:
            assert ann.destructive_hint is True and "[approval]" in t.description
        else:
            assert ann.destructive_hint is False


async def test_e2e_status_and_structured_errors(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(scenario("healthy"), max_risk=RiskLevel.SAFE_AUTOMATION)
    server = build_server(ctx)
    async with Client(server) as client:
        st = _payload(await client.call_tool("printer_status", {"printer": "enderbig"}))
        assert st["klippy_state"] == "ready" and "objects" not in st
        denied = _payload(await client.call_tool("printer_home", {"printer": "enderbig", "axes": "z"}))
        assert denied == {
            "ok": False,
            "error_kind": "policy_denied",
            "error": denied["error"],
            "risk": "HIGH_RISK_WRITE",
            "allowed": "SAFE_AUTOMATION",
        }
        unknown = _payload(await client.call_tool("printer_status", {"printer": "prusa"}))
        assert unknown["error_kind"] == "unknown_printer" and "enderbig" in unknown["error"]
        validate = _payload(await client.call_tool("printer_config_validate", {"printer": "enderbig"}))
        assert validate["valid"] is True and validate["counts"]["danger"] == 2
        diff = _payload(await client.call_tool("printer_config_diff", {"printer": "enderbig", "base": "loaded"}))
        assert diff["identical"] is True
        cam = _payload(await client.call_tool("printer_camera_snapshot", {"printer": "enderbig"}))
        assert cam["error_kind"] == "no_camera"
        gl = _payload(await client.call_tool("printer_git_log", {}))
        assert gl["error_kind"] == "git_disabled"


async def test_e2e_offline_printer_is_reported_not_invented(make_ctx: MakeCtx) -> None:
    from sim import OfflineTransport

    from printer_agent.moonraker import MoonrakerClient

    ctx = make_ctx(scenario("healthy"))
    ctx.clients["enderbig"] = MoonrakerClient("http://x", transport=OfflineTransport())
    async with Client(build_server(ctx)) as client:
        r = _payload(await client.call_tool("printer_temperatures", {"printer": "enderbig"}))
    assert r["error_kind"] == "printer_unreachable"
    assert "temperatures" not in r and "sensors" not in r


async def test_e2e_propose_apply_flow(make_ctx: MakeCtx) -> None:
    sim = scenario("healthy")
    ctx = make_ctx(sim)
    async with Client(build_server(ctx)) as client:
        prop = _payload(
            await client.call_tool(
                "printer_config_propose",
                {
                    "printer": "enderbig",
                    "summary": "restore verify_heater defaults",
                    "rationale": "thermal runaway protection is effectively disabled",
                    "evidence": ["printer_config_validate: verify_heater_disabled (max_error 12000000)"],
                    "edits": [
                        {"section": "verify_heater extruder", "option": "max_error", "value": None},
                        {"section": "verify_heater extruder", "option": "hysteresis", "value": None},
                    ],
                },
            )
        )
        assert prop["risk"] == "DANGEROUS" and prop["policy_allows_apply"] is False
        denied = _payload(
            await client.call_tool(
                "printer_config_apply",
                {
                    "printer": "enderbig",
                    "proposal_id": prop["proposal_id"],
                    "acknowledge_dangerous": prop["dangerous_changes"],
                },
            )
        )
        assert denied["error_kind"] == "policy_denied"
        ctx.printer("enderbig").policy.max_risk = RiskLevel.DANGEROUS
        applied = _payload(
            await client.call_tool(
                "printer_config_apply",
                {
                    "printer": "enderbig",
                    "proposal_id": prop["proposal_id"],
                    "acknowledge_dangerous": prop["dangerous_changes"],
                },
            )
        )
        assert applied["ok"] and applied["verified"], applied
        audit = _payload(await client.call_tool("printer_audit_log", {"printer": "enderbig"}))
    assert "max_error" not in sim.loaded["verify_heater extruder"]
    outcomes = [e["outcome"] for e in audit["entries"]]
    assert "denied" in outcomes and "verified" in outcomes
