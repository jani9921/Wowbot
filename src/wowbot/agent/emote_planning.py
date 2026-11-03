"""Quest emotes at an NPC (REV4 P8.4 EMOTE, user 2026-11-02).

"Dance with Tommy Joe", "/cheer", "Salute given": the server credits the
emote received by the named creature from the player who targets it.  The
addon (0.9.83) puts the emote its open objective names on one secure button
the user binds ("AIPC: quest emote") and exports which one it is.  The agent
re-checks that word in the same objective text, finds the subject among the
server's units (the objective's TDB creatures), walks up, selects it with
Ctrl+Tab (GUID verified afterwards) and presses the binding; only quest
credit verifies it.
"""
from __future__ import annotations

import math

from .models import Proposal, number

PRIORITY = 65.
EMOTE_YARDS = 10.
FRIEND_TAB_YARDS = 6.


def _subject_entries(state: dict, quest_id: str, text: str) -> set[str]:
    from .quest_reference_matching import reference_objectives
    ref = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(quest_id) or {}
    rows = reference_objectives(quest_id, None, text, ref.get("objectives") or [])
    if len(rows) != 1:
        return set()
    row = rows[0]
    entries = {str(c["entry"]) for field in ("named_creatures", "talk_creatures", "talk_actor_candidates")
               for c in row.get(field) or () if isinstance(c, dict) and c.get("entry") is not None}
    if row.get("raw_type") == 0 and number(row.get("credit_object_id")) and row["credit_object_id"] > 0:
        entries.add(str(row["credit_object_id"]))
    return entries


def emote_task(state: dict) -> dict | None:
    """The exported emote, re-checked against its open objective's own text."""
    from wowbot.quests.objective_mechanics import text_hint
    action = state.get("emote_action") or {}
    word = str(action.get("word") or "").casefold()
    if (action.get("applied") is not True or action.get("kind") != "EMOTE"
            or not action.get("emote") or not word):
        return None
    quest = next((q for q in state.get("active_quests") or () if isinstance(q, dict)
                  and str(q.get("quest_id")) == str(action.get("quest_id")) and q.get("is_complete") is not True), None)
    index = action.get("objective_index")
    objectives = (quest or {}).get("objectives") or ()
    if quest is None or type(index) is not int or not 0 <= index < len(objectives):
        return None
    row = objectives[index]
    text = str(row.get("description") or "")
    if row.get("is_complete") is True or word not in text.casefold() or text_hint(text) != "EMOTE":
        return None
    qid = str(quest.get("quest_id"))
    return {"quest_id": qid, "objective_id": str(row.get("objective_id") or f"{qid}:{index}"), "text": text,
            "emote": action["emote"], "binding": str(action.get("binding") or "").upper(),
            "entries": _subject_entries(state, qid, text)}


def abandon_failed(state: dict) -> Proposal | None:
    """A FAILED quest (escort died, timer out) on the addon button: abandon
    it so the giver offers it again (the shared accept flow re-takes it)."""
    action = state.get("emote_action") or {}
    quest = next((q for q in state.get("active_quests") or () if isinstance(q, dict)
                  and str(q.get("quest_id")) == str(action.get("quest_id")) and q.get("is_failed") is True), None)
    if action.get("applied") is not True or action.get("kind") != "ABANDON_FAILED" or quest is None:
        return None
    return Proposal.make(
        "ADDON_ACTION", "Elbukott quest eldobása az AIPC gombbal, hogy újra felvehető legyen",
        {"quest_ids": [str(quest["quest_id"])], "binding": str(action.get("binding") or "").upper(),
         "action_kind": "ABANDON_FAILED"},
        confidence=.9, priority=75., evidence=("quest_log_failed", "addon_quest_action_button"))


class EmotePolicy:
    def propose(self, state: dict) -> list[Proposal]:
        if state.get("is_in_combat") or state.get("is_dead") or state.get("is_ghost") or state.get("in_vehicle"):
            return []
        abandon = abandon_failed(state)
        if abandon is not None:
            return [abandon]
        task = emote_task(state)
        if task is None or not task["entries"]:
            return []
        from .packet_entity_facts import best_position, unit_dead
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        if px is None or py is None:
            return []
        subjects = []
        for value in (state.get("packet_entities") or {}).values():
            if (not isinstance(value, dict) or value.get("kind") != "CREATURE" or value.get("removed")
                    or str(value.get("entry_id")) not in task["entries"] or unit_dead(value)):
                continue
            point = best_position(value)
            if point is not None and str(point.get("instance_id")) == str(player.get("instance_id")):
                subjects.append((math.hypot(point["x"]-px, point["y"]-py), str(value["guid"]), point))
        if not subjects:
            return []
        distance, guid, point = min(subjects)
        common = {"quest_ids": [task["quest_id"]], "objective_ids": [task["objective_id"]]}
        target = str((state.get("target") or {}).get("guid") or "")
        chosen = next((row for row in subjects if row[1] == target), None)
        if chosen is not None and chosen[0] <= EMOTE_YARDS:
            return [Proposal.make(
                "ADDON_ACTION", f"Quest emote ({task['emote']}) a kijelölt NPC-nek, az addon gombjával",
                {**common, "binding": task["binding"], "emote": task["emote"], "guid": target,
                 "action_kind": "EMOTE"},
                confidence=.85, priority=PRIORITY, evidence=("addon_emote_button", "objective_emote"))]
        if distance <= FRIEND_TAB_YARDS:
            return [Proposal.make(
                "TARGET", "Quest emote: az NPC kijelölése Ctrl+Tabbal (GUID-ellenőrzéssel)",
                {**common, "guid": guid, "activation_source": "TAB_FRIEND_RESCUE", "purpose": "EMOTE_SUBJECT",
                 "acceptable_guids": sorted(row[1] for row in subjects)[:12]},
                confidence=.8, priority=PRIORITY, evidence=("server_unit_position", "objective_emote"))]
        return [Proposal.make(
            "MOVE", "Quest emote: odamegyek az NPC-hez",
            {**common, "x": point["x"], "y": point["y"], "z": point.get("z"), "z_known": point.get("z") is not None,
             "z_source": "PACKET_ENTITY", "coordinate_space": "WORLD_YARDS", "instance_id": point["instance_id"],
             "map_id": state.get("map_id"), "purpose": "EMOTE_SUBJECT_APPROACH", "require_navmesh": True,
             "stop_distance": 3., "face_on_arrival": True, "server_entity_guid": guid,
             "quest_id": task["quest_id"]},
            confidence=.8, priority=PRIORITY, evidence=("server_unit_position", "objective_emote"))]
