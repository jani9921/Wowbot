"""Runtime composition for an already-active combat skill."""
from __future__ import annotations

from dataclasses import dataclass, field

from wowbot.runtime import FailureReason, SkillResult, SkillStatus, failure_reason_from_legacy
from .navigation_handoff import prepare, start_options, failure_detail


@dataclass(frozen=True)
class CombatRuntimeStep:
    commands: tuple = ()
    movement_lane: bool = False
    terminal_result: SkillResult | None = None
    event_type: str | None = None
    diagnostics: dict = field(default_factory=dict)
    set_segment_baseline: bool = False
    stop_movement: bool = False
    plan_pending: bool = False


class CombatRuntimeRunner:
    def __init__(self, navigation, combat_skill) -> None:
        self.navigation, self.combat_skill = navigation, combat_skill

    def continue_approach(self, active_state, state: dict, observation_id: str,
                          now: float, *, allow_route_queries=True) -> CombatRuntimeStep:
        # This is still the same COMBAT attempt; NavigationService owns the
        # movement, while the canonical combat FSM exposes the approach phase.
        preparation = prepare(self.navigation, active_state, state, now, allow_route_queries=allow_route_queries)
        if preparation.terminal:
            return CombatRuntimeStep(stop_movement=True, terminal_result=preparation.terminal)
        if preparation.pending:
            return CombatRuntimeStep(stop_movement=True, plan_pending=True)
        if hasattr(active_state, "phase"):
            active_state.phase = "APPROACH_TARGET"
        assessment = self.navigation.observe(state, observation_id, now, commanded=True)
        if assessment.terminal:
            detail = failure_detail(self.navigation, assessment) if not assessment.success else None
            movement = self.navigation.movement_snapshot()
            self.navigation.cancel_movement()
            if not assessment.success:
                return CombatRuntimeStep(stop_movement=True, terminal_result=SkillResult(
                    SkillStatus.FAILURE, reason=failure_reason_from_legacy(assessment.reason),
                    retryable=True, replan_required=True,
                    metadata={"legacy_reason": assessment.reason, 'navigation_failure':detail}))
            resumed = self.combat_skill.resume_after_approach(active_state, state, now)
            if resumed.status is not SkillStatus.RUNNING:
                return CombatRuntimeStep(stop_movement=True, terminal_result=resumed)
            if resumed.metadata.get('approach_request') or resumed.metadata.get('los_reposition_request'):
                return self.step_verification(state,resumed,observation_id,now,
                    allow_route_queries=allow_route_queries,
                    deadline=getattr(getattr(active_state,'attempt',None),'deadline',None))
            return CombatRuntimeStep(
                tuple(resumed.commands), False, event_type="COMBAT_APPROACH_ARRIVED",
                diagnostics={"movement": movement}, stop_movement=True)
        return CombatRuntimeStep(
            tuple(self.navigation.command(state, observation_id, now)), True,
            event_type="COMBAT_APPROACH_CONTROL_UPDATE",
            diagnostics={"movement": self.navigation.movement_snapshot()})

    def step_verification(self, state: dict, result: SkillResult,
                          observation_id: str, now: float, *, allow_route_queries=True,
                          deadline=None) -> CombatRuntimeStep:
        if deadline is not None and now >= deadline:
            self.navigation.cancel_movement()
            return CombatRuntimeStep(stop_movement=True, terminal_result=SkillResult(
                SkillStatus.FAILURE, FailureReason.TIMEOUT, retryable=True, replan_required=True))
        los_reposition = result.metadata.get("los_reposition_request")
        if los_reposition:
            destination = self.navigation.reposition_for_los(
                state, los_reposition.get("expected_guid"), observation_id, now,
                desired_range=los_reposition.get("stop_distance", 4.5),
                **start_options(allow_route_queries=allow_route_queries, end=deadline))
            if destination is None:
                return CombatRuntimeStep(terminal_result=SkillResult(
                    SkillStatus.FAILURE, reason=FailureReason.LINE_OF_SIGHT,
                    retryable=True, replan_required=True,
                    metadata={"target_unreachable": True,
                              "los_recovery_phase": "LOCAL_REPLAN_UNAVAILABLE"}))
            return CombatRuntimeStep(
                tuple(self.navigation.command(state, observation_id, now)), True,
                event_type="COMBAT_LOS_REPLAN_STARTED",
                diagnostics={"destination": destination,
                             "navigation_mode": "REPOSITION_FOR_LOS"},
                set_segment_baseline=True, stop_movement=not allow_route_queries,
                plan_pending=not allow_route_queries)
        approach = result.metadata.get("approach_request")
        if approach:
            destination = self.navigation.move_to_entity(
                state, approach.get("expected_guid"), observation_id, now,
                stop_distance=approach.get("stop_distance", 3.5),
                **start_options(allow_route_queries=allow_route_queries, end=deadline))
            if destination is None:
                return CombatRuntimeStep(terminal_result=SkillResult(
                    SkillStatus.FAILURE, reason=FailureReason.TARGET_MOVED,
                    retryable=True, replan_required=True,
                    metadata={"legacy_reason": "target_moved"}))
            return CombatRuntimeStep(
                tuple(self.navigation.command(state, observation_id, now)), True,
                event_type="COMBAT_APPROACH_STARTED",
                diagnostics={"destination": destination}, set_segment_baseline=True,
                stop_movement=not allow_route_queries, plan_pending=not allow_route_queries)
        local = result.metadata.get("local_navigation_request")
        if local:
            commands = tuple(self.navigation.local_combat_reposition(state, local))
            if not commands:
                return CombatRuntimeStep(terminal_result=SkillResult(
                    SkillStatus.FAILURE, reason=FailureReason.IDENTITY_UNCERTAIN,
                    retryable=True, replan_required=True,
                    metadata={"legacy_reason": "identity_uncertain"}))
            return CombatRuntimeStep(commands, True,
                                     event_type="COMBAT_LOCAL_NAVIGATION_UPDATE",
                                     diagnostics={"request": local,
                                                  "navigation": self.navigation.snapshot(now)})
        if result.commands:
            return CombatRuntimeStep(tuple(result.commands), False,
                                     event_type="COMBAT_ROTATION_UPDATE",
                                     diagnostics={"metadata": result.metadata})
        return CombatRuntimeStep()
