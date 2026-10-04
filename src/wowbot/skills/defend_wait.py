"""Bounded, stationary DEFEND/WAIT quest-objective monitor."""
from __future__ import annotations

from enum import StrEnum

from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus
from wowbot.verification import QuestProgressVerifier


class DefendWaitPhase(StrEnum):
    WAIT_FOR_EVENT = "WAIT_FOR_EVENT"
    MONITOR = "MONITOR"
    COMBAT_IF_REQUIRED = "COMBAT_IF_REQUIRED"
    VERIFY_PROGRESS = "VERIFY_PROGRESS"
    TIMEOUT_REEVALUATE = "TIMEOUT_REEVALUATE"


class DefendWaitSkill:
    """Wait for a quest event without searching or issuing movement input.

    A hostile interrupt ends this monitoring attempt with a typed replan so
    the canonical combat policy can select DEFEND.  Quest progress is the
    only success condition; timeout requests bounded reevaluation.
    """

    def __init__(self, verifier: QuestProgressVerifier | None = None) -> None:
        self.verifier = verifier or QuestProgressVerifier()

    def begin(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        state.phase = DefendWaitPhase.WAIT_FOR_EVENT.value
        parameters = state.intent.parameters
        state.skill_context["defend_wait"] = {
            "quest_ids": tuple(parameters.get("quest_ids") or ()),
            "objective_ids": tuple(parameters.get("objective_ids") or ()),
            "started_at": now,
        }
        state.phase = DefendWaitPhase.MONITOR.value
        return SkillResult(SkillStatus.RUNNING, evidence=("stationary_event_monitor_started",))

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("defend_wait") or {}
        if world_state.get("is_dead") or world_state.get("is_ghost"):
            return SkillResult(SkillStatus.FAILURE, FailureReason.PLAYER_DEAD,
                               replan_required=True)
        target = world_state.get("target") or {}
        if (world_state.get("is_in_combat")
                and target.get("attackable", target.get("is_attackable")) is True
                and not target.get("dead", target.get("is_dead"))):
            state.phase = DefendWaitPhase.COMBAT_IF_REQUIRED.value
            return SkillResult(
                SkillStatus.FAILURE, FailureReason.INTERRUPTED,
                retryable=True, replan_required=True,
                evidence=("combat_interrupt_requires_defend",),
                metadata={"reason": "combat_required_during_wait"})
        state.phase = DefendWaitPhase.VERIFY_PROGRESS.value
        progress = self.verifier.evaluate(
            state.before_snapshot, world_state,
            quest_ids=context.get("quest_ids") or (),
            objective_ids=context.get("objective_ids") or ())
        if progress.success:
            return SkillResult(SkillStatus.SUCCESS, evidence=progress.evidence)
        if now >= state.attempt.deadline:
            state.phase = DefendWaitPhase.TIMEOUT_REEVALUATE.value
            return SkillResult(
                SkillStatus.FAILURE, FailureReason.TIMEOUT,
                retryable=True, replan_required=True,
                evidence=("bounded_wait_window_expired",),
                metadata={"reason": "wait_event_timeout_reevaluate"})
        state.phase = DefendWaitPhase.MONITOR.value
        return SkillResult(SkillStatus.RUNNING)
