"""Read-only target hand-off proposal policy.

This module translates fresh addon mouseover evidence into TARGET/TALK
proposals.  It never clicks, mutates the WorldModel, or owns a target.
"""
from __future__ import annotations

from wowbot.runtime.entity_identity import identity_fields

from .models import Goal, Proposal, number
from .quest_giver_evidence import (friendly_npc_relevant, is_companion_pet, npc_objective_subjects,
                                   quest_search_allows_npc)
from .quest_semantics import target_matches_objective, target_matches_structured_entity, speak_target_matches
from .tooltip_quest import creature_tooltip_open, tooltip_objectives_done
from wowbot.map_mouseover import classify_tooltip


GROUND_TRUTH_MOUSEOVER_HANDOFF_PRIORITY = 72
TARGET_HANDOFF_MAX_SAMPLE_AGE_SECONDS = .35


def interaction_out_of_range(state: dict) -> bool:
    """Treat the client's explicit range error as evidence, not target loss."""
    message = str(state.get("ui_error") or "").casefold()
    return any(token in message for token in (
        "need to be closer", "too far away", "out of range", "közelebb", "túl messze"))


def is_player_unit(unit: dict, state: dict) -> bool:
    """Authoritative exclusion: a player mouseover is never an NPC fact."""
    if not isinstance(unit, dict):
        return False
    # Live 2026-10-05: the addon exports no is_player for target/mouseover; a
    # click meant for Jaina selected another player standing in front of
    # her and the agent followed him 47 yd.  The GUID type is authoritative.
    return (bool(unit.get("is_player"))
            or str(unit.get("guid") or "").startswith("Player-")
            or str(unit.get("unit_type") or "").upper() == "PLAYER"
            or bool(unit.get("guid") and unit.get("guid") == state.get("character_guid")))


def tooltip_names_active_quest(mouse: dict, state: dict) -> bool:
    """The hovered unit's own tooltip lists an unfinished active quest."""
    from .tooltip_quest import tooltip_quest_id
    return tooltip_quest_id(mouse, state) is not None


def _hover_box(state: dict, guid: str) -> dict:
    """The hovered unit's live World3D box, for hover-confirm-click TARGET."""
    from .quest_giver_evidence import hovered_subject
    subject = hovered_subject(state, guid)
    x, y = number((subject or {}).get("x")), number((subject or {}).get("y"))
    if subject is None or x is None or y is None or not (0 < x < 1 and 0 < y < 1):
        return {}
    from .track_motion import predicted_point
    x, y = predicted_point(subject, state) or (x, y)
    return {"hover_x": x, "hover_y": y, "track_id": subject.get("track_id")}


def _dead_or_spent(world, unit: dict) -> bool:
    """Any death flag, or this agent's own fresh kill / looted corpse.

    Live 2026-10-10 17:25:05: right after looting a Murloc Spearhunter the
    cursor still rested on its corpse and the enemy-mouseover TARGET selected
    it; the agent then waited on a dead target until the user pressed ESC.
    The FAST and STATE lanes spell the flag differently ("is_dead"/"dead"),
    so a single fallback lookup can miss it.
    """
    from .tooltip_quest import known_dead_unit
    if known_dead_unit(unit, getattr(world, "state", {})):
        return True
    guid = str(unit.get("guid") or "")
    model = getattr(world, "_model", None) or world
    owned = getattr(model, "owned_corpse_guids", None) or {}
    looted = getattr(model, "looted_corpse_guids", None) or {}
    return bool(guid) and (guid in owned or guid in looted)


