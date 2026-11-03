"""Shared, input-free entity identity gate; ActiveSkillState owns the pin.

Track IDs may aim a pointer. They never authorize selecting, casting, looting
or interacting. UI-only actions keep their own quest/action/item contracts;
coordinate navigation and inspection are not disguised entity interactions.
"""
from __future__ import annotations

from dataclasses import replace
from functools import wraps
import math

from .contracts import FailureReason, SkillResult, SkillStatus
from .entity_identity import (IdentityCheck, check_entity_identity, template_id,
                              world_entity_id)


SELECTED_ENTITY_SKILLS = frozenset({
    "INTERACT", "TALK", "COMBAT", "DEFEND", "USE_ON_TARGET", "ASSIST",
    "FOLLOW_INSTRUCTION", "APPROACH_TARGET",
})
HOVER_ENTITY_SKILLS = frozenset({"TARGET", "LOOT", "OBJECT_USE", "GATHER", "HERB", "MINE"})
UI_ENTITY_SKILLS = {"QUEST_DIALOG": "quest_ui", "FIELD_TURN_IN": "quest_ui",
                    "REPAIR": "vendor_ui", "BUY_VENDOR": "vendor_ui", "SELL_VENDOR": "vendor_ui"}


def expected_identity(parameters: dict, target_ref=None, *, include_item=False) -> dict:
    result = {}
    if parameters.get("_identity_invalid") is True:
        result["_identity_invalid"] = True
    guid = target_ref or parameters.get("guid") or parameters.get("object_guid") or parameters.get("soft_guid")
    if guid not in (None, ""):
        result["guid"] = guid
    aliases = [value for value in (target_ref, parameters.get("guid"),
               parameters.get("object_guid"), parameters.get("soft_guid")) if value]
    if len({world_entity_id(value) for value in aliases}) > 1:
        result["_identity_invalid"] = True
    for key in ("npc_id", "object_id", *(("item_id",) if include_item else ())):
        value = parameters.get(key)
        if value is None:
            value = parameters.get("expected_" + key)
        if value not in (None, "", 0, "0"):
            result[key] = value
            alias = parameters.get("expected_" + key)
            if alias not in (None, "", 0, "0") and template_id(alias) != template_id(value):
                result["_identity_invalid"] = True
    return result


def entity_role(skill: str, parameters: dict) -> str | None:
    if skill in UI_ENTITY_SKILLS:
        return UI_ENTITY_SKILLS[skill]
    if skill in SELECTED_ENTITY_SKILLS:
        if (skill in {"USE_ON_TARGET", "ASSIST"} and parameters.get("target_required") is False
                and not expected_identity(parameters)):
            return None
        return "target"
    if skill in HOVER_ENTITY_SKILLS:
        return "mouseover"
    if skill in {"EXTRA_ACTION", "VEHICLE_ABILITY", "VEHICLE"} and (
            parameters.get("target_required") or expected_identity(parameters)):
        return "target"
    return None


def sample_fresh(world: dict, source: str, now: float, *, max_age=1.5) -> bool:
    key = "soft_targets_sample_time" if source == "soft_targets" else source + "_sample_time"
    raw = world.get(key, world.get("monotonic_time"))
    if raw is None:
        # Unclocked offline fixtures are supported. A live transport with a
        # missing clock is unknown, not freshly sampled at dispatch time.
        return not any(world.get(key) for key in ("transport_kind", "telemetry_lane", "protocol_version"))
    try:
        sampled = float(raw)
    except (TypeError, ValueError):
        return False
    return math.isfinite(sampled) and 0 <= now - sampled <= max_age


def soft_interact(world: dict) -> dict | None:
    return next((row for row in world.get("soft_targets") or ()
                 if isinstance(row, dict) and str(row.get("source_unit") or "").casefold() == "softinteract"), None)


def check_interaction_recipient(wanted: dict, world: dict, now: float, *, fallback="target") -> IdentityCheck:
    """F7 must act on the intended live recipient, including servo probes."""
    soft = soft_interact(world)
    source = "soft_targets" if soft is not None else fallback
    observed = soft if soft is not None else world.get(fallback) or {}
    checked = check_entity_identity(wanted, observed)
    if checked and not sample_fresh(world, source, now):
        return IdentityCheck(False, "IDENTITY_SAMPLE_STALE")
    if (checked and world.get("soft_targets_sample_time", True) is None
            and any(world.get(key) for key in ("transport_kind", "telemetry_lane", "protocol_version"))):
        return IdentityCheck(False, "INTERACT_RECIPIENT_UNOBSERVED")
    return checked


