"""Read-only target hand-off proposal policy.

This module translates fresh addon mouseover evidence into TARGET/TALK
proposals.  It never clicks, mutates the WorldModel, or owns a target.
"""
from __future__ import annotations

from .models import Goal, Proposal, number
from .quest_giver_evidence import (friendly_npc_relevant, is_companion_pet, npc_objective_subjects,
                                   quest_search_allows_npc)
from .quest_semantics import target_matches_objective, target_matches_structured_entity
from .tooltip_quest import creature_tooltip_open, tooltip_objectives_done
from wowbot.vision.map_mouseover import classify_tooltip


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
    return (bool(unit.get("is_player"))
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
    return {"hover_x": x, "hover_y": y, "track_id": subject.get("track_id")}


class TargetPlanningPolicy:
    """Build target hand-off proposals from a coherent fresh cursor sample."""

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
        state = world.state
        mouse = state.get("mouseover") or {}
        surface = (state.get("map_mouseover") or {}).get("surface")
        result: list[Proposal] = []
        # User 2026-10-02: questing with no active quest selects only a quest
        # NPC -- a "!" over its box, or (no "!" anywhere) at an API giver spot.
        quest_search = getattr(goal, "domain", None) == "QUEST" and not state.get("active_quests")
        quest_model = getattr(world, "quest_model", None)
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
                     or friendly_npc_relevant(
                         state, str(mouse.get("guid")), objective_types,
                         unit_name=mouse.get("name"),
                         npc_subjects=npc_objective_subjects(
                             quest_model.ready() if quest_model is not None else ())))):
            cursor = state.get("cursor_position") or {}
            if number(cursor.get("nx")) is not None and number(cursor.get("ny")) is not None:
                result.append(Proposal.make(
                    "TARGET", "API-val azonosított mouseover NPC kijelölése",
                    {"x": cursor["nx"], "y": cursor["ny"], "guid": mouse["guid"],
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
                and mouse.get("dead", mouse.get("is_dead")) is not True
                and not state.get("is_in_combat")
                and (target.get("attackable", target.get("is_attackable")) is not True
                     or target.get("dead", target.get("is_dead")) is True)
                and ((mouse.get("quest_related") is True
                      and not tooltip_objectives_done(mouse)
                      and creature_tooltip_open(mouse, state))
                     or tooltip_names_active_quest(mouse, state)
                     or mouse.get("npc_id") in goal.parameters.get("target_npc_ids", [])
                     or any(target_matches_structured_entity(mouse, obj.target_entity)
                            or target_matches_objective(mouse, {**obj.raw, "description": obj.description})
                            for obj in world.quest_model.ready()))):
            relevant_units = getattr(getattr(world, "_model", None) or world, "quest_relevant_units", None)
            if isinstance(relevant_units, dict):
                relevant_units[str(mouse["guid"])] = number(state.get("monotonic_time")) or 0.
            cursor = state.get("cursor_position") or {}
            if number(cursor.get("nx")) is not None and number(cursor.get("ny")) is not None:
                result.append(Proposal.make(
                    "TARGET", "API-val azonosított, quest-releváns ellenséges mouseover kijelölése",
                    {"x": cursor["nx"], "y": cursor["ny"], "guid": mouse["guid"],
                     **_hover_box(state, str(mouse["guid"])),
                     "identity_source": mouse.get("identity_source") or "WOW_API_MOUSEOVER",
                     "ground_truth_handoff": True, "click_current_cursor": True},
                    confidence=1.0, priority=GROUND_TRUTH_MOUSEOVER_HANDOFF_PRIORITY))
        elif (surface not in {"MINIMAP", "WORLD_MAP"}
                and not mouse.get("guid") and cursor_matches_mouseover
                and not is_player_unit(mouse, state)
                and (mouse.get("tooltip_data") or {}).get("is_player") is not True
                and "(player)" not in str(mouse.get("tooltip") or "").casefold()
                and (mouse.get("tooltip_data") or {}).get("is_unit") is True
                and str(mouse.get("name") or (mouse.get("tooltip_data") or {}).get("unit_name") or "").strip()
                and str(mouse.get("name") or (mouse.get("tooltip_data") or {}).get("unit_name"))
                    != str(state.get("character_name") or "")
                and (not quest_search or quest_search_allows_npc(state, ""))):
            cursor = state.get("cursor_position") or {}
            if number(cursor.get("nx")) is not None and number(cursor.get("ny")) is not None:
                unit_name = str(mouse.get("name") or
                                (mouse.get("tooltip_data") or {}).get("unit_name")).strip()
                result.append(Proposal.make(
                    "TARGET", "Strukturált unit-tooltip kijelölési próbája; GUID ellenőrzés kattintás után",
                    {"x": cursor["nx"], "y": cursor["ny"], "expected_name": unit_name,
                     "identity_source": "TOOLTIP_PRIMARY_DATA", "partial_identity": True,
                     "ground_truth_handoff": True, "click_current_cursor": True},
                    confidence=.95, priority=GROUND_TRUTH_MOUSEOVER_HANDOFF_PRIORITY-1))
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
                    {"guid": mouse["guid"], "quest_role": mouse_role, "tooltip_age": tooltip_age},
                    priority=68,
                ))
        if (state.get("vehicle_controls") and mouse.get("guid")
                and mouse.get("guid") != target.get("guid")
                and surface not in {"MINIMAP", "WORLD_MAP"} and cursor_matches_mouseover
                and not is_player_unit(mouse, state)
                and mouse.get("dead", mouse.get("is_dead")) is not True
                and not any(proposal.skill == "TARGET" for proposal in result)
                and any(target_matches_objective(mouse, {**obj.raw, "description": obj.description})
                        for obj in world.quest_model.ready()
                        if str(getattr(obj, "type", "") or "").upper() in {"KILL", "KILL_NAMED"})):
            # Live 2026-10-04: the Monstrous Cadavers (ClientActor, not
            # attackable) are trampled by the ridden Giant Boar; the hostile
            # rule above never selected them.
            cursor = state.get("cursor_position") or {}
            if number(cursor.get("nx")) is not None and number(cursor.get("ny")) is not None:
                result.append(Proposal.make(
                    "TARGET", "Járművel: a quest-célpont nevű mouseover kijelölése",
                    {"x": cursor["nx"], "y": cursor["ny"], "guid": mouse["guid"],
                     **_hover_box(state, str(mouse["guid"])),
                     "identity_source": mouse.get("identity_source") or "WOW_API_MOUSEOVER",
                     "ground_truth_handoff": True, "click_current_cursor": True},
                    confidence=1.0, priority=GROUND_TRUTH_MOUSEOVER_HANDOFF_PRIORITY))
        return result
