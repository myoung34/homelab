"""Minimal read-only view of the printer workloads in Kubernetes.

In the homelab each printer is a Deployment pinned (by NFD USB-serial label)
to the node its MCU is plugged into. "Printer offline" therefore has several
distinguishable causes - pod Pending because the USB serial vanished, node
down, container crashlooping/OOMKilled - and this module surfaces them.

Uses the pod's service account with a namespaced Role granting get/list on
pods and events only (see the homelab manifests).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)
SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")


class KubeError(Exception):
    pass


class KubeReader:
    def __init__(
        self,
        base_url: str = "https://kubernetes.default.svc",
        *,
        token: str | None = None,
        verify: str | bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.AsyncClient(
            base_url=base_url, headers=headers, verify=verify, timeout=10.0, transport=transport
        )

    @classmethod
    def in_cluster(cls) -> KubeReader | None:
        token_file = SA_DIR / "token"
        if not token_file.exists():
            return None
        return cls(token=token_file.read_text().strip(), verify=str(SA_DIR / "ca.crt"))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            r = await self._client.get(path, params=params)
        except httpx.HTTPError as err:
            raise KubeError(f"kube API unreachable: {err}") from err
        if r.status_code == 403:
            raise KubeError(f"forbidden reading {path} (RBAC)")
        if r.status_code >= 400:
            raise KubeError(f"kube API {path} returned {r.status_code}")
        return dict(r.json())

    async def workload(self, namespace: str, selector: str) -> dict[str, Any]:
        pods = await self._get(f"/api/v1/namespaces/{namespace}/pods", {"labelSelector": selector})
        out = []
        for pod in pods.get("items", []):
            meta, spec, status = pod["metadata"], pod.get("spec", {}), pod.get("status", {})
            containers = []
            for cs in status.get("containerStatuses", []):
                last = cs.get("lastState", {}).get("terminated")
                state = next(iter(cs.get("state", {})), "unknown")
                c: dict[str, Any] = {
                    "name": cs["name"],
                    "ready": cs.get("ready"),
                    "restarts": cs.get("restartCount", 0),
                    "state": state,
                }
                waiting = cs.get("state", {}).get("waiting")
                if waiting:
                    c["waiting_reason"] = waiting.get("reason")
                if last:
                    c["last_termination"] = {k: last.get(k) for k in ("reason", "exitCode", "startedAt", "finishedAt")}
                containers.append(c)
            conds = {c["type"]: c for c in status.get("conditions", [])}
            sched = conds.get("PodScheduled", {})
            entry: dict[str, Any] = {
                "pod": meta["name"],
                "phase": status.get("phase"),
                "node": spec.get("nodeName"),
                "started": status.get("startTime"),
                "containers": containers,
            }
            if sched.get("status") == "False":
                entry["unschedulable"] = sched.get("message")
            out.append(entry)
        events = await self._get(f"/api/v1/namespaces/{namespace}/events")
        names = {p["pod"] for p in out}
        evs = [
            {
                "time": e.get("lastTimestamp") or e.get("eventTime"),
                "type": e.get("type"),
                "reason": e.get("reason"),
                "object": e.get("involvedObject", {}).get("name"),
                "message": (e.get("message") or "")[:300],
                "count": e.get("count"),
            }
            for e in events.get("items", [])
            if e.get("involvedObject", {}).get("name") in names
            or any(e.get("involvedObject", {}).get("name", "").startswith(n.rsplit("-", 2)[0]) for n in names)
        ]
        evs.sort(key=lambda e: e["time"] or "")
        return {"pods": out, "events": evs[-20:]}


def interpret(workload: dict[str, Any]) -> list[str]:
    """Plain-language observations about the workload state."""
    notes: list[str] = []
    pods = workload.get("pods", [])
    if not pods:
        notes.append("no pod exists for this printer (Deployment scaled to 0 or not deployed)")
    for p in pods:
        if p.get("unschedulable"):
            msg = p["unschedulable"]
            if "node affinity" in msg or "didn't match" in msg:
                notes.append(
                    f"pod {p['pod']} is unschedulable: no node advertises this printer's MCU USB "
                    "serial (printer unplugged, powered off, or MCU not enumerating)"
                )
            else:
                notes.append(f"pod {p['pod']} is unschedulable: {msg}")
        for c in p.get("containers", []):
            lt = c.get("last_termination") or {}
            if lt.get("reason") == "OOMKilled":
                notes.append(f"{c['name']} was OOMKilled at {lt.get('finishedAt')}")
            elif lt:
                notes.append(
                    f"{c['name']} last terminated: {lt.get('reason')} (exit {lt.get('exitCode')}) "
                    f"at {lt.get('finishedAt')}"
                )
            if c.get("waiting_reason") in (
                "CrashLoopBackOff",
                "CreateContainerError",
                "ErrImagePull",
                "ImagePullBackOff",
            ):
                notes.append(f"{c['name']} is {c['waiting_reason']}")
    return notes
