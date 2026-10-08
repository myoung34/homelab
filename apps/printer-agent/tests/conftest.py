from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from sim import SimPrinter, scenario

from printer_agent import operations
from printer_agent.inventory import Inventory
from printer_agent.moonraker import Clock, MoonrakerClient
from printer_agent.safety import Auditor, Policy, RiskLevel
from printer_agent.service import Context
from printer_agent.settings import Settings
from printer_agent.store import Store
from printer_agent.taxonomy import load_taxonomy

ENDERBIG_SERIAL = "320014000350415339373620"


def inventory_dict(ids: tuple[str, ...] = ("enderbig",)) -> dict:
    serials = {
        "enderbig": ENDERBIG_SERIAL,
        "enderleft": "4800420008504E5238363120",
        "enderright": "43002E000C50564837383420",
    }
    return {
        "printers": [
            {
                "id": pid,
                "name": pid,
                "model": "Ender 5" if pid == "enderbig" else "Ender 3",
                "klipper": {"moonraker_url": f"http://{pid}.sim:7125"},
                "hardware": {"mcu": {"serial": serials[pid]}, "board": "SKR mini e3 v3", "probe": "BLTouch"},
                "capabilities": {"bed_mesh": True, "filament_sensor": pid == "enderbig"},
                "git": {"path": f"k8s/prod/klipper/{pid}-configmap.yaml"},
                "kubernetes": {"namespace": "klipper", "selector": f"app.kubernetes.io/instance={pid}"},
            }
            for pid in ids
        ]
    }


class FixedClock(Clock):
    def __init__(self, t: float) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operations poll with real sleeps; make them instant in tests."""
    original = operations.poll

    async def quick(check, *, timeout: float, interval: float = 1.0) -> bool:  # type: ignore[no-untyped-def]
        return await original(check, timeout=min(timeout, 0.3), interval=0.01)

    monkeypatch.setattr(operations, "poll", quick)
    import printer_agent.remediation as rem

    monkeypatch.setattr(rem, "poll", quick)

    async def nosleep(_s: float) -> None:
        return None

    monkeypatch.setattr(operations, "_sleep", nosleep)
    monkeypatch.setattr(rem, "_sleep", nosleep)


MakeCtx = Callable[..., Context]


@pytest.fixture
async def make_ctx(tmp_path: Path) -> AsyncIterator[MakeCtx]:
    created: list[Context] = []

    def _make(
        sims: dict[str, SimPrinter] | SimPrinter | None = None,
        *,
        max_risk: RiskLevel = RiskLevel.DANGEROUS,
        now: float | None = None,
        kube=None,
        git=None,
        github_token: str | None = None,
    ) -> Context:  # type: ignore[no-untyped-def]
        if sims is None:
            sims = {"enderbig": scenario("healthy")}
        if isinstance(sims, SimPrinter):
            sims = {"enderbig": sims}
        settings = Settings.from_env(
            {
                "PRINTER_AGENT_DATA_DIR": str(tmp_path),
                "PRINTER_AGENT_MAX_RISK": "DANGEROUS",
                **({"GITHUB_TOKEN": github_token} if github_token else {}),
            }
        )
        store = Store(":memory:")
        from sim import T0

        ctx = Context(
            settings=settings,
            inventory=Inventory.model_validate(inventory_dict(tuple(sims))),
            store=store,
            taxonomy=load_taxonomy(),
            git=git,
            kube=kube,
            policy=Policy(max_risk),
            auditor=Auditor(store),
            clock=FixedClock(now if now is not None else T0 + 3600),
        )
        for pid, sim in sims.items():
            ctx.clients[pid] = MoonrakerClient(f"http://{pid}.sim:7125", transport=sim.transport())
        created.append(ctx)
        return ctx

    yield _make
    for c in created:
        await c.aclose()
