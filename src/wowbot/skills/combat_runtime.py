"""Runtime composition for an already-active combat skill."""
from __future__ import annotations

from dataclasses import dataclass, field

from wowbot.runtime import FailureReason, SkillResult, SkillStatus, failure_reason_from_legacy


@dataclass(frozen=True)
class CombatRuntimeStep:
    commands: tuple = ()
    movement_lane: bool = False
    terminal_result: SkillResult | None = None
    event_type: str | None = None
    diagnostics: dict = field(default_factory=dict)
    set_segment_baseline: bool = False


class CombatRuntimeRunner:
    def __init__(self, navigation, combat_skill) -> None:
        self.navigation, self.combat_skill = navigation, combat_skill

    def continue_approach(self, active_state, state: dict, observation_id: str,
                          now: float) -> CombatRuntimeStep:
        # This is still the same COMBAT attempt; NavigationService owns the
        # movement, while the canonical combat FSM exposes the approach phase.
        if hasattr(active_state, "phase"):
            active_state.phase = "APPROACH_TARGET"
        assessment = self.navigation.observe(state, observation_id, now, commanded=True)
        if assessment.terminal:
            self.navigation.cancel_movement()
            if not assessment.success:
                return CombatRuntimeStep(terminal_result=SkillResult(
                    SkillStatus.FAILURE, reason=failure_reason_from_legacy(assessment.reason),
                    retryable=True, replan_required=True,
                    metadata={"legacy_reason": assessment.reason}))
            resumed = self.combat_skill.resume_after_approach(active_state, state, now)
            if resumed.status is not SkillStatus.RUNNING:
                return CombatRuntimeStep(terminal_result=resumed)
            return CombatRuntimeStep(
                tuple(resumed.commands), False, event_type="COMBAT_APPROACH_ARRIVED",
                diagnostics={"movement": self.navigation.movement_snapshot()})
        return CombatRuntimeStep(
            tuple(self.navigation.command(state, observation_id, now)), True,
            event_type="COMBAT_APPROACH_CONTROL_UPDATE",
            diagnostics={"movement": self.navigation.movement_snapshot()})

    def step_verification(self, state: dict, result: SkillResult,
                          observation_id: str, now: float) -> CombatRuntimeStep:
        los_reposition = result.metadata.get("los_reposition_request")
        if los_reposition:
            destination = self.navigation.reposition_for_los(
                state, los_reposition.get("expected_guid"), observation_id, now,
                desired_range=los_reposition.get("stop_distance", 4.5))
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
                set_segment_baseline=True)
        approach = result.metadata.get("approach_request")
        if approach:
            destination = self.navigation.move_to_entity(
                state, approach.get("expected_guid"), observation_id, now,
                stop_distance=approach.get("stop_distance", 3.5))
            if destination is None:
                return CombatRuntimeStep(terminal_result=SkillResult(
                    SkillStatus.FAILURE, reason=FailureReason.TARGET_MOVED,
                    retryable=True, replan_required=True,
                    metadata={"legacy_reason": "target_moved"}))
            return CombatRuntimeStep(
                tuple(self.navigation.command(state, observation_id, now)), True,
                event_type="COMBAT_APPROACH_STARTED",
                diagnostics={"destination": destination}, set_segment_baseline=True)
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
