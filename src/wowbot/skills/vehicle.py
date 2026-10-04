"""Vehicle override skill and rotation guard (V4-055).

Entering a vehicle may replace normal action bindings. This module adds
the missing named capability -- detect VEHICLE_OVERRIDE, cancel
incompatible normal combat/movement assumptions, use vehicle-specific
configured actions, verify quest progress, and (on exit) invalidate the
vehicle action state and restore normal control context. Vehicle-specific
bindings are configured externally per spec ("use vehicle-specific
configured actions"); this skill sequences the lifecycle around them, it
does not invent the bindings.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from wowbot.agent.models import Command
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus
from wowbot.verification import QuestProgressVerifier


class VehiclePhase(StrEnum):
    DETECT_OVERRIDE = "DETECT_OVERRIDE"
    CANCEL_INCOMPATIBLE_ASSUMPTIONS = "CANCEL_INCOMPATIBLE_ASSUMPTIONS"
    USE_VEHICLE_ACTIONS = "USE_VEHICLE_ACTIONS"
    VERIFY_QUEST_PROGRESS = "VERIFY_QUEST_PROGRESS"
    EXIT_RESTORE_CONTEXT = "EXIT_RESTORE_CONTEXT"


def is_vehicle_override_active(state: Mapping[str, Any]) -> bool:
    """True while VEHICLE_OVERRIDE (or an equivalent UI/context change) is active."""
    return bool(state.get("in_vehicle") or state.get("vehicle_ui") or state.get("vehicle_camera"))


def rotation_allowed(state: Mapping[str, Any]) -> bool:
    """Guard against normal combat rotation firing into a vehicle override.

    "Do not let normal rotation fire into a vehicle override state" -- a
    rotation caller (e.g. CombatSkill) should check this before issuing a
    normal-context ability.
    """
    return not is_vehicle_override_active(state)


class VehicleSkill:
    """Bounded vehicle-override handling: cancel, act, verify, restore."""

    def __init__(self, verifier: QuestProgressVerifier | None = None):
        self.verifier = verifier or QuestProgressVerifier()

    def begin(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        state.phase = VehiclePhase.DETECT_OVERRIDE.value
        if not is_vehicle_override_active(world_state):
            return SkillResult(SkillStatus.BLOCKED, FailureReason.WRONG_UI, replan_required=True)

        params = state.intent.parameters
        vehicle_actions = tuple(params.get("vehicle_actions") or ())
        if not vehicle_actions:
            return SkillResult(SkillStatus.BLOCKED, FailureReason.UNSUPPORTED_MECHANIC,
                               replan_required=True)

        state.skill_context["vehicle"] = {
            "quest_ids": tuple(params.get("quest_ids") or ()),
            "objective_ids": tuple(params.get("objective_ids") or
                                   ((state.intent.objective_ref,) if state.intent.objective_ref else ())),
        }
        # Cancelling incompatible normal combat/movement assumptions is the
        # caller's ActiveSkillRuntime/Supervisor responsibility on the
        # VEHICLE invalidation event (runtime/state_invalidation.py); this
        # phase marker documents the sequencing point without re-owning it.
        state.phase = VehiclePhase.CANCEL_INCOMPATIBLE_ASSUMPTIONS.value
        state.phase = VehiclePhase.USE_VEHICLE_ACTIONS.value
        commands = tuple(Command("BIND", binding=action) for action in vehicle_actions)
        return SkillResult(SkillStatus.RUNNING, commands=commands)

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        if not is_vehicle_override_active(world_state):
            # Vehicle exited mid-attempt: invalidate vehicle action state and
            # hand control back rather than claiming a false completion.
            state.phase = VehiclePhase.EXIT_RESTORE_CONTEXT.value
            return SkillResult(SkillStatus.FAILURE, FailureReason.INTERRUPTED, replan_required=True)

        context = state.skill_context.get("vehicle") or {}
        state.phase = VehiclePhase.VERIFY_QUEST_PROGRESS.value
        result = self.verifier.evaluate(state.before_snapshot, world_state,
                                        quest_ids=context.get("quest_ids", ()),
                                        objective_ids=context.get("objective_ids", ()))
        if result.success:
            return SkillResult(SkillStatus.SUCCESS, evidence=result.evidence)
        if now >= state.attempt.deadline:
            return SkillResult(SkillStatus.FAILURE, FailureReason.QUEST_CREDIT_NOT_RECEIVED,
                               retryable=True, replan_required=True)
        return SkillResult(SkillStatus.RUNNING)