QUEST_OBJECT_TOOLTIP = "QUEST_OBJECT_TOOLTIP"


def quest_object_tooltip_matches(params: dict, mouse: dict) -> bool:
    """A hovered world object proved by the client's own quest tooltip line.

    Retail exposes no GUID or object ID for a hovered game object (the addon
    reports object_id 0).  Live 2026-10-19/20 the agent hovered every Harpy
    Totem ("Harpy Totem", quest 55881, quest_related) and never used one,
    because input required that missing ID.  The quest line is shown only
    for an object of this character's active quest; any unit GUID or a
    contradicting object ID never passes this rule.
    """
    if params.get("identity_certification") != QUEST_OBJECT_TOOLTIP or not isinstance(mouse, dict):
        return False
    if mouse.get("guid") or str(mouse.get("object_id") or "0") not in {"0", ""}:
        return False
    if mouse.get("quest_related") is not True:
        return False
    if str(mouse.get("quest_id")) not in {str(value) for value in params.get("quest_ids") or ()}:
        return False
    from wowbot.agent.object_interaction_flow import name_matches
    name = mouse.get("name") or str(mouse.get("tooltip") or "").split("~", 1)[0]
    return name_matches(params.get("expected_tooltips") or (), name)


def server_object_recipient(wanted: dict, world: dict, now: float, basis=None) -> IdentityCheck:
    """INTERACT_KEY_PACKET: the server (Ymir) names the usable game object.

    Live 2026-10-19 15:23-15:25: the addon exported no soft-interact game
    object at three Harpy Totems, so no F7 recipient was ever observed.  The
    server's GUID + Activate flag identifies the object (or, for a rescue,
    its interactive type around the held NPC); the addon's fresh
    soft-interact sample must still show no other recipient for the key.
    """
    from wowbot.agent.packet_entity_facts import entity, server_object_interactable
    value = entity(world, wanted.get("guid"))
    if value is None or not server_object_interactable(world, value["guid"], basis):
        return IdentityCheck(False, "SERVER_OBJECT_NOT_USABLE")
    checked = check_entity_identity(wanted, {"guid": value["guid"], "object_id": value.get("entry_id")})
    if not checked:
        return checked
    soft = soft_interact(world)
    if soft is not None and str(soft.get("guid")) != str(value["guid"]):
        return IdentityCheck(False, "OTHER_SOFT_INTERACT_RECIPIENT")
    if not sample_fresh(world, "soft_targets", now):
        return IdentityCheck(False, "IDENTITY_SAMPLE_STALE")
    return IdentityCheck(True, "SERVER_OBJECT_RECIPIENT")


def pin_skill_identity(state, world: dict) -> dict:
    """Pin a matching identity; upgrade missing fields, never replace a GUID."""
    existing = state.skill_context.get("entity_identity")
    parameters, skill = state.intent.parameters, state.skill_type
    wanted = (dict(existing) if existing is not None else expected_identity(
        parameters, state.intent.target_ref, include_item=skill == "OBJECT_USE"))
    role = entity_role(skill, parameters)
    observed = world.get(role) if role else None
    if role in {"quest_ui", "vendor_ui"}:
        owner = (observed or {}).get("npc_guid")
        observed = {"guid": owner} if world_entity_id(owner) else {}
        if not wanted and observed:
            wanted = dict(observed)
    if parameters.get("activation_source") in {"SOFT_INTERACT", "INTERACT_KEY"}:
        observed = soft_interact(world)
    if isinstance(observed, dict):
        # An already selected public GUID can bind an otherwise unspecified
        # selected-target action. Never bind TARGET from a name/visual track.
        if existing is None and not wanted and role == "target" and world_entity_id(observed.get("guid")):
            wanted = expected_identity(observed)
        if wanted and check_entity_identity(wanted, observed):
            actual = expected_identity(observed)
            for key in ("guid", "npc_id", "object_id"):
                if actual.get(key) not in (None, ""):
                    wanted.setdefault(key, actual[key])
    state.skill_context["entity_identity"] = dict(wanted)
    return state.skill_context["entity_identity"]


