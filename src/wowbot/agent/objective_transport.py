"""Resolve a named quest transport to current server vehicle candidates only."""
from __future__ import annotations

import re

from .models import number, words
from .packet_entity_facts import best_position
from .quest_semantics import npc_name_matches
from wowbot.runtime.entity_identity import guid_template
from wowbot.runtime.skill_identity import sample_fresh


def transport_subject(description) -> str | None:
    text = words(str(description or ""))
    match = re.search(r"\b(?:travel|fly|ride)\s+with\s+(.+?)(?:\s+(?:to|towards|toward|at)\s+|$)", text)
    return match[1].strip() if match else None


def transport_entries(state: dict) -> dict[str, str]:
    """Template hints for 'Travel with X', requiring a live matching vehicle.

    TDB/client names narrow candidates; the interaction policy still needs
    the fresh exact recipient GUID. A nearby unrelated mount is not a ride.
    """
    wanted = [(str(q["quest_id"]), name) for q in state.get("active_quests") or ()
              if isinstance(q, dict) and q.get("quest_id") is not None and not q.get("is_complete")
              for o in q.get("objectives") or () if isinstance(o, dict) and not o.get("is_complete")
              and (name := transport_subject(o.get("description")))]
    if not wanted:
        return {}
    now = number(state.get("monotonic_time"))
    player = state.get("player_world_position") or {}
    reference = state.get("reference_knowledge") or {}
    result = {}
    for value in (state.get("packet_entities") or {}).values():
        if (not isinstance(value, dict) or value.get("kind") != "VEHICLE" or value.get("removed")
                or str(value.get("map_id")) != str(player.get("instance_id"))
                or value.get("dead", value.get("is_dead")) is True
                or (value.get("unit") or {}).get("health") == 0
                or best_position(value) is None):
            continue
        guid, entry = str(value.get("guid") or ""), str(value.get("entry_id"))
        if str(guid_template(guid).get("npc_id")) != entry:
            continue
        names = []
        record = (reference.get("entities") or {}).get(entry) or {}
        name = (record.get("reference") or {}).get("name")
        if name:
            names.append(str(name))
        for source, units in (("target", [state.get("target")]), ("soft_targets", state.get("soft_targets") or ())):
            if now is None or not sample_fresh(state, source, now):
                continue
            names.extend(str(unit["name"]) for unit in units if isinstance(unit, dict) and unit.get("name")
                         and str(unit.get("guid") or "") == guid
                         and unit.get("attackable", unit.get("is_attackable")) is not True)
        for qid, subject in wanted:
            quest = (reference.get("quests") or {}).get(qid) or {}
            named = [n for row in quest.get("objectives") or () if isinstance(row, dict)
                     for n in row.get("named_creatures") or ()
                     if isinstance(n, dict) and str(n.get("entry")) == entry and n.get("name")]
            if any(npc_name_matches(subject, name) for name in [*names, *(n["name"] for n in named)]):
                result[entry] = qid
                break
    return result
