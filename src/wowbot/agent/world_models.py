"""Typed evidence-graph value objects shared by WorldModel and WorldQuery."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


@dataclass(frozen=True)
class Evidence:
    observation_id: str
    correlation_id: str
    source: str
    at: float
    expires: float
    value_json: str
    confidence: float
    reliability: float
    context_json: str
    independence_group: str
    sensor_tier: str
    tier_rank: int
    kind: str = ""
    related_entity: str | None = None
    related_quest: str | None = None
    related_objective: str | None = None

    @property
    def evidence_id(self) -> str:
        return f"{self.observation_id}:{self.source}:{self.at:.6f}"

    @property
    def observed_at(self) -> float:
        return self.at

    @property
    def expires_at(self) -> float:
        return self.expires

    @property
    def value(self):
        return json.loads(self.value_json)

    def is_fresh(self, now: float) -> bool:
        return now <= self.expires

    def age_ms(self, now: float) -> int:
        return max(0, round((now-self.at)*1000.))

    def effective_confidence(self, now: float) -> float:
        if not self.is_fresh(now):
            return 0.
        lifetime = max(1e-9, self.expires-self.at)
        freshness = max(0., min(1., (self.expires-now)/lifetime))
        return max(0., min(1., self.confidence*self.reliability*freshness))


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