class TargetPlanningPolicy:
    """Build target hand-off proposals from a coherent fresh cursor sample."""

    # Live 2026-10-13 05:55:00: the World3D candidate list was empty for
    # ~1 s while Bjorn was hovered next to Alaria's "!"; "no ! visible"
    # then let the giver-pin rule select Bjorn, who had nothing to give.
    SYMBOL_HOLD_SECONDS = 2.5

    def _with_recent_symbol(self, state: dict) -> dict:
        from .quest_giver_evidence import quest_symbol_visible
        now = number(state.get("monotonic_time"))
        if now is None:
            return state
        if quest_symbol_visible(state):
            self.__dict__["_symbol_seen_at"] = now
            return state
        seen = self.__dict__.get("_symbol_seen_at")
        if seen is not None and 0 <= now - seen <= self.SYMBOL_HOLD_SECONDS:
            return {**state, "recent_quest_symbol_visible": True}
        return state

    def propose(
        self,
        world,
        goal: Goal,
        *,
        target: dict,
        cursor_matches_mouseover: bool,
        state_time: float | None,
        mouse_time: float | None,
        skip_friendly_guids: frozenset[str] = frozenset(),
    ) -> list[Proposal]:
        state = self._with_recent_symbol(world.state)
        mouse = state.get("mouseover") or {}
        surface = (state.get("map_mouseover") or {}).get("surface")
        result: list[Proposal] = []
        # User 2026-10-02: questing with no active quest selects only a quest
        # NPC -- a "!" over its box, or (no "!" anywhere) at an API giver spot.
        quest_search = getattr(goal, "domain", None) == "QUEST" and not state.get("active_quests")
        quest_model = getattr(world, "quest_model", None)
        ready = quest_model.ready() if quest_model is not None else ()
        objective_types = {str(getattr(obj, "type", "") or "") for obj in
                           (quest_model.ready() if quest_model is not None else ())}
        if (surface not in {"MINIMAP", "WORLD_MAP"} and mouse.get("guid")
                and mouse.get("guid") != target.get("guid")
                and not is_player_unit(mouse, state)
                and cursor_matches_mouseover
                and (mouse.get("npc_id") is not None
                     or str(mouse.get("unit_type") or "").upper() in {"NPC", "CREATURE"})
                and mouse.get("attackable", mouse.get("is_attackable")) is False
                and str(mouse.get("guid")) not in skip_friendly_guids
                and not is_companion_pet(mouse)
                and (getattr(goal, "domain", None) != "QUEST"
                     or any(speak_target_matches(obj, mouse) for obj in ready)
                     or friendly_npc_relevant(
                         state, str(mouse.get("guid")), objective_types,
                         unit_name=mouse.get("name"),
                         npc_subjects=npc_objective_subjects(
                             quest_model.ready() if quest_model is not None else ())))):
            cursor = state.get("cursor_position") or {}
            if number(cursor.get("nx")) is not None and number(cursor.get("ny")) is not None:
                result.append(Proposal.make(
                    "TARGET", "API-val azonosított mouseover NPC kijelölése",
                    {"x": cursor["nx"], "y": cursor["ny"], "guid": mouse["guid"], **identity_fields(mouse),
                     **_hover_box(state, str(mouse["guid"])),
                     "identity_source": mouse.get("identity_source") or "WOW_API_MOUSEOVER",
                     "ground_truth_handoff": True, "click_current_cursor": True},
                    confidence=1.0, priority=GROUND_TRUTH_MOUSEOVER_HANDOFF_PRIORITY))
        elif (surface not in {"MINIMAP", "WORLD_MAP"} and mouse.get("guid")
                and mouse.get("guid") != target.get("guid")
                and not is_player_unit(mouse, state)
                and cursor_matches_mouseover
                and (mouse.get("npc_id") is not None
                     or str(mouse.get("unit_type") or "").upper() in {"NPC", "CREATURE"})
                and mouse.get("attackable", mouse.get("is_attackable")) is True
                and not _dead_or_spent(world, mouse)
                and not state.get("is_in_combat")
                and (target.get("attackable", target.get("is_attackable")) is not True
                     or target.get("dead", target.get("is_dead")) is True)
                and ((mouse.get("quest_related") is True
                      and not tooltip_objectives_done(mouse)
                      and creature_tooltip_open(mouse, state))
                     or tooltip_names_active_quest(mouse, state)
                     or mouse.get("npc_id") in goal.parameters.get("target_npc_ids", [])
                     or any(target_matches_structured_entity(mouse, obj.target_entity)
                            or target_matches_objective(mouse, {**obj.raw, "target_entity": obj.target_entity, "description": obj.description})
                            for obj in world.quest_model.ready()))):
            relevant_units = getattr(getattr(world, "_model", None) or world, "quest_relevant_units", None)
            if isinstance(relevant_units, dict):
                relevant_units[str(mouse["guid"])] = number(state.get("monotonic_time")) or 0.
            cursor = state.get("cursor_position") or {}
            if number(cursor.get("nx")) is not None and number(cursor.get("ny")) is not None:
                result.append(Proposal.make(
                    "TARGET", "API-val azonosított, quest-releváns ellenséges mouseover kijelölése",
                    {"x": cursor["nx"], "y": cursor["ny"], "guid": mouse["guid"], **identity_fields(mouse),
                     **_hover_box(state, str(mouse["guid"])),
                     "identity_source": mouse.get("identity_source") or "WOW_API_MOUSEOVER",
                     "ground_truth_handoff": True, "click_current_cursor": True},
                    confidence=1.0, priority=GROUND_TRUTH_MOUSEOVER_HANDOFF_PRIORITY))
        # A structured name without a GUID remains a search hint. Do not
        # turn it into a TARGET action and certify identity after clicking.
        if (surface not in {"MINIMAP", "WORLD_MAP"}
                and mouse.get("guid") and mouse.get("guid") == target.get("guid")):
            mouse_role = classify_tooltip(mouse.get("tooltip"))
            if (mouse_role in {"QUEST_GIVER", "QUEST_TURN_IN"}
                    and mouse.get("attackable", mouse.get("is_attackable")) is False
                    and not (state.get("quest_ui") or {}).get("open")):
                tooltip_age = (round(state_time-mouse_time, 3)
                               if state_time is not None and mouse_time is not None else None)
                result.append(Proposal.make(
                    "TALK",
                    f"Tooltip alapján felismert {mouse_role.lower()} (3D-világ mouseover ground truth) "
                    f"[tooltip='{str(mouse.get('tooltip') or '')[:60]}' age={tooltip_age}]",
                    {"guid": mouse["guid"], **identity_fields(mouse), "quest_role": mouse_role, "tooltip_age": tooltip_age},
                    priority=68,
                ))
        if (state.get("vehicle_controls") and mouse.get("guid")
                and mouse.get("guid") != target.get("guid")
                and surface not in {"MINIMAP", "WORLD_MAP"} and cursor_matches_mouseover
                and not is_player_unit(mouse, state)
                and mouse.get("dead", mouse.get("is_dead")) is not True
                and not any(proposal.skill == "TARGET" for proposal in result)
                and any(target_matches_objective(mouse, {**obj.raw, "target_entity": obj.target_entity, "description": obj.description})
                        for obj in world.quest_model.ready()
                        if str(getattr(obj, "type", "") or "").upper() in {"KILL", "KILL_NAMED"})):
            # Live 2026-10-04: the Monstrous Cadavers (ClientActor, not
            # attackable) are trampled by the ridden Giant Boar; the hostile
            # rule above never selected them.
            cursor = state.get("cursor_position") or {}
            if number(cursor.get("nx")) is not None and number(cursor.get("ny")) is not None:
                result.append(Proposal.make(
                    "TARGET", "Járművel: a quest-célpont nevű mouseover kijelölése",
                    {"x": cursor["nx"], "y": cursor["ny"], "guid": mouse["guid"], **identity_fields(mouse),
                     **_hover_box(state, str(mouse["guid"])),
                     "identity_source": mouse.get("identity_source") or "WOW_API_MOUSEOVER",
                     "ground_truth_handoff": True, "click_current_cursor": True},
                    confidence=1.0, priority=GROUND_TRUTH_MOUSEOVER_HANDOFF_PRIORITY))
        return result
