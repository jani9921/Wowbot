"""Immutable evidence values; no agent, sensor, planner or input ownership."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import math

from .context_contracts import SessionContext


class EvidenceValidity(StrEnum):
    """Temporal validity only; VALID does not establish source/input authority."""

    VALID = "VALID"
    FUTURE = "FUTURE"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"


class EvidenceCompleteness(StrEnum):
    UNKNOWN = "UNKNOWN"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"


class EvidenceDirection(StrEnum):
    UNKNOWN = "UNKNOWN"
    CLIENT_TO_SERVER = "CLIENT_TO_SERVER"
    SERVER_TO_CLIENT = "SERVER_TO_CLIENT"


def finite_time(value) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


@dataclass(frozen=True, slots=True)
class SourceLineage:
    producer: str | None = None
    parent_observation_ids: tuple[str, ...] = ()
    root_observation_ids: tuple[str, ...] = ()
    event_id: str | None = None
    direction: EvidenceDirection = EvidenceDirection.UNKNOWN
    game_build: int | None = None
    payload_layout: str | None = None
    source_timestamp: float | None = None
    correlation_uncertain: bool = False

    def __post_init__(self):
        for ids in (self.parent_observation_ids, self.root_observation_ids):
            if (type(ids) is not tuple or len(ids) > 64
                    or any(type(value) is not str or not value.strip() or len(value) > 256 for value in ids)):
                raise ValueError("bounded immutable observation IDs required")
        if not isinstance(self.direction, EvidenceDirection):
            raise ValueError("explicit evidence direction required")
        for value in (self.producer, self.event_id, self.payload_layout):
            if value is not None and (type(value) is not str or not value.strip() or len(value) > 256):
                raise ValueError("bounded textual provenance required")
        if self.game_build is not None and (type(self.game_build) is not int or self.game_build <= 0):
            raise ValueError("invalid source build")
        if self.source_timestamp is not None and not finite_time(self.source_timestamp):
            raise ValueError("invalid source timestamp")
        if type(self.correlation_uncertain) is not bool:
            raise ValueError("explicit correlation state required")

    def as_dict(self, *, limit: int = 64) -> dict:
        return {"producer": self.producer, "parent_observation_ids": list(self.parent_observation_ids[:limit]),
                "root_observation_ids": list(self.root_observation_ids[:limit]), "event_id": self.event_id,
                "direction": self.direction.value, "game_build": self.game_build,
                "payload_layout": self.payload_layout, "source_timestamp": self.source_timestamp,
                "correlation_uncertain": self.correlation_uncertain,
                "lineage_truncated": len(self.parent_observation_ids) > limit or len(self.root_observation_ids) > limit}


@dataclass(frozen=True)
class Evidence:
    # Positional fields remain compatible with agent.world_models.Evidence.
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
    sampled_at_monotonic: float | None = None
    lineage: SourceLineage | None = None
    completeness: EvidenceCompleteness = EvidenceCompleteness.UNKNOWN
    invalid_reason: str | None = None
    _time_valid: bool = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if self.lineage is not None and not isinstance(self.lineage, SourceLineage):
            raise ValueError("immutable source lineage required")
        if not isinstance(self.completeness, EvidenceCompleteness):
            raise ValueError("explicit completeness required")
        observed = self.observed_at
        object.__setattr__(self, "_time_valid", not self.invalid_reason
            and all(finite_time(t) for t in (self.at, observed, self.expires))
            and observed <= self.at and observed <= self.expires)

    @property
    def evidence_id(self) -> str:
        identity = f"{self.observation_id}:{self.source}:{self.at:.6f}"
        return f"{identity}:{self.kind}" if self.kind else identity

    @property
    def observed_at(self) -> float:
        return self.at if self.sampled_at_monotonic is None else self.sampled_at_monotonic

    @property
    def received_at(self) -> float:
        return self.at

    @property
    def expires_at(self) -> float:
        return self.expires

    @property
    def value(self):
        return json.loads(self.value_json)

    @property
    def session_context(self) -> SessionContext | None:
        try:
            return SessionContext.from_mapping(json.loads(self.context_json))
        except (ValueError, TypeError):
            return None

    def validity(self, now: float) -> EvidenceValidity:
        if not self._time_valid or not finite_time(now):
            return EvidenceValidity.INVALID
        if now > self.expires:
            return EvidenceValidity.EXPIRED
        if now < self.at or now < self.observed_at:
            return EvidenceValidity.FUTURE
        return EvidenceValidity.VALID

    def is_fresh(self, now: float) -> bool:
        return self.validity(now) is EvidenceValidity.VALID

    def age_ms(self, now: float) -> int:
        if not finite_time(now) or not finite_time(self.observed_at):
            return 0
        return max(0, round((now-self.observed_at)*1000.))

    def effective_confidence(self, now: float) -> float:
        if not self.is_fresh(now) or not all(finite_time(v) for v in (self.confidence, self.reliability)):
            return 0.
        lifetime = max(1e-9, self.expires-self.observed_at)
        freshness = max(0., min(1., (self.expires-now)/lifetime))
        return max(0., min(1., self.confidence*self.reliability*freshness))

    def correlation_tokens(self) -> frozenset[tuple[str, str]]:
        tokens = {("group", self.independence_group), ("observation", self.observation_id)}
        if self.lineage is not None:
            tokens.update(("observation", value) for value in self.lineage.parent_observation_ids)
            tokens.update(("observation", value) for value in self.lineage.root_observation_ids)
            if self.lineage.event_id:
                tokens.add(("event", self.lineage.event_id))
            if self.lineage.correlation_uncertain:
                tokens.add(("uncertain_lineage", "shared"))
        return frozenset(tokens)


def independent_evidence(entries, *, priority_key=None) -> list[Evidence]:
    """One strongest/current vote per connected ancestry component.

    Different wrappers and partially overlapping root sets cannot turn one
    observation into several votes. Only suppresses correlation; it never
    changes a source's authority tier or supplies missing facts.
    """
    entries = list(entries)
    parents = list(range(len(entries)))
    owners: dict[tuple[str, str], int] = {}

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    # Token indexing avoids pairwise component comparisons on every belief
    # projection. Union-find still handles a late bridge across several roots.
    for index, entry in enumerate(entries):
        for token in entry.correlation_tokens():
            other = owners.setdefault(token, index)
            a, b = root(index), root(other)
            if a != b:
                parents[a] = b
    winners = {}
    for index, entry in enumerate(entries):
        identity = root(index)
        priority = (priority_key(entry) if priority_key is not None else
                    (entry.tier_rank, entry.reliability*entry.confidence, entry.observed_at, entry.at))
        current = winners.get(identity)
        if current is None or priority > current[0]:
            winners[identity] = priority, entry
    return [entry for _, entry in winners.values()]
