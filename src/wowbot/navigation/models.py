from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional

from wowbot.vision.models import WorldPosition


class DestinationKind(StrEnum):
    POINT = "POINT"
    AREA = "AREA"
    ZONE = "ZONE"
    TARGET = "TARGET"


@dataclass(frozen=True, slots=True)
class ArrivalCondition:
    condition_type: str
    tolerance: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DestinationIntent:
    kind: DestinationKind
    position: Optional[WorldPosition]
    purpose: str
    arrival: ArrivalCondition
    target_id: Optional[str] = None
    zone: Optional[str] = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.position is None and self.zone is None:
            raise ValueError("DestinationIntent requires position or zone")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")


class MovementMode(StrEnum):
    WALK = "WALK"


@dataclass(frozen=True, slots=True)
class MovementIntent:
    mode: MovementMode
    desired_heading_deg: Optional[float]
    target_position: Optional[WorldPosition]
    stop_distance: float
    reason: str


class NavigationStatus(StrEnum):
    IDLE = "IDLE"
    RESOLVING = "RESOLVING"
    ROUTING = "ROUTING"
    READY = "READY"
    NAVIGATING = "NAVIGATING"
    STUCK = "STUCK"
    REPLANNING = "REPLANNING"
    ARRIVED = "ARRIVED"
    FAILED = "FAILED"


@dataclass(slots=True)
class NavigationPlan:
    destination: DestinationIntent
    route_node_ids: list[str]
    revision: int = 1
    status: NavigationStatus = NavigationStatus.READY
    current_index: int = 0

    @property
    def current_node_id(self) -> Optional[str]:
        if 0 <= self.current_index < len(self.route_node_ids):
            return self.route_node_ids[self.current_index]
        return None
