"""Grounded, bounded inputs for Planner's look-ahead (no I/O or execution)."""
from __future__ import annotations

from copy import deepcopy
import math
from types import SimpleNamespace

from wowbot.query_ports import TravelCostPort
from .models import number
from .planning_types import world_point
from .tdb_locations import objective_region, role_region


def scoped_point(value, state):
    point = world_point(value)
    player = state.get("player_world_position") or {}
    if (point is None or str(point["instance_id"]) != str(player.get("instance_id"))
            or point.get("map_id") not in (None, state.get("map_id"))):
        return None
    keys = ("x", "y", "z", "z_known", "z_estimated", "instance_id", "map_id",
            "coordinate_space", "source", "reference_hint_id", "verified_build")
    return {key: point[key] for key in keys if key in point}


def height(point):
    if not point or point.get("z_known") is False:
        return None
    value = number(point.get("z"))
    return value if value is not None and math.isfinite(value) else None


def distance(a, b):
    if not a or not b or str(a.get("instance_id")) != str(b.get("instance_id")):
        return math.inf
    values = [number(point.get(key)) for point in (a, b) for key in ("x", "y")]
    if any(v is None or not math.isfinite(v) for v in values):
        return math.inf
    az, bz = height(a), height(b)
    dz = bz-az if az is not None and bz is not None else 0.
    return math.sqrt((values[0]-values[2])**2 + (values[1]-values[3])**2 + dz**2)


def same_area(a, b, radius=120.):
    az, bz = height(a), height(b)
    # A known lower cave level is not nearby work just because XY overlaps.
    return bool(a and b and (az is None or bz is None or abs(az-bz) <= 15.)
                and distance(a, b) <= radius)


def role_ids(reference, role):
    return sorted({str(row["npc_id"]) for row in reference.get("quest_roles") or ()
                   if isinstance(row, dict) and row.get("role") == role and row.get("npc_id")})


def completion_mode(record, state, only_quest=False):
    mode = str(record.raw.get("completion_mode") or "UNKNOWN").upper()
    ui = state.get("quest_ui") or {}
    qid = str(record.quest_id)
    if str(ui.get("quest_id") or state.get("quest_ui_quest_id") or "") == qid:
        if str(ui.get("action") or state.get("quest_ui_action") or "").upper() in {"COMPLETE", "TURN_IN", "REWARD_SELECT"}:
            return "FIELD_TURN_IN"
    if only_quest or str(state.get("primary_quest_id") or "") == qid:
        mode = str(state.get("quest_completion_mode") or mode).upper()
    return mode if mode in {"FIELD_TURN_IN", "AUTO_COMPLETE", "SPECIAL_UI", "NPC_TURN_IN"} else "UNKNOWN"


def objective_plan(objective):
    """Inspectible capability horizon, not a command sequence to auto-run."""
    kind = objective.type
    chains = {
        "KILL": ["IDENTIFY_TARGET", "TARGET", "APPROACH", "COMBAT", "LOOT_IF_NEEDED", "VERIFY_QUEST_CREDIT"],
        "TALK_TO": ["IDENTIFY_TARGET", "TARGET", "APPROACH", "INTERACT", "VERIFY_QUEST_CREDIT"],
        "INTERACT": ["IDENTIFY_TARGET", "APPROACH", "FRESH_HOVER", "OBJECT_USE_OR_INTERACT", "VERIFY_QUEST_CREDIT"],
        "USE_OBJECT": ["IDENTIFY_TARGET", "APPROACH", "FRESH_HOVER", "USE_QUEST_TOOL_OR_OBJECT", "VERIFY_QUEST_CREDIT"],
        "COLLECT": ["IDENTIFY_SOURCE", "GATHER_OR_COMBAT", "LOOT_IF_NEEDED", "VERIFY_QUEST_CREDIT"],
        "TRAVEL_TO": ["NAVIGATE", "VERIFY_ARRIVAL", "VERIFY_QUEST_CREDIT"],
        "DEFEND": ["REACH_DEFEND_AREA_IF_KNOWN", "DEFEND_OR_WAIT_EVENT", "VERIFY_QUEST_CREDIT"],
        "WAIT": ["WAIT_EVENT", "VERIFY_QUEST_CREDIT"],
    }
    return {"objective_id": objective.objective_id, "type": kind, "description": objective.description,
            "capabilities": chains.get(kind, ["GATHER_EVIDENCE", "RESOLVE_STRATEGY", "VERIFY_QUEST_CREDIT"]),
            "fallback": "KEEP_VERIFIED_PROGRESS_AND_REPLAN_ON_NEW_EVIDENCE",
            "execution": "REVALIDATE_EACH_CAPABILITY_WITH_EXISTING_SKILL_CONTRACTS"}


