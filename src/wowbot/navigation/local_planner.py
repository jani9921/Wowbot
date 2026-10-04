"""Traversability-first local planning for a previously chosen corridor."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .contracts import LocalMotionPlan, PathCorridor


@dataclass(frozen=True, slots=True)
class LocalPlannerPolicy:
    plan_valid_for_ms: int = 250
    blocked_confidence: float = 0.65


class LocalNavigator:
    """Choose a local waypoint from cost evidence, never from object semantics.

    World3D sectors are camera-relative.  Without a calibrated projection this
    class will *not* manufacture an off-corridor world coordinate; a confirmed
    blocked centre requests a bounded local replan instead.  This avoids the
    old failure mode where an arbitrary screen cue became a movement target.
    """

    def __init__(self, policy: LocalPlannerPolicy | None = None) -> None:
        self.policy = policy or LocalPlannerPolicy()

    def plan(self, state: dict[str, Any], corridor: PathCorridor | None, *,
             destination: dict[str, Any] | None = None) -> LocalMotionPlan:
        waypoint = self._next_waypoint(state, corridor, destination)
        if waypoint is None:
            return LocalMotionPlan(None, None, "HOLD_AND_OBSERVE", None,
                                   self.policy.plan_valid_for_ms, "LOCAL_PLANNER")
        sector_scores = self._sector_scores(state.get("local_traversability"))
        center = sector_scores.get("CENTER")
        if center and center["blocked"]:
            bypass = self._best_bypass(sector_scores)
            if bypass is None:
                return LocalMotionPlan(None, waypoint, "REQUEST_LOCAL_REPLAN", None,
                                       self.policy.plan_valid_for_ms, "LOCAL_PLANNER")
            # This is a *relative* preference, not an invented world point.
            waypoint = {**waypoint, "local_bypass_preference": bypass,
                        "traversability_evidence": center["evidence"]}
        player = self._player(state)
        heading, vector = self._heading_and_vector(player, waypoint)
        return LocalMotionPlan(heading, waypoint, "FOLLOW_CORRIDOR", vector,
                               self.policy.plan_valid_for_ms, "LOCAL_PLANNER")

    def compute_local_intent(self, state: dict[str, Any], corridor: PathCorridor | None,
                             *, destination: dict[str, Any] | None = None) -> LocalMotionPlan:
        return self.plan(state, corridor, destination=destination)

    @staticmethod
    def correct_heading(current: float, desired: float, *, deadzone: float = .04) -> float:
        error = math.atan2(math.sin(desired-current), math.cos(desired-current))
        return 0.0 if abs(error) <= max(0., deadzone) else error

    def approach_target(self, state: dict[str, Any], target: dict[str, Any],
                        corridor: PathCorridor | None = None) -> LocalMotionPlan:
        return self.plan(state, corridor, destination=target)

    def avoid_immediate_obstacle(self, state: dict[str, Any]) -> str | None:
        scores = self._sector_scores(state.get("local_traversability"))
        center = scores.get("CENTER")
        return self._best_bypass(scores) if center and center["blocked"] else None

    @staticmethod
    def stop_at_range(distance: float | None, desired_range: float | None) -> bool:
        return (isinstance(distance, (int, float)) and isinstance(desired_range, (int, float))
                and float(distance) <= max(0., float(desired_range)))

    def _sector_scores(self, raw: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(raw, dict) or raw.get("schema") != "WORLD3D_TRAVERSABILITY_V5":
            return {}
        result: dict[str, dict[str, Any]] = {}
        for sector in raw.get("sectors") or ():
            if not isinstance(sector, dict):
                continue
            key = str(sector.get("sector") or "")
            canonical = "CENTER" if key == "CENTER" else "LEFT" if key == "CENTER_LEFT" else "RIGHT" if key == "CENTER_RIGHT" else None
            if canonical is None:
                continue
            confidence = float(sector.get("obstacle_confidence") or 0.0)
            result[canonical] = {
                "score": max(0.0, min(1.0, float(sector.get("traversability_score") or 0.0))),
                "blocked": sector.get("state") == "BLOCKED" and sector.get("obstacle_lifecycle") == "CONFIRMED" and confidence >= self.policy.blocked_confidence,
                "evidence": tuple(sector.get("evidence") or ()),
            }
        return result

    @staticmethod
    def _best_bypass(scores: dict[str, dict[str, Any]]) -> str | None:
        choices = [(item["score"], side) for side, item in scores.items()
                   if side in {"LEFT", "RIGHT"} and not item["blocked"]]
        return max(choices)[1] if choices and max(choices)[0] > 0.0 else None

    @staticmethod
    def _player(state: dict[str, Any]) -> dict[str, float] | None:
        raw = state.get("player_world_position") or state.get("position") or {}
        try:
            return {"x": float(raw["x"]), "y": float(raw["y"])}
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _next_waypoint(state: dict[str, Any], corridor: PathCorridor | None,
                       destination: dict[str, Any] | None) -> dict[str, Any] | None:
        if corridor and corridor.segments:
            return dict(corridor.segments[0]["to"])
        return dict(destination) if isinstance(destination, dict) and "x" in destination and "y" in destination else None

    @staticmethod
    def _heading_and_vector(player: dict[str, float] | None, waypoint: dict[str, Any]) -> tuple[float | None, dict[str, float] | None]:
        if player is None:
            return None, None
        try:
            dx, dy = float(waypoint["x"]) - player["x"], float(waypoint["y"]) - player["y"]
        except (KeyError, TypeError, ValueError):
            return None, None
        length = math.hypot(dx, dy)
        if length <= 1e-8:
            return None, {"x": 0.0, "y": 0.0}
        return math.atan2(dy, dx), {"x": dx / length, "y": dy / length}


# Source-compatible import name; both names refer to the same class/authority.
LocalPlanner = LocalNavigator
