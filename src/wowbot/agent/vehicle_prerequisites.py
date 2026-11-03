"""A completed boarding credit is not proof that the player is still aboard.

Use per-objective, persisted progress evidence and the reference's exact
boarding actor. Normal planner / MOVE / INTERACT / verification own execution.
No quest counter, GUID, vehicle position or key binding is invented here.
"""
from __future__ import annotations

from wowbot.query_ports import TravelCostPort
from .models import Proposal, number
from .quest_reference_matching import objective_text_key, reference_objectives


def learned_requirements(state: dict, memory) -> list[dict]:
    """Vehicle stages still open, including after a new WorldModel/session.

    A SPELLCLICK alone is not a vehicle (healing/rescuing uses it too).
    Its completed credit must have actually progressed aboard a vehicle.
    Later objectives proven on foot need no vehicle; unknown later stages
    are not swept into the dependency just because the quest once used one.
    """
    references = (state.get("reference_knowledge") or {}).get("quests") or {}
    result = []
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        qid = str(quest.get("quest_id") or "")
        objectives = quest.get("objectives") or ()
        rows = (references.get(qid) or {}).get("objectives") or ()
        if not rows or not objectives:
            continue
        progress = memory.progress(qid)

        def history(index, objective):
            key = objective_text_key(objective.get("description"))
            return [p for p in progress if p.get("objective") == index and key
                    and objective_text_key(p.get("description")) == key
                    and (number(p.get("count")) or 0) > 0]

        boarding = []
        for index, objective in enumerate(objectives):
            if not isinstance(objective, dict) or objective.get("is_complete") is not True:
                continue
            matches = reference_objectives(qid, objective.get("objective_id", f"{qid}:{index}"),
                                           objective.get("description"), rows)
            if len(matches) != 1:
                continue
            row = matches[0]
            action = row.get("credit_action")
            if action not in {"RIDE", "SPELLCLICK"}:
                continue
            if not any(p.get("in_vehicle") for p in history(index, objective)):
                continue
            actors = row.get("spellclick_creatures") if action == "SPELLCLICK" else row.get("named_creatures")
            entries = sorted({str(a["entry"]) for a in actors or ()
                              if isinstance(a, dict) and (number(a.get("entry")) or 0) > 0})
            if entries and row.get("objective_id") is not None:
                boarding.append((index, objective, row, entries))

        for offset, (index, objective, row, entries) in enumerate(boarding):
            end = boarding[offset+1][0] if offset+1 < len(boarding) else len(objectives)
            remaining = []
            for work_index in range(index+1, end):
                work = objectives[work_index]
                if not isinstance(work, dict) or work.get("is_complete") is True:
                    continue
                known = history(work_index, work)
                if any(not p.get("in_vehicle") for p in known):
                    continue  # a successful on-foot method disproves a required vehicle
                # The immediate combat stage follows the observed boarding.
                # Other stages require their own persisted vehicle progress;
                # e.g. a later on-foot boss must not reopen the boar ride.
                first_combat = work_index == index+1 and (
                    str(work.get("type") or "").upper() == "KILL"
                    or str(work.get("raw_type") or "").lower() == "monster")
                if any(p.get("in_vehicle") for p in known) or first_combat:
                    remaining.append(str(work.get("objective_id", f"{qid}:{work_index}")))
            if remaining:
                result.append({
                    "quest_id": qid, "boarding_objective_id": str(row["objective_id"]),
                    "boarding_index": index, "npc_ids": entries,
                    "name": row.get("credit_name") or objective.get("description"),
                    "remaining_objectives": remaining,
                    "source": "OBSERVED_VEHICLE_PROGRESS",
                })
    return result


def boarding_location(state: dict, requirement: dict, *,
                       travel_cost: TravelCostPort | None = None) -> dict | None:
    """Exact boarding objective POI/spawn, never a same-name vehicle or observer."""
    from .tdb_locations import _nearest, _poi_regions, _spawn_regions
    reference = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(
        requirement["quest_id"]) or {}
    oid, entries = requirement["boarding_objective_id"], set(requirement["npc_ids"])
    points = _poi_regions(state, reference, lambda p: (
        str(p.get("objective_id")) == oid and len(p.get("points") or ()) == 1))
    spawns = _spawn_regions(state, reference, lambda s: (
        str(s.get("entry")) in entries and s.get("entity_kind") in {"CREATURE", "VEHICLE"}
        and s.get("location_kind") != "OBSERVER_POSITION"
        and str(s.get("objective_id")) == oid))
    return _nearest(state, spawns or points, travel_cost=travel_cost)


