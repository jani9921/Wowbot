"""Canonical targeted quest-item activation with credit-only verification."""
from __future__ import annotations

from enum import StrEnum

from wowbot.agent.models import Command, number
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus
from wowbot.verification import QuestProgressVerifier


class UseItemPhase(StrEnum):
    VALIDATE_CONTEXT = "VALIDATE_CONTEXT"
    RESOLVE_ITEM_ACTION = "RESOLVE_ITEM_ACTION"
    ACQUIRE_TARGET_IF_NEEDED = "ACQUIRE_TARGET_IF_NEEDED"
    APPROACH = "APPROACH"
    FACE = "FACE"
    USE = "USE"
    WAIT = "WAIT"
    VERIFY = "VERIFY"


class UseItemSkill:
    """Use a selected-cache action-bar item on one confirmed living target.

    Item-use acknowledgement, a cooldown change, and an ITEM_USED event do not
    prove a quest objective. They remain diagnostic evidence only; this skill
    succeeds solely through the normalized quest progress verifier.
    """

    def __init__(self, bindings=None, verifier: QuestProgressVerifier | None = None):
        self.bindings = bindings
        self.verifier = verifier or QuestProgressVerifier()

    @staticmethod
    def target_required(parameters: dict) -> bool:
        return bool(parameters.get("guid") or parameters.get("target_required", True))

    @staticmethod
    def range_required(parameters: dict, action: dict | None = None) -> bool:
        if "range_required" in parameters:
            return parameters.get("range_required") is True
        return action is not None and action.get("in_range") is not None

    @staticmethod
    def cooldown_ready(action: dict | None) -> bool:
        cooldown = number((action or {}).get("cooldown_remaining"))
        return bool(action and action.get("is_usable") is True
                    and cooldown is not None and cooldown <= .1)

    @staticmethod
    def resolve_item(world_state: dict, item_id: object) -> dict | None:
        return next((candidate for candidate in world_state.get("actionbar", ())
                     if isinstance(candidate, dict) and candidate.get("kind") == "item"
                     and str(candidate.get("id")) == str(item_id)), None)

    @staticmethod
    def resolve_inventory_item(world_state: dict, parameters: dict) -> dict | None:
        """Revalidate an addon-reported visible bag button before clicking."""
        if parameters.get("activation_source") != "INVENTORY_COORDINATE":
            return None
        item_id = parameters.get("item_id")
        quest_ids = {str(value) for value in parameters.get("quest_ids", ())}
        authorized = any(
            str(quest.get("quest_id")) in quest_ids
            and str((quest.get("special_item") or {}).get("item_id")) == str(item_id)
            for quest in world_state.get("active_quests", ()))
        if not authorized or world_state.get("bags_open") is not True:
            return None
        item = next((candidate for candidate in (world_state.get("inventory") or {}).get("items", ())
                     if str(candidate.get("item_id")) == str(item_id)
                     and candidate.get("bag") == parameters.get("bag")
                     and candidate.get("slot") == parameters.get("slot")), None)
        x, y = number(parameters.get("x")), number(parameters.get("y"))
        ix, iy = number((item or {}).get("x")), number((item or {}).get("y"))
        if (item is None or item.get("is_locked") is True
                or item.get("coordinate_space") != "CLIENT_BOTTOM_LEFT"
                or parameters.get("coordinate_space") != "CLIENT_BOTTOM_LEFT"
                or None in (x, y, ix, iy) or not (0 < x < 1 and 0 < y < 1)
                or abs(x-ix) > .002 or abs(y-iy) > .002):
            return None
        return item

    @staticmethod
    def activate_actionbar(binding: str) -> Command:
        return Command("BIND", binding)

    @staticmethod
    def activate_inventory(parameters: dict) -> Command:
        return Command("CLICK", x=parameters["x"], y=parameters["y"], button="RIGHT")

    def verify_credit(self, baseline: dict, world_state: dict, *,
                      quest_ids=(), objective_ids=()):
        return self.verifier.evaluate(
            baseline, world_state, quest_ids=quest_ids,
            objective_ids=objective_ids)

    def begin(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        params, target = state.intent.parameters, world_state.get("target") or {}
        expected_guid = state.intent.target_ref or str(params.get("guid") or "")
        item_id = params.get("item_id")
        expected_binding = str(params.get("binding") or "")
        quest_ids = tuple(params.get("quest_ids") or ())
        objective_ids = tuple(params.get("objective_ids") or
                              ((state.intent.objective_ref,) if state.intent.objective_ref else ()))
        state.phase = UseItemPhase.VALIDATE_CONTEXT.value
        if (item_id is None or (not quest_ids and not objective_ids)
                or (self.target_required(params) and not expected_guid)):
            return SkillResult(SkillStatus.BLOCKED, FailureReason.OBJECTIVE_UNKNOWN,
                               replan_required=True)
        state.phase = UseItemPhase.ACQUIRE_TARGET_IF_NEEDED.value
        if self.target_required(params) and target.get("guid") != expected_guid:
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                               retryable=True, replan_required=True)
        if target.get("dead", target.get("is_dead")):
            return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_DEAD,
                               replan_required=True)
        if (state.skill_type == "ASSIST"
                and target.get("attackable", target.get("is_attackable")) is not False):
            return SkillResult(SkillStatus.FAILURE, FailureReason.INVALID_TARGET,
                               replan_required=True)
        state.phase = UseItemPhase.RESOLVE_ITEM_ACTION.value
        action = self.resolve_item(world_state, item_id)
        binding = str((action or {}).get("action") or "")
        inventory_item = self.resolve_inventory_item(world_state, params)
        using_inventory = inventory_item is not None
        interact_key = params.get("activation_source") == "INTERACT_KEY"
        if using_inventory:
            command = self.activate_inventory(params)
            binding = ""
        elif interact_key:
            # Retail's Interact key uses an active quest's special item on
            # its objective target (live 2026-10-04, Re-Sizer v9.0.1).
            if self.bindings is not None and not self.bindings.contains("INTERACTTARGET"):
                return SkillResult(SkillStatus.BLOCKED, FailureReason.UNSUPPORTED_MECHANIC,
                                   replan_required=True,
                                   metadata={"reason": "interact_binding_required"})
            binding = "INTERACTTARGET"
            command = self.activate_actionbar(binding)
        else:
            if self.bindings is None:
                return SkillResult(SkillStatus.BLOCKED, FailureReason.UNSUPPORTED_MECHANIC,
                                   replan_required=True,
                                   metadata={"reason": "selected_cache_or_verified_bag_item_required"})
            if (not self.cooldown_ready(action)
                    or not binding or (expected_binding and binding != expected_binding)
                    or not self.bindings.contains(binding)):
                return SkillResult(SkillStatus.FAILURE, FailureReason.SPELL_NOT_READY,
                                   retryable=True, replan_required=True)
            if state.skill_type == "ASSIST" and action.get("is_harmful") is True:
                return SkillResult(SkillStatus.FAILURE, FailureReason.INVALID_TARGET,
                                   replan_required=True)
            if self.range_required(params, action) and action.get("in_range") is False:
                state.phase = UseItemPhase.APPROACH.value
                return SkillResult(SkillStatus.FAILURE, FailureReason.OUT_OF_RANGE,
                                   retryable=True, replan_required=True)
            command = self.activate_actionbar(binding)
        state.skill_context["quest_item"] = {
            "guid": expected_guid, "item_id": item_id, "binding": binding,
            "activation_source": ("INVENTORY_COORDINATE" if using_inventory
                                  else "INTERACT_KEY" if interact_key else "ACTIONBAR"),
            "quest_ids": quest_ids, "objective_ids": objective_ids,
        }
        state.phase = UseItemPhase.FACE.value
        state.phase = UseItemPhase.USE.value
        return SkillResult(SkillStatus.RUNNING, commands=(command,))

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("quest_item") or {}
        state.phase = UseItemPhase.VERIFY.value
        target = world_state.get("target") or {}
        if target.get("guid") != context.get("guid"):
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                               retryable=True, replan_required=True)
        result = self.verify_credit(
            state.before_snapshot, world_state,
            quest_ids=context.get("quest_ids", ()),
            objective_ids=context.get("objective_ids", ()))
        if result.success:
            return SkillResult(SkillStatus.SUCCESS, evidence=result.evidence)
        from wowbot.verification.interaction import classify_ui_error, new_ui_errors
        kinds = {classify_ui_error(error.get("message"), error.get("error_code"))
                 for error in new_ui_errors(state.before_snapshot or {}, world_state)}
        # User 2026-10-04: not only "too far" -- line of sight and facing
        # errors end the attempt too; the planner approaches/faces the target.
        for kind, reason in (("RANGE", FailureReason.OUT_OF_RANGE),
                             ("FACING", FailureReason.FACING_FAILED),
                             ("LINE_OF_SIGHT", FailureReason.LINE_OF_SIGHT)):
            if kind in kinds:
                return SkillResult(SkillStatus.FAILURE, reason, retryable=True, replan_required=True,
                                   metadata={"ui_error_kind": kind})
        if now >= state.attempt.deadline:
            return SkillResult(SkillStatus.FAILURE, FailureReason.QUEST_CREDIT_NOT_RECEIVED,
                               retryable=True, replan_required=True)
        state.phase = UseItemPhase.WAIT.value
        return SkillResult(SkillStatus.RUNNING)


# Compatibility imports; UseItemSkill is the canonical design component.
QuestItemPhase = UseItemPhase
QuestItemSkill = UseItemSkill
