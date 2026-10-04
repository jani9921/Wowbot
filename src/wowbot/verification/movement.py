"""Pure movement/arrival postcondition evaluation (V4-040)."""
from __future__ import annotations

import math
from typing import Any

from wowbot.runtime import FailureReason, VerificationResult


class MovementVerifier:
    """Evaluate arrival at a destination from before/after world position.

    No input, no controller mutation, no retries, no planner calls -- this
    only compares two already-captured snapshots' ``player_world_position``.
    """

    def evaluate(self, before: dict[str, Any], after: dict[str, Any], *,
                destination: tuple[float, float] | None,
                arrival_radius: float = 3.0) -> VerificationResult:
        if destination is None:
            return VerificationResult(False, 0.0, FailureReason.NO_ROUTE)

        after_position = after.get("player_world_position") or {}
        ax, ay = after_position.get("x"), after_position.get("y")
        if ax is None or ay is None:
            return VerificationResult(False, 0.0, FailureReason.STALE_OBSERVATION)

        distance = math.hypot(float(ax) - destination[0], float(ay) - destination[1])
        if distance <= arrival_radius:
            return VerificationResult(True, .9, None, ("within_arrival_radius",))

        before_position = before.get("player_world_position") or {}
        bx, by = before_position.get("x"), before_position.get("y")
        progressed = False
        if bx is not None and by is not None:
            before_distance = math.hypot(float(bx) - destination[0], float(by) - destination[1])
            progressed = distance < before_distance

        if progressed:
            return VerificationResult(False, .3, FailureReason.NO_PROGRESS, ("distance_decreasing",))
        return VerificationResult(False, .0, FailureReason.NO_PROGRESS)
