from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional

from wowbot.vision.models import MinimapObservation, WorldObservation, WorldPosition
from .models import MovementIntent, MovementMode


@dataclass(frozen=True, slots=True)
class LocalNavigationDecision:
    target_position: Optional[WorldPosition]
    desired_heading_deg: Optional[float]
    distance: Optional[float]
    blocked: bool
    confidence: float
    reason: str


class LocalNavigator:
    """Turns local minimap/world observations into semantic MovementIntent."""

    def decide(
        self,
        *,
        player_position: WorldPosition,
        waypoint: Optional[WorldPosition],
        minimap: Optional[MinimapObservation],
        world: Optional[WorldObservation],
    ) -> LocalNavigationDecision:
        if waypoint is None:
            return LocalNavigationDecision(None, None, None, False, 0.0, "no_waypoint")
        dx, dy = waypoint.x - player_position.x, waypoint.y - player_position.y
        distance = math.hypot(dx, dy)
        heading = math.degrees(math.atan2(dy, dx)) % 360.0
        blocked = bool(world and world.obstacles)
        confidence = 0.8 if minimap is not None else 0.55
        if blocked:
            confidence = min(confidence, 0.45)
        return LocalNavigationDecision(waypoint, heading, distance, blocked, confidence, "local_guidance")

    @staticmethod
    def to_movement_intent(decision: LocalNavigationDecision, stop_distance: float = 0.05) -> MovementIntent:
        return MovementIntent(
            mode=MovementMode.WALK,
            desired_heading_deg=decision.desired_heading_deg,
            target_position=decision.target_position,
            stop_distance=stop_distance,
            reason=decision.reason,
        )
