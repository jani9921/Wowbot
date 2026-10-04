"""Canonical spell use explicitly named by fresh NPC instruction telemetry."""
from __future__ import annotations

import re
from wowbot.agent.models import Command, number
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus
from wowbot.verification import QuestProgressVerifier


def _words(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


class InstructedSpellSkill:
    def __init__(self, bindings=None, verifier: QuestProgressVerifier | None = None):
        self.bindings, self.verifier = bindings, verifier or QuestProgressVerifier()

    def begin(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        params, target = state.intent.parameters, world_state.get("target") or {}
        guid, instruction = state.intent.target_ref or str(params.get("guid") or ""), _words(params.get("instruction"))
        binding, spell_id = str(params.get("binding") or ""), params.get("spell_id")
        quest_ids = tuple(params.get("quest_ids") or ())
        objective_ids = tuple(params.get("objective_ids") or ((state.intent.objective_ref,) if state.intent.objective_ref else ()))
        if (not guid or not instruction or not binding or spell_id is None or not quest_ids and not objective_ids
                or target.get("guid") != guid or target.get("attackable", target.get("is_attackable")) is not True
                or target.get("dead", target.get("is_dead"))):
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN, retryable=True, replan_required=True)
        # A spell name contained in NPC text is never enough authority to
        # synthesize a key.  The one explicitly selected cache is the source
        # of truth for every real input path, including this M1 convenience
        # mechanic.  This mirrors QuestToolSkill's fail-closed boundary.
        if self.bindings is None or not self.bindings.contains(binding):
            return SkillResult(SkillStatus.BLOCKED, FailureReason.UNSUPPORTED_MECHANIC,
                               replan_required=True,
                               metadata={"reason": "selected_cache_missing_instructed_spell_binding"})
        action = next((a for a in world_state.get("actionbar", ()) if isinstance(a, dict)
                       and a.get("kind") == "spell" and str(a.get("id", a.get("spell_id"))) == str(spell_id)
                       and str(a.get("action") or "") == binding and _words(a.get("name")) in instruction), None)
        cooldown = number((action or {}).get("cooldown_remaining"))
        if (action is None or action.get("is_usable") is not True or action.get("in_range") is False
                or cooldown is None or cooldown > .1):
            return SkillResult(SkillStatus.FAILURE, FailureReason.SPELL_NOT_READY, retryable=True, replan_required=True)
        state.skill_context["instructed_spell"] = {"guid": guid, "quest_ids": quest_ids, "objective_ids": objective_ids}
        return SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", binding),))

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("instructed_spell") or {}
        if (world_state.get("target") or {}).get("guid") != context.get("guid"):
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN, retryable=True, replan_required=True)
        result = self.verifier.evaluate(state.before_snapshot, world_state, quest_ids=context.get("quest_ids", ()), objective_ids=context.get("objective_ids", ()))
        if result.success:
            return SkillResult(SkillStatus.SUCCESS, evidence=result.evidence)
        if now >= state.attempt.deadline:
            return SkillResult(SkillStatus.FAILURE, FailureReason.QUEST_CREDIT_NOT_RECEIVED, retryable=True, replan_required=True)
        return SkillResult(SkillStatus.RUNNING)