def resume_proposals(state: dict, server_npcs, *, primary_quest_id=None,
                     travel_cost: TravelCostPort | None = None) -> list[Proposal] | None:
    """None means no missing prerequisite; a list exclusively restores it."""
    if (state.get("in_vehicle") is not False or state.get("on_taxi") is True
            or state.get("is_in_combat") or state.get("player_dead") or state.get("is_ghost")):
        return None
    requirements = state.get("vehicle_requirements") or ()
    if primary_quest_id:
        primary = [r for r in requirements if r["quest_id"] == str(primary_quest_id)]
        requirements = primary or requirements
    if not requirements:
        return None
    # A stable choice; the prerequisite cannot oscillate with nearby kill mobs.
    requirement = requirements[0]
    params = {"quest_id": requirement["quest_id"],
              "vehicle_prerequisite": requirement["boarding_objective_id"],
              "required_npc_ids": requirement["npc_ids"]}
    if state.get("world_map_open"):
        return [Proposal.make("CLOSE_MAP", "Visszaszállás előtt a térkép bezárása",
                              params, priority=115)]
    proposals = server_npcs.propose(state, vehicle_requirement=requirement)
    if proposals:
        return [Proposal.make(p.skill, "A questhez ismét jármű kell: " + p.reason,
                              {**p.parameters, **params}, p.confidence, p.priority, p.evidence)
                for p in proposals]
    # A known nearby actor must not be replaced with a static point while
    # the recipient settles or the previous press is still awaiting entry.
    candidates = server_npcs.candidates(state, vehicle_requirement=requirement)
    if not candidates:
        location = boarding_location(state, requirement, travel_cost=travel_cost)
        if location:
            from .destination_distance import arrived
            move = {**location, **params, "purpose": "RETURN_TO_QUEST_VEHICLE",
                    "stop_distance": 3., "require_navmesh": True}
            if not arrived(state, move):
                return [Proposal.make("MOVE", "A hiányzó quest-jármű felszállási helyére visszamegyek",
                                      move, confidence=.85, priority=110,
                                      evidence=("observed_vehicle_progress", "boarding_objective_location"))]
    return [Proposal.make("WAIT", "Visszaszállás: a megfelelő jármű / soft-interact / felszállás igazolására várok",
                          {**params, "purpose": "QUEST_VEHICLE_REQUIRED",
                           "waiting_for": ["BOARDING_ACTOR_OR_SOFT_INTERACT_OR_VEHICLE_ENTRY"]},
                          priority=110)]


def movement_interrupt(params: dict, state: dict) -> dict | None:
    """Release the existing navigation owner before the planner restores a ride."""
    if (state.get("in_vehicle") is not False or state.get("on_taxi") is True
            or state.get("is_in_combat") or state.get("is_dead") or state.get("is_ghost")):
        return None
    requirements = state.get("vehicle_requirements") or ()
    requirement = next((r for r in requirements if r["quest_id"] == str(params.get("quest_id"))), None)
    if requirement is None:
        return None
    result = {"kind": "QUEST_VEHICLE_PREREQUISITE", "quest_id": requirement["quest_id"]}
    if params.get("vehicle_prerequisite") != requirement["boarding_objective_id"]:
        return {**result, "reason": "quest_vehicle_missing"}
    from .server_npc_planning import ServerNpcInteractionPolicy
    policy = ServerNpcInteractionPolicy()
    if params.get("purpose") == "RETURN_TO_QUEST_VEHICLE":
        if policy.candidates(state, vehicle_requirement=requirement):
            return {**result, "reason": "quest_vehicle_actor_available"}
    elif params.get("purpose") == "APPROACH_SERVER_NPC":
        proposals = policy.propose(state, vehicle_requirement=requirement)
        if any(p.skill == "INTERACT" and p.parameters.get("soft_guid") == params.get("server_entity_guid")
               for p in proposals):
            return {**result, "reason": "quest_vehicle_interaction_ready"}
    return None
