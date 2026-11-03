"""Typed evidence-graph value objects shared by WorldModel and WorldQuery."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from wowbot.evidence_contracts import Evidence


@dataclass(frozen=True)
class Belief:
    """Typed, immutable projection of fused evidence for one world-state key."""

    key: str
    status: str
    value: Any
    confidence: float
    evidence_refs: tuple[str, ...]
    contradictions: tuple[str, ...]
    source: str | None = None
    sensor_tier: str | None = None
    resolution: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)

    @classmethod
    def from_projection(cls, key: str, projection: dict) -> "Belief":
        return cls(
            key=key, status=str(projection.get("status") or "UNKNOWN"),
            value=projection.get("value"),
            confidence=float(projection.get("confidence") or 0.),
            evidence_refs=tuple(str(value) for value in projection.get("evidence") or ()),
            contradictions=tuple(str(value) for value in projection.get("contradictions") or ()),
            source=projection.get("source"), sensor_tier=projection.get("sensor_tier"),
            resolution=dict(projection.get("resolution") or {}),
            context=dict(projection.get("context") or {}),
        )

    @property
    def supported(self) -> bool:
        return self.status in {"SUPPORTED", "CONFIRMED"}


@dataclass(frozen=True)
class ContradictionRecord:
    key: str
    status: str
    resolution: str
    chosen_value_json: str
    supporting_observations: tuple[str, ...]
    contradicting_observations: tuple[str, ...]
    at: float


@dataclass(frozen=True)
class WorldRelation:
    relation_id: str
    subject: str
    predicate: str
    object: str
    confidence: float
    evidence: tuple[str, ...]
    status: str
    at: float
