"""The kagent Agent and inventory in k8s/prod/printer-agent must match this server."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from test_git_and_server import EXPECTED_TOOLS

from printer_agent.inventory import Inventory
from printer_agent.server import WRITE_TOOLS

MANIFESTS = Path(__file__).resolve().parents[3] / "k8s" / "prod" / "printer-agent"
pytestmark = pytest.mark.skipif(not MANIFESTS.exists(), reason="not inside the homelab repo")


def _docs(name: str) -> list[dict]:
    return [d for d in yaml.safe_load_all((MANIFESTS / name).read_text()) if d]


def test_agent_tool_lists_match_server() -> None:
    agent = next(d for d in _docs("agent.yaml") if d["kind"] == "Agent")
    mcp = next(t["mcpServer"] for t in agent["spec"]["declarative"]["tools"] if t["mcpServer"]["name"] == "printer-mcp")
    assert set(mcp["toolNames"]) == EXPECTED_TOOLS
    # every write tool needs human approval, and nothing else is gated
    assert set(mcp["requireApproval"]) == set(WRITE_TOOLS)


def test_inventory_configmap_is_valid() -> None:
    cm = _docs("printers.yaml")[0]
    inv = Inventory.model_validate(yaml.safe_load(cm["data"]["printers.yaml"]))
    assert {p.id for p in inv.enabled()} == {"enderbig", "enderleft"}
    for p in inv.printers:
        assert p.git is not None and (MANIFESTS.parent / "klipper" / Path(p.git.path).name).exists()
        # MCU serial must match the klipper Deployment's by-id path
        deploy = (MANIFESTS.parent / "klipper" / f"{p.id}.yaml").read_text()
        assert p.hardware.mcu["serial"] in deploy


def test_prompt_includes_resolve() -> None:
    agent = next(d for d in _docs("agent.yaml") if d["kind"] == "Agent")
    keys = set(_docs("prompt.yaml")[0]["data"])
    import re

    used = set(re.findall(r'include "printer/(\w+)"', agent["spec"]["declarative"]["systemMessage"]))
    assert used and used <= keys
