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

    # Live 2026-10-05 (Re-Sizer): Interact on a far boar did nothing for 5 s
    # (no error); the bag item then only armed a targeting cursor, which the
    # next left click on a boar fired.  User 2026-10-06: target, then
    # Interact Target within range, or right-click.
    INTERACT_EFFECT_SECONDS = 1.5
    ARMED_CURSOR_CLICK_SECONDS = .4

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
                # User 2026-10-06: "...vagy jobb klikk" -- right-click the
                # target's own box instead.
                right_click = self._start_right_click(state, world_state, expected_guid,
                                                      item_id, quest_ids, objective_ids, now=state.started_at)
                if right_click is not None:
                    return right_click
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
        if world_state.get("is_casting") is True or world_state.get("is_channeling") is True:
            context["cast_seen"] = True
        source = context.get("activation_source")
        if source == "UNIT_RIGHT_CLICK" and not (context.get("target_click") or {}).get("done"):
            from .hover_confirm import hover_confirm_step
            click = context["target_click"]
            outcome, commands = hover_confirm_step(click, world_state, now,
                                                   expected_guid=str(context.get("guid") or ""),
                                                   click_button="RIGHT")
            if outcome == "CLICK":
                click.update(done=True, clicked_at=now)
            if outcome in {"CLICK", "HOVER"}:
                return SkillResult(SkillStatus.RUNNING, commands=commands)
            if outcome == "FAILED":
                return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                                   retryable=True, replan_required=True)
            return SkillResult(SkillStatus.RUNNING)
        activated_at = number((context.get("target_click") or {}).get("clicked_at"))             if source == "UNIT_RIGHT_CLICK" else float(state.started_at)
        elapsed = now - float(activated_at if activated_at is not None else state.started_at)
        if (source in {"INTERACT_KEY", "UNIT_RIGHT_CLICK"} and not context.get("cast_seen")
                and elapsed >= self.INTERACT_EFFECT_SECONDS):
            # Nothing started: the target is beyond interact range.  The
            # planner approaches it and tries again.
            return SkillResult(SkillStatus.FAILURE, FailureReason.OUT_OF_RANGE,
                               retryable=True, replan_required=True,
                               metadata={"detail": "interact_no_effect"})
        if (source in {"INVENTORY_COORDINATE", "ACTIONBAR"} and not context.get("cast_seen")
                and elapsed >= self.ARMED_CURSOR_CLICK_SECONDS):
            click = self._target_click(context, world_state, now)
            if click is not None:
                return click
        if now >= state.attempt.deadline:
            return SkillResult(SkillStatus.FAILURE, FailureReason.QUEST_CREDIT_NOT_RECEIVED,
                               retryable=True, replan_required=True)
        state.phase = UseItemPhase.WAIT.value
        return SkillResult(SkillStatus.RUNNING)

    @staticmethod
    def _target_track(world_state: dict, guid) -> object:
        target = world_state.get("target") or {}
        return (target.get("screen_position") or {}).get("track_id") or (
            (world_state.get("confirmed_mouseover_anchors") or {}).get(str(guid)) or {}).get("track_id")

    def _start_right_click(self, state: ActiveSkillState, world_state: dict, guid,
                           item_id, quest_ids, objective_ids, *, now: float) -> SkillResult | None:
        from .hover_confirm import hover_confirm_step, live_track_point
        track = self._target_track(world_state, guid)
        if live_track_point(world_state, track) is None:
            return None
        click = {"track_id": track, "hovers": 0}
        state.skill_context["quest_item"] = {
            "guid": guid, "item_id": item_id, "binding": "",
            "activation_source": "UNIT_RIGHT_CLICK", "target_click": click,
            "quest_ids": quest_ids, "objective_ids": objective_ids,
        }
        outcome, commands = hover_confirm_step(click, world_state, now, expected_guid=str(guid),
                                               click_button="RIGHT")
        if outcome == "CLICK":
            click.update(done=True, clicked_at=now)
        state.phase = UseItemPhase.USE.value
        return SkillResult(SkillStatus.RUNNING, commands=commands)

    @staticmethod
    def _target_click(context: dict, world_state: dict, now: float) -> SkillResult | None:
        """Click the selected target's live box: an item that armed a
        targeting cursor fires on it, any other click just reselects it."""
        from .hover_confirm import hover_confirm_step, live_track_point
        click = context.get("target_click")
        if click is None:
            track = UseItemSkill._target_track(world_state, context.get("guid"))
            if live_track_point(world_state, track) is None:
                return None
            click = context["target_click"] = {"track_id": track, "hovers": 0}
        if click.get("done"):
            return None
        outcome, commands = hover_confirm_step(click, world_state, now,
                                               expected_guid=str(context.get("guid") or ""))
        if outcome == "CLICK":
            click["done"] = True
        if outcome in {"CLICK", "HOVER"}:
            return SkillResult(SkillStatus.RUNNING, commands=commands,
                               metadata={"armed_cursor_target_click": outcome})
        if outcome == "FAILED":
            click["done"] = True
        return None


# Compatibility imports; UseItemSkill is the canonical design component.
QuestItemPhase = UseItemPhase
QuestItemSkill = UseItemSkill