def quest_steps(world, goal, *, travel_cost: TravelCostPort | None = None):
    """One work/turn-in pair per real log quest; no simulated quest credit."""
    state = world.state
    readiness = world.quest_model.readiness()
    references = (state.get("reference_knowledge") or {}).get("quests") or {}
    explicit = (goal.parameters.get("primary_quest_id") or goal.parameters.get("quest_id")
                or state.get("primary_quest_id"))
    campaign = str(goal.parameters.get("mode") or goal.parameters.get("quest_mode") or "").upper() == "MAIN_CAMPAIGN"
    player = state.get("player_world_position") or {}
    steps = []
    records = [record for record in world.quest_model.records.values()
               if record.current_state in {"ACTIVE", "COMPLETED"}
               and (explicit is None or str(record.quest_id) == str(explicit))
               and (not campaign or record.raw.get("is_campaign") is True)]
    for record in sorted(records, key=lambda r: str(r.quest_id))[:30]:
        qid = str(record.quest_id)
        reference = references.get(qid) or {}
        complete = record.current_state == "COMPLETED" or record.raw.get("is_complete") is True
        ready = [o for o in record.objectives if readiness.get(o.objective_id, {}).get("status") == "READY"]
        points = [point for obj in ready[:4]
                  if (point := scoped_point(objective_region(
                      state, qid, obj, travel_cost=travel_cost), state)) is not None]
        live = next((loc for loc in state.get("quest_locations") or ()
                     if isinstance(loc, dict) and str(loc.get("quest_id")) == qid and scoped_point(loc, state)), None)
        if not points and not complete and live is not None:
            points.append(scoped_point(live, state))
        work = min(points, key=lambda point: distance(player, point)) if points else None
        ender = scoped_point(role_region(state, qid, "QUEST_ENDER",
            live_location=live if complete else None, travel_cost=travel_cost), state)
        if ender is None and complete and live is not None:
            ender = scoped_point(live, state)
        mode = completion_mode(record, state, only_quest=sum(
            r.current_state in {"ACTIVE", "COMPLETED"} for r in world.quest_model.records.values()) == 1)
        if mode in {"FIELD_TURN_IN", "AUTO_COMPLETE", "SPECIAL_UI"}:
            ender = None  # UI/credit verification, not a return to a remembered giver
        common = {"quest_id": qid, "title": record.title, "source": "LIVE_QUEST_STATE",
                  "verified_build": reference.get("verified_build")}
        steps.extend([
            {**common, "key": f"work:{qid}", "kind": "WORK", "location": work,
             "objective_ids": [o.objective_id for o in ready],
             "objective_plans": [objective_plan(o) for o in ready[:4]],
             "status": "VERIFIED" if complete else "READY" if ready else "NEEDS_EVIDENCE",
             "depends_on": [], "requires": ["quest_active", "objective_still_open", "live_target_verification"]},
            {**common, "key": f"turnin:{qid}", "kind": "TURN_IN", "location": ender,
             "npc_ids": role_ids(reference, "QUEST_ENDER"),
             "completion_mode": mode,
             "status": "READY" if complete else "BLOCKED", "depends_on": [f"work:{qid}"],
             "requires": ["live_quest_complete", "completion_mode_resolved", "live_identity_and_interaction"]},
        ])
        next_ids = [str(value) for key, value in (reference.get("chain") or {}).items()
                    if key in {"NextQuestID", "RewardNextQuest"} and number(value) is not None and number(value) > 0]
        steps.append({**common, "key": f"discover:{qid}", "kind": "CHECK_NEXT_QUESTS",
                      "location": ender, "npc_ids": role_ids(reference, "QUEST_ENDER"),
                      "candidate_quest_ids": sorted(set(next_ids)), "status": "BLOCKED",
                      "depends_on": [f"turnin:{qid}"],
                      "requires": ["turnin_verified", "fresh_gossip_or_map_api_availability"]})
    return steps


