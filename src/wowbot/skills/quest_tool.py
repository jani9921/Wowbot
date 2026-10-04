"""Canonical, fail-closed handler for Retail's Extra Action quest control."""
from __future__ import annotations

from enum import StrEnum

from wowbot.agent.models import Command
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus
from wowbot.verification import QuestProgressVerifier


class QuestToolPhase(StrEnum):
    VALIDATE_CONTEXT = "VALIDATE_CONTEXT"
    ACTIVATE_EXPORTED_ACTION = "ACTIVATE_EXPORTED_ACTION"
    WAIT_QUEST_CREDIT = "WAIT_QUEST_CREDIT"
    VERIFY = "VERIFY"


class ExtraActionHandler:
    """Use exactly one addon-identified Extra Action binding.

    This skill deliberately does not infer what an Extra Action button means.
    The intent must carry the action type and ID observed from the client, and
    those values must still match at dispatch time. Success remains exclusively
    quest/objective progress, never an input acknowledgement or UI transition.
    """

    ACTION = "EXTRAACTIONBUTTON1"

    def __init__(self, bindings=None, verifier: QuestProgressVerifier | None = None):
        self.bindings = bindings
        self.verifier = verifier or QuestProgressVerifier()

    @staticmethod
    def detect(world_state: dict) -> dict | None:
        extra = world_state.get("extra_action") or {}
        return extra if extra.get("visible") is True else None

    @staticmethod
    def associate_context(parameters: dict) -> bool:
        return bool((parameters.get("quest_ids") or parameters.get("objective_ids"))
                    and parameters.get("extra_action_type")
                    and parameters.get("extra_action_id") is not None)

    @staticmethod
    def requires_target(parameters: dict) -> bool:
        return bool(parameters.get("target_required") or parameters.get("guid"))

    @staticmethod
    def requires_range(parameters: dict) -> bool:
        return parameters.get("range_required") is True

    @classmethod
    def activate(cls) -> Command:
        return Command("BIND", cls.ACTION)

    def verify_transition(self, baseline: dict, world_state: dict, *,
                          quest_ids=(), objective_ids=()):
        return self.verifier.evaluate(
            baseline, world_state, quest_ids=quest_ids,
            objective_ids=objective_ids)

    def begin(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        params = state.intent.parameters
        extra = self.detect(world_state) or {}
        expected_type = str(params.get("extra_action_type") or "").lower()
        expected_id = params.get("extra_action_id")
        quest_ids = tuple(params.get("quest_ids") or ())
        objective_ids = tuple(params.get("objective_ids") or
                              ((state.intent.objective_ref,) if state.intent.objective_ref else ()))
        state.phase = QuestToolPhase.VALIDATE_CONTEXT.value
        if not self.associate_context(params):
            return SkillResult(SkillStatus.BLOCKED, FailureReason.OBJECTIVE_UNKNOWN,
                               replan_required=True,
                               metadata={"reason": "exact_quest_action_context_required"})
        if self.bindings is None or not self.bindings.contains(self.ACTION):
            return SkillResult(SkillStatus.BLOCKED, FailureReason.UNSUPPORTED_MECHANIC,
                               replan_required=True,
                               metadata={"reason": "selected_cache_missing_extra_action_binding"})
        if (extra.get("visible") is not True or extra.get("usable") is not True
                or str(extra.get("action") or "").upper() != self.ACTION
                or str(extra.get("action_type") or "").lower() != expected_type
                or str(extra.get("action_id")) != str(expected_id)):
            return SkillResult(SkillStatus.FAILURE, FailureReason.WRONG_UI,
                               retryable=True, replan_required=True,
                               metadata={"reason": "extra_action_identity_not_current"})
        if self.requires_target(params):
            target = world_state.get("target") or {}
            if str(target.get("guid") or "") != str(params.get("guid") or ""):
                return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                                   retryable=True, replan_required=True)
        if self.requires_range(params) and extra.get("in_range") is False:
            return SkillResult(SkillStatus.FAILURE, FailureReason.OUT_OF_RANGE,
                               retryable=True, replan_required=True)
        state.skill_context["quest_tool"] = {
            "action": self.ACTION,
            "action_type": expected_type,
            "action_id": expected_id,
            "quest_ids": quest_ids,
            "objective_ids": objective_ids,
        }
        state.phase = QuestToolPhase.ACTIVATE_EXPORTED_ACTION.value
        return SkillResult(SkillStatus.RUNNING, commands=(self.activate(),))

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("quest_tool") or {}
        state.phase = QuestToolPhase.VERIFY.value
        result = self.verify_transition(
            state.before_snapshot, world_state,
            quest_ids=context.get("quest_ids", ()),
            objective_ids=context.get("objective_ids", ()),
        )
        if result.success:
            return SkillResult(SkillStatus.SUCCESS, evidence=result.evidence)
        if now >= state.attempt.deadline:
            return SkillResult(SkillStatus.FAILURE, FailureReason.QUEST_CREDIT_NOT_RECEIVED,
                               retryable=True, replan_required=True)
        state.phase = QuestToolPhase.WAIT_QUEST_CREDIT.value
        return SkillResult(SkillStatus.RUNNING)


# Existing runtime import retained while ExtraActionHandler is canonical.
QuestToolSkill = ExtraActionHandler
