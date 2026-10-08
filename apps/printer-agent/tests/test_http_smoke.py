"""Real-wire test: uvicorn + streamable HTTP, as kagent's RemoteMCPServer sees it.

kagent's Go ADK speaks the handshake-era protocol (initialize + Mcp-Session-Id).
This drives the actual ASGI app over a socket with raw JSON-RPC to prove that
path works, independent of the Python SDK's own client.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml
from conftest import inventory_dict
from sim import scenario
from test_git_and_server import EXPECTED_TOOLS

from printer_agent.__main__ import build_app, build_context
from printer_agent.settings import Settings


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextlib.asynccontextmanager
async def serve(app, port: int) -> AsyncIterator[None]:  # type: ignore[no-untyped-def]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    try:
        yield
    finally:
        server.should_exit = True
        await task


@pytest.mark.parametrize("protocol", ["2025-03-26", "2025-06-18"])
async def test_streamable_http_handshake(tmp_path: Path, protocol: str) -> None:
    sim_port, mcp_port = _port(), _port()
    inv = inventory_dict()
    inv["printers"][0]["klipper"]["moonraker_url"] = f"http://127.0.0.1:{sim_port}"
    (tmp_path / "printers.yaml").write_text(yaml.safe_dump(inv))
    settings = Settings.from_env(
        {
            "PRINTER_AGENT_INVENTORY": str(tmp_path / "printers.yaml"),
            "PRINTER_AGENT_DATA_DIR": str(tmp_path / "data"),
            "PRINTER_AGENT_GIT_URL": "",
            "PRINTER_AGENT_KUBE": "off",
            "PRINTER_AGENT_POLL_INTERVAL": "0.2",
        }
    )
    ctx = build_context(settings)
    sim = scenario("healthy")
    async with serve(sim.app(), sim_port), serve(build_app(ctx), mcp_port):
        base = f"http://127.0.0.1:{mcp_port}"
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        async with httpx.AsyncClient(base_url=base, timeout=10) as c:
            r = await c.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": protocol,
                        "capabilities": {},
                        "clientInfo": {"name": "kagent-like", "version": "0"},
                    },
                },
            )
            assert r.status_code == 200, r.text
            init = r.json()
            assert init["result"]["protocolVersion"] == protocol
            assert init["result"]["serverInfo"]["name"] == "printer-agent"
            sid = r.headers.get("mcp-session-id")
            assert sid
            h = {**headers, "Mcp-Session-Id": sid, "Mcp-Protocol-Version": protocol}
            await c.post("/mcp", headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            r = await c.post("/mcp", headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            tools = {t["name"] for t in r.json()["result"]["tools"]}
            assert tools == EXPECTED_TOOLS
            r = await c.post(
                "/mcp",
                headers=h,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "printer_status", "arguments": {"printer": "enderbig"}},
                },
            )
            result = r.json()["result"]
            assert not result.get("isError")
            text = json.loads(result["content"][0]["text"])
            assert text["klippy_state"] == "ready"
            assert (await c.get("/healthz")).json()["printers"] == ["enderbig"]
            await asyncio.sleep(0.5)  # let the poller run once
            metrics = (await c.get("/metrics")).text
            assert 'printer_online{printer="enderbig"} 1.0' in metrics
            assert 'printer_agent_tool_calls_total{outcome="ok",tool="printer_status"}' in metrics
