"""QuestDomain's bounded subject-location memory, separate from live identity."""
from __future__ import annotations

import math

from .models import Proposal, number
from .packet_entity_facts import best_position, interaction_position
from .quest_reference_matching import reference_objectives
from .quest_search_hints import objective_poi_points, subject_search_proposal
from .tooltip_quest import known_dead_unit

SEARCH_PURPOSE = "SEARCH_QUEST_ITEM_SUBJECT"
MEMORY_SECONDS = 600.


def context(state):
    return (str((state.get("player_world_position") or {}).get("instance_id")),
            str(state.get("map_id")), str(state.get("phase")))


def key(state, objective_id, guid):
    return (str(state.get("session_id")), str(objective_id), str(guid))


def same_site(a, b, radius=3.):
    return (a and b and str(a.get("instance_id")) == str(b.get("instance_id"))
            and all(number(p.get(k)) is not None for p in (a, b) for k in ("x", "y", "z"))
            and math.hypot(a["x"]-b["x"], a["y"]-b["y"]) <= radius
            and abs(a["z"]-b["z"]) <= 2.)


def remember_subjects(visits, obj, state, now):
    entry = (obj.target_entity or {}).get("npc_id")
    scope = context(state)
    for unit in (state.get("packet_entities") or {}).values():
        if (not isinstance(unit, dict) or str(unit.get("entry_id")) != str(entry)
                or not unit.get("guid") or unit.get("kind") not in {"CREATURE", "VEHICLE"}):
            continue
        identity = key(state, obj.objective_id, unit["guid"])
        removed = unit.get("removed") or {}
        removal = removed.get("reason") if isinstance(removed, dict) else "UNKNOWN"
        if removed and removal != "OUT_OF_RANGE" or known_dead_unit(unit, state):
            if identity in visits:
                visits[identity]["retired"] = True
            continue
        point = best_position(unit)
        if (not point or str(point.get("instance_id")) != scope[0]
                or not all(number(point.get(k)) is not None and math.isfinite(point[k]) for k in ("x", "y", "z"))):
            continue
        age = number(point.get("age"))
        if removed and (age is None or not 0 <= age <= MEMORY_SECONDS):
            continue
        visit = visits.setdefault(identity, {})
        if visit.get("context") not in (None, scope):
            visit.clear()
        visit.update(context=scope, position={k: point[k] for k in ("x", "y", "z", "instance_id")},
                     seen_at=now-age if removed else now)
        visit.setdefault("first_seen", now)
        if not removed:
            visit.pop("retired", None)
        # Healing can replace the injured actor with a departing animation
        # actor of the same entry at the same spot. Briefly defer a NEW GUID;
        # never transfer identity or claim that the replacement was healed.
        for other_key, other in list(visits.items()):
            credited = number(other.get("credited_at"))
            if (other_key != identity and other_key[:2] == identity[:2]
                    and other.get("context") == scope and credited is not None
                    and 0 <= now-credited < 15. and visit["first_seen"] >= credited-1.
                    and same_site(visit["position"], other.get("position"), 1.5)):
                visit["settling_until"] = credited+15.
    while len(visits) > 256:
        visits.pop(next(iter(visits)))


def search_proposal(visits, obj, record, state, now):
    reference = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(record.quest_id)) or {}
    rows = reference_objectives(record.quest_id, obj.objective_id, obj.description,
                                reference.get("objectives") or ())
    points, hints = (objective_poi_points(state, record.quest_id, rows[0]["objective_id"], rows[0].get("order"))
                     if len(rows) == 1 else ([], []))
    excluded = []
    for identity, visit in visits.items():
        if (identity[:2] != key(state, obj.objective_id, "")[:2]
                or visit.get("context") != context(state)
                or not 0 <= now-visit.get("seen_at", float("-inf")) <= MEMORY_SECONDS):
            continue
        point = visit.get("position")
        if not point:
            continue
        # Keep geometry independent of removal/credit counters, so the shared
        # coverage does not restart after each heal or packet-cache eviction.
        if not any(same_site({**p, "instance_id": point["instance_id"]}, point) for p in points):
            points.append({k: point[k] for k in ("x", "y", "z")})
        if visit.get("retired") or max(visit.get("used_until", 0.), visit.get("settling_until", 0.)) > now:
            excluded.append(point)
    proposal = subject_search_proposal(state, record.quest_id, obj.objective_id,
        [(obj.target_entity or {}).get("npc_id")], points, hints,
        purpose=SEARCH_PURPOSE, reason="Quest item: a még hiányzó NPC keresése az ismert helyeken",
        excluded_points=excluded)
    if proposal is not None:
        return Proposal.make(proposal.skill, proposal.reason,
            {**proposal.parameters, "quest_item_id": (obj.target_object or {}).get("item_id")},
            proposal.confidence, proposal.priority, proposal.evidence)
    return proposal


def search_actor_available(params, state):
    """Fresh matching actor interrupts search, but authorizes no use or click."""
    if params.get("purpose") != SEARCH_PURPOSE:
        return None
    quest = next((q for q in state.get("active_quests") or ()
                  if str(q.get("quest_id")) == str(params.get("quest_id")) and not q.get("is_complete")), None)
    if quest is None:
        return None
    from .quest_semantics import healing_subject
    if (str((quest.get("special_item") or {}).get("item_id")) != str(params.get("quest_item_id"))
            or not any(str(row.get("objective_id", f"{quest['quest_id']}:{i}")) == str(params.get("objective_id"))
                       and not row.get("is_complete") and healing_subject(row)
                       for i, row in enumerate(quest.get("objectives") or ()))):
        return None
    entries = set(map(str, params.get("expected_npc_ids") or ()))
    for unit in (state.get("packet_entities") or {}).values():
        if str(unit.get("entry_id")) not in entries or known_dead_unit(unit, state):
            continue
        point = interaction_position(state, unit.get("guid"))
        if point and not any(same_site(point, p) for p in params.get("excluded_search_points") or ()):
            return unit["guid"]
    return None