def skill_identity_check(state, observed: dict, world: dict | None = None) -> IdentityCheck:
    wanted = pin_skill_identity(state, world or {})
    return check_entity_identity(wanted, observed)


def check_command_identity(skill: str, parameters: dict, wanted: dict, world: dict,
                           commands: tuple, now: float | None) -> IdentityCheck:
    """Pure final check reused by canonical and legacy command routes."""
    if commands and entity_role(skill, parameters) is not None:
        from wowbot.agent.quest_target_context import physical_target_problem
        problem = physical_target_problem(skill, parameters, wanted, world)
        if problem:
            return IdentityCheck(False, problem)
    if skill == "USE_ON_TARGET" and parameters.get("purpose") == "DIRECTED_QUEST_ITEM" and commands:
        from wowbot.agent.directed_item_facts import ready_for_use
        from wowbot.skills.quest_item import UseItemSkill
        if now is None or not ready_for_use(world, parameters, now):
            return IdentityCheck(False, "DIRECTED_ITEM_POSE_OR_CONTEXT_CHANGED")
        source = parameters.get("activation_source")
        for command in commands:
            if source == "INVENTORY_COORDINATE":
                item = UseItemSkill.resolve_inventory_item(world, parameters)
                if (not item or command.kind != "CLICK" or command.button != "RIGHT"
                        or command.x != item["x"] or command.y != item["y"]):
                    return IdentityCheck(False, "DIRECTED_ITEM_BUTTON_CHANGED")
            elif source == "ACTIONBAR":
                item = UseItemSkill.resolve_item(world, parameters.get("item_id"))
                if (not item or command.kind != "BIND" or not UseItemSkill.cooldown_ready(item)
                        or command.binding != item.get("action") or command.binding != parameters.get("binding")):
                    return IdentityCheck(False, "DIRECTED_ITEM_ACTION_CHANGED")
            else:
                return IdentityCheck(False, "DIRECTED_ITEM_ACTIVATION_UNSUPPORTED")
        return IdentityCheck(True, "DIRECTED_ITEM_AIM_AND_BUTTON_VERIFIED")
    role = entity_role(skill, parameters)
    if role is None or not commands:
        return IdentityCheck(True, "NO_ENTITY_DIRECTED_EFFECT")
    if role in {"quest_ui", "vendor_ui"}:
        # Button/quest/item/slot identity is independently mandatory in the
        # owning UI skill. An available NPC owner additionally pins the UI;
        # remote field turn-ins legitimately have no NPC at all.
        if not wanted:
            return IdentityCheck(True, "EXPLICIT_UI_ACTION_ID")
        ui = world.get(role) or {}
        return check_entity_identity(wanted, {"guid": ui.get("npc_guid")})
    meaningful = tuple(command for command in commands
                       if str(getattr(command, "kind", "")).upper() not in {"HOVER", "POINTER"})
    if not meaningful:
        return IdentityCheck(True, "NO_ENTITY_DIRECTED_EFFECT")
    if now is None:
        return IdentityCheck(False, "IDENTITY_SAMPLE_CLOCK_MISSING")
    if skill in {"COMBAT", "DEFEND"}:
        from wowbot.agent.combat_target_safety import combat_target_allowed
        if not combat_target_allowed(world, world.get("target") or {},
                explicit_objective=parameters.get("elite_objective_verified") is True):
            return IdentityCheck(False, "UNVERIFIED_ELITE_TARGET")
    params = parameters
    if (role == "target" or skill == "LOOT") and not world_entity_id(wanted.get("guid")):
        return IdentityCheck(False, "LIVE_ENTITY_GUID_REQUIRED")
    if skill == "TARGET" and params.get("restore_last_target"):
        # This is an explicit acquisition attempt, not proof of selection.
        # TARGET.verify still requires the exact pinned GUID afterwards.
        checked = IdentityCheck(bool(world_entity_id(wanted.get("guid"))), "RESTORE_REQUIRES_GUID")
    else:
        checked = IdentityCheck(False, "EXPECTED_IDENTITY_MISSING_OR_INVALID")
        for command in meaningful:
            source = role
            kind = str(getattr(command, "kind", "")).upper()
            binding = str(getattr(command, "binding", "")).upper()
            # Inventory item activation is a UI click, not a world click. Its
            # exact item/slot contract is checked by UseItemSkill itself.
            inventory_click = (skill in {"USE_ON_TARGET", "ASSIST"}
                               and params.get("activation_source") == "INVENTORY_COORDINATE"
                               and kind == "CLICK" and str(command.button).upper() == "RIGHT")
            if kind in {"CLICK", "CLICK_CURRENT_CURSOR"} and not inventory_click:
                source = "mouseover"
            if binding == "INTERACTTARGET" and params.get("activation_source") == "INTERACT_KEY_PACKET":
                checked = server_object_recipient(wanted, world, now, params.get("server_use_basis"))
                if not checked:
                    break
                continue
            if (skill == "TARGET" and binding == "TARGETNEARESTFRIEND"
                    and params.get("activation_source") == "TAB_FRIEND_RESCUE"):
                # Ctrl+Tab names no unit before the press (user 2026-10-21);
                # TARGET.verify requires the rescue NPC's GUID afterwards.
                checked = IdentityCheck(True, "FRIEND_TAB_VERIFIED_AFTER_PRESS")
                continue
            if (skill == "TARGET" and binding == "TARGETNEARESTENEMY"
                    and params.get("activation_source") == "TAB_DEFEND"
                    and world.get("is_in_combat") is True):
                # In combat any live enemy is a valid defence target;
                # TARGET.verify requires a live attackable selection.
                checked = IdentityCheck(True, "DEFEND_TAB_VERIFIED_AFTER_PRESS")
                continue
            if (skill == "TARGET" and binding in {"TURNLEFT", "TURNRIGHT"}
                    and params.get("activation_source") == "TAB_DEFEND"
                    and world.get("is_in_combat") is True and kind == "BIND"
                    and 0 < float(command.duration or 0) <= .34):
                # A short self turn toward an attacker behind us, before the
                # next defence Tab (live 2026-11-01); it addresses no unit.
                checked = IdentityCheck(True, "DEFEND_TAB_SELF_TURN")
                continue
            if (skill == "TARGET" and binding == "TARGETNEARESTENEMY"
                    and params.get("activation_source") == "TAB_SERVER_GUID"):
                # Tab names no unit before the press: the server must show the
                # wanted GUID as the one Tab selects; TARGET.verify then
                # requires exactly that GUID as the new target.
                from wowbot.agent.packet_entity_facts import tab_target_check
                ok, reason = tab_target_check(world, wanted.get("guid"))
                checked = IdentityCheck(ok, reason)
                if not checked:
                    break
                continue
            observed = world.get(source) or {}
            soft = soft_interact(world) if binding == "INTERACTTARGET" else None
            if soft is not None:
                source, observed = "soft_targets", soft
            elif binding == "INTERACTTARGET" and skill == "LOOT":
                source, observed = "target", world.get("target") or {}
            if (skill == "OBJECT_USE" and source == "mouseover"
                    and params.get("identity_certification") == QUEST_OBJECT_TOOLTIP):
                checked = IdentityCheck(quest_object_tooltip_matches(params, observed),
                                        QUEST_OBJECT_TOOLTIP)
            else:
                checked = check_entity_identity(wanted, observed)
            if binding == "INTERACTTARGET":
                checked = check_interaction_recipient(wanted, world, now, fallback=source)
            if checked and not sample_fresh(world, source, now):
                checked = IdentityCheck(False, "IDENTITY_SAMPLE_STALE")
            if checked and source == "mouseover":
                from wowbot.agent.pointer_tracking import world_pointer_blocked
                if world_pointer_blocked(world):
                    checked = IdentityCheck(False, "WORLD_POINTER_BLOCKED_BY_UI")
                if not sample_fresh(world, "cursor", now):
                    checked = IdentityCheck(False, "CURSOR_SAMPLE_STALE")
                mouse_time, cursor_time = world.get("mouseover_sample_time"), world.get("cursor_sample_time")
                if mouse_time is not None and cursor_time is not None:
                    try:
                        if abs(float(mouse_time) - float(cursor_time)) > .1:
                            checked = IdentityCheck(False, "CURSOR_IDENTITY_NOT_COSAMPLED")
                    except (TypeError, ValueError):
                        checked = IdentityCheck(False, "CURSOR_SAMPLE_INVALID")
                if checked and kind == "CLICK":
                    cursor = world.get("cursor_position") or {}
                    try:
                        if (abs(float(command.x) - float(cursor["nx"])) > .004
                                or abs(float(command.y) - float(cursor["ny"])) > .004):
                            checked = IdentityCheck(False, "CLICK_POINT_NOT_VERIFIED")
                    except (KeyError, TypeError, ValueError):
                        checked = IdentityCheck(False, "CLICK_POINT_UNKNOWN")
            if not checked:
                break
    return checked


