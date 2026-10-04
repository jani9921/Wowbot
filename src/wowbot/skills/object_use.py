"""Canonical screen-space world-object use with quest-credit verification."""
from __future__ import annotations

from enum import StrEnum

from wowbot.agent.models import Command, number
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus
from wowbot.verification import QuestProgressVerifier


class ObjectUsePhase(StrEnum):
    VALIDATE_MOUSEOVER = "VALIDATE_MOUSEOVER"
    SEND_USE = "SEND_USE"
    WAIT_QUEST_CREDIT = "WAIT_QUEST_CREDIT"
    VERIFY = "VERIFY"


class ObjectUseSkill:
    """Use one currently-hovered quest object, never a stale screen crop."""

    def __init__(self, verifier: QuestProgressVerifier | None = None):
        self.verifier = verifier or QuestProgressVerifier()

    @staticmethod
    def _identity_matches(params: dict, mouse: dict) -> bool:
        object_id, item_id = params.get("object_id"), params.get("item_id")
        if object_id is not None:
            return str(mouse.get("object_id")) == str(object_id)
        if item_id is not None:
            return str(mouse.get("item_id")) == str(item_id)
        expected = str(params.get("mouseover_tooltip") or "")
        return bool(expected and str(mouse.get("tooltip") or "") == expected)

    def begin(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        params = state.intent.parameters
        quest_ids = tuple(params.get("quest_ids") or ())
        objective_ids = tuple(params.get("objective_ids") or
                              ((state.intent.objective_ref,) if state.intent.objective_ref else ()))
        x, y = number(params.get("x")), number(params.get("y"))
        # A world object's name may arrive only in the (late) mouseover
        # change event; effective_mouseover attributes it to a still cursor.
        from wowbot.agent.tooltip_quest import effective_mouseover
        mouse, cursor = effective_mouseover(world_state), world_state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        state.phase = ObjectUsePhase.VALIDATE_MOUSEOVER.value
        if (not quest_ids and not objective_ids) or None in (x, y, cx, cy):
            return SkillResult(SkillStatus.BLOCKED, FailureReason.OBJECTIVE_UNKNOWN,
                               replan_required=True)
        if not (0 < x < 1 and 0 < y < 1 and abs(x - cx) <= .002 and abs(y - cy) <= .002):
            return SkillResult(SkillStatus.FAILURE, FailureReason.STALE_OBSERVATION,
                               retryable=True, replan_required=True)
        if not self._identity_matches(params, mouse):
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                               retryable=True, replan_required=True)
        state.skill_context["object_use"] = {"quest_ids": quest_ids, "objective_ids": objective_ids}
        state.phase = ObjectUsePhase.SEND_USE.value
        return SkillResult(SkillStatus.RUNNING, commands=(Command("CLICK", x=x, y=y, button="RIGHT"),))

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("object_use") or {}
        state.phase = ObjectUsePhase.VERIFY.value
        result = self.verifier.evaluate(state.before_snapshot, world_state,
                                        quest_ids=context.get("quest_ids", ()),
                                        objective_ids=context.get("objective_ids", ()))
        if result.success:
            return SkillResult(SkillStatus.SUCCESS, evidence=result.evidence)
        if now >= state.attempt.deadline:
            return SkillResult(SkillStatus.FAILURE, FailureReason.QUEST_CREDIT_NOT_RECEIVED,
                               retryable=True, replan_required=True)
        state.phase = ObjectUsePhase.WAIT_QUEST_CREDIT.value
        return SkillResult(SkillStatus.RUNNING)