def offer_steps(state, goal, *, travel_cost: TravelCostPort | None = None):
    """UI/map API availability is evidence; TDB alone cannot authorize accept."""
    campaign = str(goal.parameters.get("mode") or goal.parameters.get("quest_mode") or "").upper() == "MAIN_CAMPAIGN"
    explicit = goal.parameters.get("primary_quest_id") or goal.parameters.get("quest_id") or state.get("primary_quest_id")
    active = {str(q.get("quest_id")) for q in state.get("active_quests") or ()}
    ui = state.get("quest_ui") or {}
    offered = [dict(row, agenda_source="LIVE_GOSSIP_OFFER") for row in ui.get("entries") or ()
               if isinstance(row, dict) and (ui.get("open") or state.get("quest_ui_open"))
               and str(row.get("kind")).upper() == "AVAILABLE"]
    offered.extend(dict(row, agenda_source="LIVE_MAP_API")
                   for row in (state.get("map_pois") or {}).get("available_quests") or () if isinstance(row, dict))
    if (ui.get("open") or state.get("quest_ui_open")) and str(ui.get("action") or "").upper() == "ACCEPT":
        offered.append({**ui, "agenda_source": "LIVE_QUEST_OFFER"})
    result, seen = [], set()
    for row in offered[:30]:
        qid = str(row.get("quest_id") or "")
        if (not qid or qid in active or qid in seen or explicit is not None and qid != str(explicit)
                or campaign and row.get("is_campaign") is not True):
            continue
        seen.add(qid)
        point = scoped_point(role_region(state, qid, "QUEST_STARTER", live_location=row,
                                        travel_cost=travel_cost), state) or scoped_point(row, state)
        reference = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(qid) or {}
        future_points = [p for objective in (reference.get("objectives") or ())[:4]
                         if (p := scoped_point(objective_region(state, qid,
                             SimpleNamespace(objective_id=str(objective.get("objective_id"))),
                             travel_cost=travel_cost), state))]
        future = min(future_points, key=lambda p: distance(state.get("player_world_position") or {}, p)) if future_points else None
        ender = scoped_point(role_region(state, qid, "QUEST_ENDER", travel_cost=travel_cost), state)
        next_ids = [str(value) for key, value in (reference.get("chain") or {}).items()
                    if key in {"NextQuestID", "RewardNextQuest"}
                    and number(value) is not None and number(value) > 0]
        result.extend([
            {"key": f"accept:{qid}", "kind": "ACCEPT", "quest_id": qid,
             "title": row.get("title") or row.get("quest_name"),
             "location": point, "status": "READY", "source": row["agenda_source"],
             "depends_on": [], "npc_ids": role_ids(reference, "QUEST_STARTER"),
             "requires": ["fresh_offer_still_available", "accept_policy_allows", "accepted_state_confirmation"]},
            {"key": f"future-read:{qid}", "kind": "READ_ACCEPTED_QUEST", "quest_id": qid,
             "location": point, "status": "BLOCKED", "depends_on": [f"accept:{qid}"],
             "requires": ["accepted_quest_in_live_log", "read_actual_objectives"], "source": row["agenda_source"]},
            {"key": f"future-work:{qid}", "kind": "WORK_AFTER_ACCEPT", "quest_id": qid,
             "location": future, "status": "BLOCKED", "depends_on": [f"future-read:{qid}"],
             "requires": ["accepted_quest_in_live_log", "read_actual_objectives"], "source": row["agenda_source"]},
            {"key": f"future-turnin:{qid}", "kind": "TURN_IN_AFTER_WORK", "quest_id": qid,
             "location": ender, "npc_ids": role_ids(reference, "QUEST_ENDER"),
             "status": "BLOCKED", "depends_on": [f"future-work:{qid}"],
             "requires": ["live_quest_complete", "completion_mode_resolved", "live_identity_and_interaction"],
             "source": row["agenda_source"]},
            {"key": f"discover:{qid}", "kind": "CHECK_NEXT_QUESTS", "quest_id": qid,
             "location": None, "candidate_quest_ids": sorted(set(next_ids)), "status": "BLOCKED",
             "depends_on": [f"future-turnin:{qid}"],
             "requires": ["turnin_verified", "fresh_gossip_or_map_api_availability"],
             "source": row["agenda_source"]},
        ])
    return result


