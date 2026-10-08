"""Background loop: keeps metrics fresh and records history nothing else keeps.

Every interval: a light status query per printer (metrics). Every
`snapshot_every` intervals: snapshot the on-disk and loaded config (so
"what changed since the last good print" has an answer) and sync job
outcomes. Once at startup: backfill loaded-config history from klippy.log.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from printer_agent import metrics, service
from printer_agent.gitrepo import GitError
from printer_agent.inventory import Printer
from printer_agent.moonraker import MoonrakerError
from printer_agent.service import Context, Gaps

logger = logging.getLogger(__name__)
POLL_OBJECTS: dict[str, list[str] | None] = {
    "print_stats": ["state", "print_duration", "filename"],
    "virtual_sdcard": ["progress"],
    "extruder": ["temperature", "target", "power"],
    "heater_bed": ["temperature", "target", "power"],
    "fan": ["speed"],
    "motion_report": ["live_velocity"],
    "mcu": ["last_stats"],
}


class Poller:
    def __init__(self, ctx: Context, *, snapshot_every: int = 10) -> None:
        self.ctx = ctx
        self.snapshot_every = snapshot_every
        self._task: asyncio.Task[None] | None = None
        self._last_ok: dict[str, float] = {}

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="printer-poller")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        for p in self.ctx.inventory.enabled():
            await self._guard(self.backfill(p), p, "backfill")
        if self.ctx.git is not None:
            try:
                await self.ctx.git.ensure()
            except GitError:
                logger.warning("initial git clone failed; git tools will retry", exc_info=True)
        cycle = 0
        while True:
            for p in self.ctx.inventory.enabled():
                await self._guard(self.poll(p), p, "status")
                if cycle % self.snapshot_every == 0:
                    await self._guard(self.snapshot(p), p, "snapshot")
            now = time.time()
            for p in self.ctx.inventory.enabled():
                if p.id in self._last_ok:
                    metrics.TELEMETRY_AGE.labels(p.id).set(now - self._last_ok[p.id])
            cycle += 1
            await asyncio.sleep(self.ctx.settings.poll_interval)

    async def _guard(self, coro: object, p: Printer, source: str) -> None:
        try:
            await coro  # type: ignore[misc]
        except MoonrakerError as err:
            metrics.POLL_ERRORS.labels(p.id, source).inc()
            logger.info("poll %s for %s failed: %s", source, p.id, err)
        except Exception:
            metrics.POLL_ERRORS.labels(p.id, source).inc()
            logger.exception("poll %s for %s crashed", source, p.id)

    async def poll(self, p: Printer) -> None:
        client = self.ctx.client(p)
        try:
            info = await client.server_info()
        except MoonrakerError:
            metrics.update_from_status(p.id, None)
            raise
        res: dict[str, object] = {"klippy_state": info.get("klippy_state"), "status": {}}
        if info.get("klippy_state") == "ready":
            available = set(await client.objects_list())
            q = {k: v for k, v in POLL_OBJECTS.items() if k in available}
            res["status"] = (await client.query_objects(q)).get("status", {})
        metrics.update_from_status(p.id, res)
        self._last_ok[p.id] = time.time()

    async def snapshot(self, p: Printer) -> None:
        gaps = Gaps()
        await service.config_sources(self.ctx, p, gaps)
        jobs = await self.ctx.client(p).history_list(limit=200)
        counts: dict[str, int] = {}
        for j in jobs:
            self.ctx.store.record_job(p.id, j)
            counts[str(j.get("status"))] = counts.get(str(j.get("status")), 0) + 1
        for status, n in counts.items():
            metrics.JOBS.labels(p.id, status).set(n)

    async def backfill(self, p: Printer) -> None:
        """Record loaded-config history from klippy.log and rotated logs."""
        gaps = Gaps()
        try:
            files = await service.log_files(self.ctx, p)
        except MoonrakerError:
            files = []
        names = [
            "klippy.log",
            *sorted(
                (f.get("path") or "" for f in files if (f.get("path") or "").startswith("klippy.log.")), reverse=True
            ),
        ]
        for name in names[:6]:
            await service.klippy(self.ctx, p, gaps, filename=name, max_bytes=20_000_000)