def guard_skill_result(state, world: dict, result: SkillResult, now: float) -> SkillResult:
    """Guard every retry, but let pure credit/death verification observe despawn."""
    if (state.skill_type == "USE_ON_TARGET" and state.intent.parameters.get("purpose") == "DIRECTED_QUEST_ITEM"
            and result.commands):
        checked = check_command_identity(state.skill_type, state.intent.parameters, {}, world, result.commands, now)
        if not checked:
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN, replan_required=True,
                               metadata={"identity_check":checked.reason})
        return replace(result, metadata={**result.metadata,"identity_check":checked.reason})
    if entity_role(state.skill_type, state.intent.parameters) is None or not result.commands:
        return result
    if (state.skill_type == 'OBJECT_USE'
            and (state.skill_context.get('object_use') or {}).get('pull')
            and all(command.kind == 'BIND' and command.binding == 'MOVEBACKWARD'
                    and 0 < command.duration <= .3 for command in result.commands)):
        from wowbot.skills.object_pull import pull_identity
        if pull_identity(state,world):
            # This self movement retains the used server object; keeping
            # the old object under the pointer is not required to step back.
            return replace(result,metadata={**result.metadata,'identity_check':'POST_USE_PINNED_OBJECT_MOVEMENT'})
    wanted = pin_skill_identity(state, world)
    checked = check_command_identity(
        state.skill_type, state.intent.parameters, wanted, world, result.commands, now)
    if checked:
        return replace(result, metadata={**result.metadata, "identity_check": checked.reason})
    return SkillResult(
        SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
        retryable=True, replan_required=True,
        metadata={"identity_check": checked.reason, "expected_identity": dict(wanted),
                  "detail": "entity-directed input withheld; inspect/reacquire before retry"})


