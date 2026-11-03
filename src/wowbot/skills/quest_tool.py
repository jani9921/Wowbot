"""Canonical, fail-closed handler for Retail's Extra Action quest control."""
from __future__ import annotations

from wowbot.runtime.skill_identity import identity_guarded

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

    @identity_guarded
    def begin(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        params = state.intent.parameters
        if state.skill_type == "ADDON_ACTION":
            return self._begin_addon_action(state, world_state)
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
            return SkillResult(SkillStatus.BLOCKED, FailureReason.MISSING_BINDING,
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

    def _begin_addon_action(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        params = state.intent.parameters
        quest_ids = tuple(params.get("quest_ids") or ())
        objective_ids = tuple(params.get("objective_ids") or
                              ((state.intent.objective_ref,) if state.intent.objective_ref else ()))
        state.phase = QuestToolPhase.VALIDATE_CONTEXT.value
        if not addon_action_ready(params, world_state, self.bindings):
            return SkillResult(SkillStatus.BLOCKED, FailureReason.WRONG_UI, retryable=True,
                               replan_required=True, metadata={"reason": "addon_action_not_current"})
        state.skill_context["quest_tool"] = {"action": params["binding"],
                                             "action_type": str(params.get("action_kind") or "EMOTE").lower(),
                                             "action_id": params.get("emote"),
                                             "quest_ids": quest_ids, "objective_ids": objective_ids}
        state.phase = QuestToolPhase.ACTIVATE_EXPORTED_ACTION.value
        return SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", params["binding"]),))

    @identity_guarded
    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("quest_tool") or {}
        state.phase = QuestToolPhase.VERIFY.value
        if context.get("action_type") == "abandon_failed":
            # The failed quest left the (known) log: the giver offers it again.
            quests = world_state.get("active_quests")
            if isinstance(quests, (list, tuple)) and not any(
                    isinstance(q, dict) and str(q.get("quest_id")) in {str(v) for v in context.get("quest_ids", ())}
                    for q in quests):
                return SkillResult(SkillStatus.SUCCESS, evidence=("failed_quest_abandoned",))
            if now >= state.attempt.deadline:
                return SkillResult(SkillStatus.FAILURE, FailureReason.EXPECTED_STATE_NOT_REACHED,
                                   retryable=True, replan_required=True)
            return SkillResult(SkillStatus.RUNNING)
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


ADDON_EMOTE_BINDING = "CLICK AIPCEMOTEBUTTON:LEFTBUTTON"


def addon_action_ready(params: dict, world_state: dict, bindings) -> bool:
    """P8.4: the addon's quest-action button carries exactly this action now
    and the selected cache binds it.  EMOTE: this quest's emote, the subject
    NPC is the live target.  ABANDON_FAILED: this quest, still FAILED."""
    action = world_state.get("emote_action") or {}
    binding = str(params.get("binding") or "")
    kind = str(params.get("action_kind") or "EMOTE")
    if not (binding == ADDON_EMOTE_BINDING and bindings is not None and bindings.contains(binding)
            and action.get("applied") is True and str(action.get("binding") or "").upper() == binding
            and str(action.get("kind") or "") == kind
            and str(action.get("quest_id")) in {str(q) for q in params.get("quest_ids") or ()}):
        return False
    if kind == "ABANDON_FAILED":
        return any(isinstance(q, dict) and str(q.get("quest_id")) == str(action.get("quest_id"))
                   and q.get("is_failed") is True for q in world_state.get("active_quests") or ())
    target = world_state.get("target") or {}
    return (kind == "EMOTE" and str(action.get("emote") or "") == str(params.get("emote") or "") != ""
            and bool(params.get("guid")) and str(target.get("guid") or "") == str(params["guid"])
            and not target.get("dead", target.get("is_dead")))


# Existing runtime import retained while ExtraActionHandler is canonical.
QuestToolSkill = ExtraActionHandler
