"""V5 navigation data contracts; these objects never own physical input."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import math


_MODES = frozenset({"MOVE_TO_LOCATION", "APPROACH_ENTITY", "FOLLOW_ENTITY",
                    "REPOSITION_FOR_LOS", "REPOSITION_FOR_FACING", "SEARCH_REGION", "ESCORT"})


@dataclass(frozen=True, slots=True)
class ArrivalEnvelope:
    radius: float | None = None
    desired_range: float | None = None

    def __post_init__(self) -> None:
        if self.radius is not None and self.radius < 0:
            raise ValueError("arrival radius must be non-negative")
        if self.desired_range is not None and self.desired_range < 0:
            raise ValueError("desired range must be non-negative")


@dataclass(frozen=True, slots=True)
class NavigationRequest:
    request_id: str
    correlation_id: str
    mode: str
    destination: dict[str, Any]
    target_entity_id: str | None = None
    arrival: ArrivalEnvelope = field(default_factory=ArrivalEnvelope)
    avoid_combat: bool = False
    allow_combat: bool = False
    priority: int = 0
    timeout: float | None = None

    def __post_init__(self) -> None:
        if not self.request_id or not self.correlation_id:
            raise ValueError("navigation request requires request and correlation IDs")
        if self.mode not in _MODES:
            raise ValueError(f"unsupported navigation mode: {self.mode}")
        if not isinstance(self.destination, dict):
            raise ValueError("navigation destination must be a mapping")
        if self.timeout is not None and (not math.isfinite(float(self.timeout)) or self.timeout <= 0):
            raise ValueError("navigation timeout must be a positive finite duration")
        if self.avoid_combat and self.allow_combat:
            raise ValueError("avoid_combat and allow_combat cannot both be true")


@dataclass(frozen=True, slots=True)
class GlobalRoute:
    route_id: str
    anchors: tuple[dict[str, Any], ...]
    regions: tuple[dict[str, Any], ...]
    cost: float
    confidence: float
    created_at: float
    valid_until: float


@dataclass(frozen=True, slots=True)
class PathCorridor:
    corridor_id: str
    route_id: str
    segments: tuple[dict[str, Any], ...]
    confidence: float
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LocalMotionPlan:
    desired_heading: float | None
    local_waypoint: dict[str, Any] | None
    motion_mode: str
    expected_progress_vector: dict[str, float] | None
    valid_for_ms: int
    source: str = "LOCAL_PLANNER"