def discovery_steps(world, goal, existing, previous, now):
    """Keep an information-gathering goal when the last live quest ends.

    A disappeared quest is not a turn-in. Only the canonical QuestModel's
    explicit TURNED_IN state can satisfy that dependency; an empty known log
    can independently justify asking for available quests, never accepting a
    static chain candidate. No old screen point or identity is executable.
    """
    state = world.state
    explicit = goal.parameters.get("primary_quest_id") or goal.parameters.get("quest_id") or state.get("primary_quest_id")
    if (explicit is not None or not isinstance(state.get("active_quests"), (list, tuple))
            or state["active_quests"] or any(step["kind"] in {"WORK", "TURN_IN", "ACCEPT"}
                                           for step in existing)):
        return []
    verified = [record for record in world.quest_model.records.values()
                if record.current_state == "TURNED_IN"
                and number(record.last_updated_at) is not None
                and 0 <= now-record.last_updated_at <= 120.]
    recent = max(verified, key=lambda record: record.last_updated_at) if verified else None
    qid = str(recent.quest_id) if recent else None
    prior = {step["key"]: step for step in previous}
    result = []
    if recent is not None:
        terminal = deepcopy(prior.get(f"turnin:{qid}") or {})
        terminal.update(key=f"turnin:{qid}", kind="TURN_IN", quest_id=qid,
                        title=recent.title, status="VERIFIED", source="VERIFIED_QUEST_TURNED_IN",
                        depends_on=[], requires=["verified_quest_turned_in_event"])
        terminal.setdefault("location", None)
        result.append(terminal)
    next_step = deepcopy(prior.get(f"discover:{qid}") or {}) if qid else {}
    next_step.update(key=f"discover:{qid}" if qid else "discover:available",
                     kind="CHECK_NEXT_QUESTS", quest_id=qid, status="READY", location=None,
                     source="VERIFIED_QUEST_TURNED_IN" if recent else "LIVE_QUEST_LOG_EMPTY",
                     depends_on=[f"turnin:{qid}"] if recent else [],
                     requires=["fresh_gossip_or_map_api_availability"])
    # The former ender's identity/position is not a new quest-giver fact.
    next_step.pop("npc_ids", None)
    result.append(next_step)
    return result


def follow_up_steps(state, existing, *, travel_cost: TravelCostPort | None = None):
    """Static chain read-ahead remains BLOCKED until the client offers it."""
    from .reference_knowledge import positive_id
    known = {step["quest_id"] for step in existing}
    result = []
    references = (state.get("reference_knowledge") or {}).get("quests") or {}
    for parent in [step for step in existing if step["kind"] == "CHECK_NEXT_QUESTS"]:
        reference = references.get(parent["quest_id"]) or {}
        for candidate in reference.get("follow_up_candidates") or ():
            qid = positive_id(candidate.get("quest_id"))
            if qid is None or str(qid) in known:
                continue
            qid = str(qid)
            # Reuse the existing role resolver's build/phase/map checks over
            # a read-only reference view; never insert it into live quests.
            scoped = {**state, "reference_knowledge": {"quests": {qid: candidate}}}
            point = scoped_point(role_region(scoped, qid, "QUEST_STARTER",
                                            travel_cost=travel_cost), state)
            result.append({"key": f"followup:{parent['quest_id']}:{qid}", "kind": "CHECK_FOLLOW_UP",
                "quest_id": qid, "title": candidate.get("title"), "location": point,
                "npc_ids": role_ids(candidate, "QUEST_STARTER"), "status": "BLOCKED",
                "depends_on": [parent["key"]], "requires": ["turnin_verified", "fresh_live_offer"],
                "source": "TDB_CHAIN_CANDIDATE", "verified_build": candidate.get("verified_build")})
            if len(result) >= 8:
                return result
    return result
