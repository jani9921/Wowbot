"""Navigation-facing effects of an already verified terminal skill result."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Attempt, Outcome
from wowbot.runtime import FailureReason


MOVEMENT_SKILLS = frozenset({"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"})
ENTITY_SKILLS = frozenset({"INTERACT", "TALK", "COMBAT", "LOOT"})
REACHABILITY_FAILURES = frozenset({
    FailureReason.OUT_OF_RANGE, FailureReason.LINE_OF_SIGHT,
    FailureReason.TARGET_LOST, FailureReason.PATH_BLOCKED,
})


@dataclass(frozen=True)
class NavigationTerminalAssessment:
    events: tuple[tuple[str, dict], ...]
    recovery_succeeded: bool = False


class NavigationTerminalProcessor:
    """Report verified outcomes to the sole NavigationService authority."""

    def __init__(self, navigation) -> None:
        self.navigation = navigation

    def process(self, attempt: Attempt, outcome: Outcome, reason: str,
                failure_reason: FailureReason | None, before: dict, after: dict,
                *, latest_observation_id: str | None, now: float) -> NavigationTerminalAssessment:
        skill = attempt.proposal.skill
        guid = attempt.proposal.parameters.get("guid")
        events: list[tuple[str, dict]] = []
        recovery_succeeded = False
        recovery_movement = bool(
            skill == "RECOVER"
            or (skill == "MOVE" and attempt.proposal.parameters.get(
                "_stuck_recovery_waypoint")))
        if outcome == Outcome.SUCCESS:
            if skill in ENTITY_SKILLS:
                self.navigation.report_entity_success(guid, now)
            if skill in MOVEMENT_SKILLS | {"RECOVER"}:
                destination = attempt.proposal.parameters if skill in {"MOVE", "FOLLOW", "REACH_LOCATION"} else None
                self.navigation.observe_verified_move(before, after, destination)
                if recovery_movement:
                    self.navigation.mark_recovery()
                    recovery = self.navigation.report_recovery_result(success=True, now=now)
                    events.append(("STUCK_RECOVERY", {
                        "state": recovery.state.value, "reason": recovery.reason,
                        "correlation_id": recovery.correlation_id,
                    }))
                    self.navigation.cancel_movement()
                    recovery_succeeded = True
        elif outcome == Outcome.FAILURE:
            if skill in ENTITY_SKILLS and failure_reason in REACHABILITY_FAILURES:
                self.navigation.report_entity_failure(guid, failure_reason.value, now)
            if skill == "COMBAT" and failure_reason is FailureReason.LINE_OF_SIGHT:
                self.navigation.record_los_exhaustion(guid, after, now)
            if skill == "MOVE" and reason == "supported_stuck":
                claim = self.navigation.observe_failed_move(
                    before, after, attempt.proposal.parameters,
                    latest_observation_id or attempt.observation_id, now)
                if claim:
                    events.append(("OBSTACLE_EVIDENCE", claim))
                # Live 2026-10-04 09:09: after BACKWARD/JUMP freed the
                # character, the next route ran into the same rock (not in
                # the mmaps).  Mark it now -- not only at MARK_DANGER, which
                # the physical escapes precede -- so every replan detours.
                if self.navigation.mark_current_route_danger(
                        after, now, correlation_id=f"stuck:{attempt.action_id}"):
                    events.append(("OBSTACLE_MARKED", {
                        "correlation_id": attempt.action_id, "source": "SUPPORTED_STUCK"}))
            if recovery_movement:
                recovery = self.navigation.report_recovery_result(success=False, now=now)
                events.append(("STUCK_RECOVERY", {
                    "state": recovery.state.value, "action": recovery.action,
                    "reason": recovery.reason, "correlation_id": recovery.correlation_id,
                }))
                self.navigation.cancel_movement()
        return NavigationTerminalAssessment(tuple(events), recovery_succeeded)