def identity_guarded(handler):
    """Apply the shared rule even to direct runtime/resume skill calls.

    This is a stateless boundary adapter, not another executor or skill FSM.
    The pin lives exclusively in the existing ActiveSkillState context.
    """
    @wraps(handler)
    def guarded(self, state, world_state=None, *args, **kwargs):
        world = world_state if world_state is not None else (getattr(state, "before_snapshot", None) or {})
        if not getattr(state, "intent", None) or not getattr(state, "skill_type", None):
            # Invalid/legacy context may still be observed for a pure terminal
            # verification. It can never gain input authority by duck typing.
            result = handler(self, state, world, *args, **kwargs)
            if result.commands:
                return SkillResult(SkillStatus.BLOCKED, FailureReason.IDENTITY_UNCERTAIN,
                                   replan_required=True,
                                   metadata={"identity_check": "CANONICAL_INTENT_REQUIRED"})
            return result
        pin_skill_identity(state, world)
        now = kwargs.get("now", args[0] if args else None)
        if now is None:
            now = (getattr(state, "started_at", None) if handler.__name__ == "begin"
                   else world.get("monotonic_time", getattr(state, "started_at", None)))
        if now is None:
            return SkillResult(SkillStatus.BLOCKED, FailureReason.IDENTITY_UNCERTAIN,
                               replan_required=True,
                               metadata={"identity_check": "SKILL_CLOCK_REQUIRED"})
        result = handler(self, state, world, *args, **kwargs)
        if (handler.__name__ == "begin" and result.status is SkillStatus.SUCCESS
                and entity_role(state.skill_type, state.intent.parameters) in {"target", "mouseover"}):
            checked = skill_identity_check(state, world.get("target") or {}, world)
            if not checked:
                return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                                   retryable=True, replan_required=True,
                                   metadata={"identity_check": checked.reason})
        return guard_skill_result(state, world, result, float(now))
    return guarded
