"""Typed WorldModel records that keep identity, location, role, state and appearance separate."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EntityIdentity:
    entity_id: str
    npc_id: int | None
    guids: tuple[str, ...]
    name: str | None
    unit_type: str | None
    first_seen: float
    last_seen: float


@dataclass(frozen=True)
class LocationObservation:
    observation_id: str
    cluster_id: str
    map_id: int | None
    x: float
    y: float
    z: float | None
    coordinate_space: str
    phase: str | None
    instance: str | int | None
    zone: str | None
    context: str
    source: str
    confidence: float
    observed_at: float


@dataclass
class LocationCluster:
    cluster_id: str
    map_id: int | None
    phase: str | None
    instance: str | int | None
    zone: str | None
    context: str
    coordinate_space: str
    center_x: float
    center_y: float
    center_z: float | None
    first_seen: float
    last_seen: float
    seen_count: int = 1
    confidence: float = 1.0
    observation_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RoleObservation:
    role_id: str
    role: str
    quest_id: str | int | None
    quest_revision: str | int | None
    player_context: str
    phase: str | None
    instance: str | int | None
    source: str
    confidence: float
    observed_at: float
    observation_id: str


@dataclass(frozen=True)
class EntityStateObservation:
    state_id: str
    values: dict[str, object]
    phase: str | None
    instance: str | int | None
    source: str
    observed_at: float
    observation_id: str


@dataclass(frozen=True)
class AppearanceObservation:
    appearance_id: str
    representation_space: str
    signature: dict[str, object]
    source: str
    observed_at: float
    observation_id: str
