"""Entrypoint: build context, start the background poller, serve MCP over streamable HTTP."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from starlette.applications import Starlette

from printer_agent.gitrepo import GitRepo
from printer_agent.inventory import load_inventory
from printer_agent.kube import KubeReader
from printer_agent.moonraker import Clock
from printer_agent.poller import Poller
from printer_agent.safety import Auditor, Policy
from printer_agent.server import build_server
from printer_agent.service import Context
from printer_agent.settings import Settings
from printer_agent.store import Store
from printer_agent.taxonomy import load_taxonomy


class JsonFormatter(logging.Formatter):
    """One JSON object per line, so Datadog log collection parses fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def build_context(settings: Settings) -> Context:
    store = Store(settings.data_dir / "printer-agent.sqlite")
    git = (
        GitRepo(
            settings.git_url,
            settings.data_dir / "homelab.git",
            branch=settings.git_branch,
            allowed_paths=settings.git_paths,
            fetch_ttl=settings.git_fetch_ttl,
        )
        if settings.git_url
        else None
    )
    return Context(
        settings=settings,
        inventory=load_inventory(settings.inventory_path),
        store=store,
        taxonomy=load_taxonomy(settings.taxonomy_extra),
        git=git,
        kube=KubeReader.in_cluster() if settings.kube_enabled else None,
        policy=Policy(settings.max_risk),
        auditor=Auditor(store),
        clock=Clock(),
    )


def build_app(ctx: Context, *, start_poller: bool = True) -> Starlette:
    server = build_server(ctx)
    app = server.streamable_http_app(stateless_http=False, json_response=True, host=ctx.settings.host)
    inner = app.router.lifespan_context
    poller = Poller(ctx)

    @asynccontextmanager
    async def lifespan(a: Starlette) -> AsyncIterator[None]:
        async with inner(a):
            if start_poller:
                poller.start()
            try:
                yield
            finally:
                await poller.stop()
                await ctx.aclose()
                ctx.store.close()

    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    settings = Settings.from_env()
    ctx = build_context(settings)
    logging.getLogger(__name__).info(
        "starting printer-agent: printers=%s max_risk=%s",
        [p.id for p in ctx.inventory.enabled()],
        settings.max_risk.name,
    )
    uvicorn.run(build_app(ctx), host=settings.host, port=settings.port, log_config=None, proxy_headers=False)


if __name__ == "__main__":
    main()
