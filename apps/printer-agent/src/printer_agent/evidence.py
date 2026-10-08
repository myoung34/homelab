"""Evidence model shared by every analysing tool.

The agent must be able to tell the operator *how* it knows something. Every
finding therefore carries a certainty level and the source it came from, and
diagnoses keep a separate list of what could not be determined.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Certainty(StrEnum):
    """How strongly a statement is supported.

    OBSERVED  - read directly from a source (log line, API field).
    INFERRED  - follows deterministically from observations.
    LIKELY    - best-supported hypothesis; evidence for, little against.
    POSSIBLE  - consistent with the evidence but not singled out by it.
    UNKNOWN   - could not be determined from available data.
    """

    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    LIKELY = "LIKELY"
    POSSIBLE = "POSSIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class Evidence:
    statement: str
    certainty: Certainty
    source: str
    timestamp: float | None = None
    # True when the timestamp was interpolated (e.g. a klippy.log line placed
    # between two Stats lines) rather than recorded with the event.
    time_approximate: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["certainty"] = str(self.certainty)
        if self.timestamp is not None:
            d["time_iso"] = iso(self.timestamp)
        if not self.data:
            d.pop("data")
        if not self.time_approximate:
            d.pop("time_approximate")
        return d


@dataclass(slots=True)
class Hypothesis:
    failure_class: str
    summary: str
    certainty: Certainty
    score: float
    supporting: list[Evidence] = field(default_factory=list)
    contradicting: list[Evidence] = field(default_factory=list)
    next_test: str | None = None
    next_test_risk: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_class": self.failure_class,
            "summary": self.summary,
            "certainty": str(self.certainty),
            "score": round(self.score, 2),
            "supporting": [e.to_dict() for e in self.supporting],
            "contradicting": [e.to_dict() for e in self.contradicting],
            "next_test": self.next_test,
            "next_test_risk": self.next_test_risk,
        }


def certainty_for_score(score: float) -> Certainty:
    """Map a hypothesis score (0..1) onto the certainty vocabulary.

    Hypotheses never reach OBSERVED/INFERRED: those describe facts, and a
    hypothesis is by definition an explanation of facts.
    """
    if score >= 0.7:
        return Certainty.LIKELY
    if score >= 0.25:
        return Certainty.POSSIBLE
    return Certainty.UNKNOWN


def iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
