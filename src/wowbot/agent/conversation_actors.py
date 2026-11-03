"""Resolve an explicitly addressed live talk objective to current server actors.

Names identify candidate templates only. Actual interaction keeps its fresh
GUID/soft-recipient gate; no GUID is transferred between creature instances.
"""
from __future__ import annotations

from wowbot.query_ports import TravelCostPort
from .models import number
from .quest_reference_matching import objective_text_key
from .quest_semantics import (npc_name_candidate_matches, npc_name_subjects,
                             talk_to_subject, unique_npc_name_candidates)
from wowbot.runtime.entity_identity import (check_entity_identity, guid_template,
                                          identity_fields, template_id)
from wowbot.runtime.skill_identity import sample_fresh


def conversation_actors(state, quest_id, description=None, *,
                        travel_cost: TravelCostPort | None = None):
    quest = next((q for q in state.get("active_quests") or ()
                  if str(q.get("quest_id")) == str(quest_id) and q.get("is_complete") is not True), None)
    if not quest:
        return []
    objectives = [row for row in quest.get("objectives") or () if isinstance(row, dict)
                  and row.get("is_complete") is not True
                  and (description is None or objective_text_key(row.get("description")) == objective_text_key(description))]
    if not objectives:
        return []
    player = state.get("player_world_position") or {}
    visible_units = [u for u in (state.get("packet_entities") or {}).values()
               if u.get("kind") in {"CREATURE", "VEHICLE"} and not u.get("removed")
               and u.get("dead") is not True and u.get("is_dead") is not True
               and str(u.get("map_id")) == str(player.get("instance_id"))
               and type((u.get("info") or {}).get("npc_flags")) is int
               and (u["info"]["npc_flags"] & 3)
               and guid_template(u.get("guid")).get("npc_id") == template_id(u.get("entry_id"))]
    visible = {str(u.get("entry_id")) for u in visible_units}
    visible_guids = {str(u.get("guid")): u for u in visible_units}
    ref = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(quest_id)) or {}
    client_names = []
    now = number(state.get("monotonic_time"))
    for source, units in (("target", [state.get("target")]), ("mouseover", [state.get("mouseover")]),
                          ("soft_targets", state.get("soft_targets") or ())):
        if now is None or not sample_fresh(state, source, now):
            continue
        for unit in units:
            if (not isinstance(unit, dict) or not unit.get("name")
                    or unit.get("attackable", unit.get("is_attackable")) is True
                    or unit.get("dead", unit.get("is_dead")) is True):
                continue
            entry = template_id(unit.get("npc_id"))
            parsed = guid_template(unit.get("guid"))
            if (entry is None or parsed.get("npc_id") != entry or str(entry) not in visible
                    or str(unit.get("guid")) not in visible_guids):
                continue
            client_names.append({"entry": entry, "name": unit["name"], "source": "CURRENT_CLIENT_SERVER_ACTOR"})

    result = {}
    for objective in objectives:
        from .quest_contextual_talk import speakers_at_objective
        explicit = identity_fields(objective.get("target_entity") or {})
        for speaker in speakers_at_objective(state, quest_id, objective, ref, visible_units,
                                             travel_cost=travel_cost):
            entry = template_id(speaker.get('entry'))
            if (not explicit or any(check_entity_identity(explicit,
                    {'npc_id': entry, 'guid': unit['guid']}) for unit in visible_units
                    if template_id(unit.get('entry_id')) == entry)):
                result.setdefault(entry, speaker)
        subject = talk_to_subject(objective)
        if not subject:
            continue
        key = objective_text_key(objective.get("description"))
        references = [row for row in ref.get("objectives") or () if isinstance(row, dict)
                      and objective_text_key(row.get("description")) == key]
        roles = [{"entry": entry, "name": row.get("name"), "source": "QUEST_ROLE_CURRENT_SERVER_ACTOR"}
                 for row in ref.get("quest_roles") or () if isinstance(row, dict)
                 and (entry := template_id(row.get("npc_id"))) is not None and str(entry) in visible]
        static = [{**actor, "source": "TDB_OBJECTIVE_CURRENT_SERVER_ACTOR"}
                  for row in references for field in ("talk_creatures", "talk_actor_candidates")
                  for actor in row.get(field) or () if isinstance(actor, dict)
                  and str(actor.get("entry")) in visible]
        # A generic role needs quest/TDB context. A single currently hovered
        # 'Captain' is not proof that no other matching captain is nearby.
        is_role = subject.startswith("the ")
        contextual_entries = {str(row["entry"]) for row in [*roles, *static]}
        clients = [row for row in client_names if not is_role or str(row["entry"]) in contextual_entries]
        pool = [*roles, *static, *clients]
        explicit = identity_fields(objective.get("target_entity") or {})
        from .quest_speaker_context import speakers_at_subject
        for speaker in speakers_at_subject(state, quest_id, subject, ref):
            entry = template_id(speaker.get('entry'))
            actors = [u for u in visible_units if template_id(u.get('entry_id')) == entry
                      and (not explicit or check_entity_identity(explicit,
                           {'npc_id': entry, 'guid': u['guid']}))]
            if actors:
                result.setdefault(entry, speaker)
        if explicit:
            pool = [row for row in pool if any(check_entity_identity(explicit,
                    {"npc_id": row["entry"], "guid": unit["guid"]}) for unit in visible_units
                    if str(unit["entry_id"]) == str(row["entry"]))]

        def addresses(row):
            return (npc_name_candidate_matches(subject, row.get("name")) or is_role and any(
                npc_name_candidate_matches(subject, title) for title in row.get("titles") or ()))

        pool = [row for row in pool if addresses(row)]
        # Resolve each explicitly coordinated actor separately. The original
        # group filter above prevents 'Left' in 'Left and Right' becoming
        # 'Left Shark'. One full name can have several current entry variants.
        for part in npc_name_subjects(subject):
            preferred = [row for row in pool if row.get("source") == "QUEST_ROLE_CURRENT_SERVER_ACTOR"
                         and npc_name_candidate_matches(part, row.get("name"))]
            chosen = unique_npc_name_candidates(part, preferred or pool)
            for actor in chosen:
                entry = template_id(actor.get("entry"))
                if entry is not None:
                    result.setdefault(entry, {"entry": entry, "name": actor["name"], "source": actor["source"]})
    return list(result.values())
