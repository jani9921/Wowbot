"""Runtime composition for an already-active loot skill."""
from __future__ import annotations

from dataclasses import dataclass, field

from wowbot.runtime import FailureReason, SkillResult, SkillStatus, failure_reason_from_legacy
from .navigation_handoff import prepare, start_options, failure_detail, deadline


@dataclass(frozen=True)
class LootRuntimeStep:
    commands: tuple = ()
    movement_lane: bool = False
    terminal_result: SkillResult | None = None
    event_type: str | None = None
    diagnostics: dict = field(default_factory=dict)
    set_segment_baseline: bool = False
    stop_movement: bool = False
    plan_pending: bool = False


class LootRuntimeRunner:
    """Own loot verification and its bounded corpse-approach subflow.

    The runner produces commands and typed results only.  Input dispatch and
    active-skill finalization remain the Agent's single authority.
    """

    def __init__(self, navigation, loot_skill) -> None:
        self.navigation, self.loot_skill = navigation, loot_skill

    def continue_approach(self, active_state, state: dict, observation_id: str,
                          now: float, *, allow_route_queries=True) -> LootRuntimeStep:
        preparation = prepare(self.navigation, active_state, state, now, allow_route_queries=allow_route_queries)
        if preparation.terminal:
            return LootRuntimeStep(stop_movement=True, terminal_result=preparation.terminal)
        if preparation.pending:
            return LootRuntimeStep(stop_movement=True, plan_pending=True)
        assessment = self.navigation.observe(state, observation_id, now, commanded=True)
        if assessment.terminal:
            detail = failure_detail(self.navigation, assessment) if not assessment.success else None
            movement = self.navigation.movement_snapshot()
            self.navigation.cancel_movement()
            if not assessment.success:
                return LootRuntimeStep(stop_movement=True, terminal_result=SkillResult(
                    SkillStatus.FAILURE, reason=failure_reason_from_legacy(assessment.reason),
                    retryable=True, replan_required=True,
                    metadata={"legacy_reason": assessment.reason, 'navigation_failure':detail}))
            resumed = self.loot_skill.resume_after_approach(active_state, state)
            if resumed.status is not SkillStatus.RUNNING:
                return LootRuntimeStep(stop_movement=True, terminal_result=resumed)
            return LootRuntimeStep(
                tuple(resumed.commands), False, event_type="LOOT_APPROACH_ARRIVED",
                diagnostics={"movement": movement}, stop_movement=True)
        return LootRuntimeStep(
            tuple(self.navigation.command(state, observation_id, now)), True,
            event_type="LOOT_APPROACH_CONTROL_UPDATE",
            diagnostics={"movement": self.navigation.movement_snapshot()})

    def step_verification(self, active_state, state: dict, observation_id: str,
                          now: float, *, allow_route_queries=True) -> LootRuntimeStep:
        end = deadline(active_state)
        if end is not None and now >= end:
            self.navigation.cancel_movement()
            return LootRuntimeStep(stop_movement=True, terminal_result=SkillResult(
                SkillStatus.FAILURE,FailureReason.TIMEOUT,retryable=True,replan_required=True))
        result = self.loot_skill.verify(active_state, state, now)
        if result.status is not SkillStatus.RUNNING:
            return LootRuntimeStep(terminal_result=result)
        if result.commands:
            # Hover-confirm-click on the corpse (see skills/hover_confirm.py).
            return LootRuntimeStep(tuple(result.commands), False,
                                   event_type="LOOT_HOVER_CONFIRM_UPDATE")
        approach = result.metadata.get("approach_request")
        if not approach:
            return LootRuntimeStep()
        destination = self.navigation.move_to_entity(
            state, approach.get("corpse_guid"), observation_id, now,
            stop_distance=approach.get("stop_distance", 3.5), allow_dead=True,
            **start_options(active_state, allow_route_queries=allow_route_queries))
        if destination is None:
            return LootRuntimeStep(terminal_result=SkillResult(
                SkillStatus.FAILURE, reason=FailureReason.CORPSE_NOT_FOUND,
                retryable=True, replan_required=True,
                metadata={"legacy_reason": "corpse_not_found"}))
        return LootRuntimeStep(
            tuple(self.navigation.command(state, observation_id, now)), True,
            event_type="LOOT_APPROACH_STARTED",
            diagnostics={"destination": destination}, set_segment_baseline=True,
            stop_movement=not allow_route_queries, plan_pending=not allow_route_queries)
