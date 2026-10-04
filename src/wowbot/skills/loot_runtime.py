"""Runtime composition for an already-active loot skill."""
from __future__ import annotations

from dataclasses import dataclass, field

from wowbot.runtime import FailureReason, SkillResult, SkillStatus, failure_reason_from_legacy


@dataclass(frozen=True)
class LootRuntimeStep:
    commands: tuple = ()
    movement_lane: bool = False
    terminal_result: SkillResult | None = None
    event_type: str | None = None
    diagnostics: dict = field(default_factory=dict)
    set_segment_baseline: bool = False


class LootRuntimeRunner:
    """Own loot verification and its bounded corpse-approach subflow.

    The runner produces commands and typed results only.  Input dispatch and
    active-skill finalization remain the Agent's single authority.
    """

    def __init__(self, navigation, loot_skill) -> None:
        self.navigation, self.loot_skill = navigation, loot_skill

    def continue_approach(self, active_state, state: dict, observation_id: str,
                          now: float) -> LootRuntimeStep:
        assessment = self.navigation.observe(state, observation_id, now, commanded=True)
        if assessment.terminal:
            self.navigation.cancel_movement()
            if not assessment.success:
                return LootRuntimeStep(terminal_result=SkillResult(
                    SkillStatus.FAILURE, reason=failure_reason_from_legacy(assessment.reason),
                    retryable=True, replan_required=True,
                    metadata={"legacy_reason": assessment.reason}))
            resumed = self.loot_skill.resume_after_approach(active_state, state)
            if resumed.status is not SkillStatus.RUNNING:
                return LootRuntimeStep(terminal_result=resumed)
            return LootRuntimeStep(
                tuple(resumed.commands), False, event_type="LOOT_APPROACH_ARRIVED",
                diagnostics={"movement": self.navigation.movement_snapshot()})
        return LootRuntimeStep(
            tuple(self.navigation.command(state, observation_id, now)), True,
            event_type="LOOT_APPROACH_CONTROL_UPDATE",
            diagnostics={"movement": self.navigation.movement_snapshot()})

    def step_verification(self, active_state, state: dict, observation_id: str,
                          now: float) -> LootRuntimeStep:
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
            stop_distance=approach.get("stop_distance", 3.5), allow_dead=True)
        if destination is None:
            return LootRuntimeStep(terminal_result=SkillResult(
                SkillStatus.FAILURE, reason=FailureReason.CORPSE_NOT_FOUND,
                retryable=True, replan_required=True,
                metadata={"legacy_reason": "corpse_not_found"}))
        return LootRuntimeStep(
            tuple(self.navigation.command(state, observation_id, now)), True,
            event_type="LOOT_APPROACH_STARTED",
            diagnostics={"destination": destination}, set_segment_baseline=True)
