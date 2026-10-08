"""Risk levels, authorization policy and the audit trail.

Two independent gates protect every write:

1. kagent's `requireApproval` pauses the agent until a human approves the
   exact tool call (configured on the Agent resource in the homelab repo).
2. This module refuses anything above the server-wide and per-printer
   `max_risk`, both of which are set in Git.

Every privileged attempt, allowed or not, is audited to SQLite and emitted as
a structured log line (which Datadog collects).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Protocol

logger = logging.getLogger("printer_agent.audit")


class RiskLevel(IntEnum):
    READ_ONLY = 0
    SAFE_AUTOMATION = 1
    LOW_RISK_WRITE = 2
    HIGH_RISK_WRITE = 3
    DANGEROUS = 4

    @classmethod
    def parse(cls, value: object) -> RiskLevel:
        if isinstance(value, RiskLevel):
            return value
        if isinstance(value, int):
            return cls(value)
        if isinstance(value, str):
            key = value.strip().upper().replace("-", "_")
            if key == "HIGH_RISK":
                key = "HIGH_RISK_WRITE"
            try:
                return cls[key]
            except KeyError as err:
                raise ValueError(f"unknown risk level {value!r}") from err
        raise ValueError(f"unknown risk level {value!r}")


class PolicyDeniedError(Exception):
    def __init__(self, reason: str, risk: RiskLevel, allowed: RiskLevel) -> None:
        super().__init__(reason)
        self.reason = reason
        self.risk = risk
        self.allowed = allowed


class PreconditionFailedError(Exception):
    """A write was authorized but the printer is not in a state to accept it."""

    def __init__(self, reason: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


class AuditSink(Protocol):
    def record_audit(self, entry: dict[str, Any]) -> None: ...


@dataclass(slots=True)
class Policy:
    max_risk: RiskLevel

    def authorize(
        self,
        *,
        action: str,
        printer_id: str,
        risk: RiskLevel,
        printer_max: RiskLevel,
    ) -> None:
        allowed = min(self.max_risk, printer_max)
        if risk > allowed:
            raise PolicyDeniedError(
                f"{action} on {printer_id} is {risk.name}; policy allows up to {allowed.name} "
                "(PRINTER_AGENT_MAX_RISK and printers.yaml policy.max_risk, both set in Git)",
                risk,
                allowed,
            )


class Auditor:
    def __init__(self, sink: AuditSink | None) -> None:
        self._sink = sink

    def record(
        self,
        *,
        action: str,
        printer_id: str,
        risk: RiskLevel,
        outcome: str,
        params: dict[str, Any] | None = None,
        detail: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "action": action,
            "printer": printer_id,
            "risk": risk.name,
            "outcome": outcome,
            "params": params or {},
            "detail": detail,
        }
        logger.info("audit %s", json.dumps(entry, sort_keys=True, default=str))
        from printer_agent.metrics import ACTIONS

        ACTIONS.labels(action, printer_id, risk.name, outcome).inc()
        if self._sink is not None:
            try:
                self._sink.record_audit(entry)
            except Exception:
                # Audit storage failing must be loud but must not mask the
                # outcome of the action itself; the log line above survives.
                logger.exception("failed to persist audit entry")
