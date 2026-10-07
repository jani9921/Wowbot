"""Quest turn-in, multi-offer and batching regressions (user 2026-10-03).

Live 2026-10-02 (run 21:21-21:55):
* 21:27 the turn-in MOVE to the API point (-423, -2611) arrived ~20 yd from
  Jaina, was proposed again, was blocked for lack of progress (WAIT) and came
  back -- MOVE/WAIT for minutes without ever looking for the "?" NPC.
* 21:33 the turned-in quest 55122 stayed the runtime's primary quest until the
  end and filtered out later quests' objectives, turn-ins and offers.
* 21:45 an NPC offered quests 55186 and 55184; the agent waited 38 s.
User: take every offered quest one after the other, and finish quests in the
same area before walking back to turn them in together.
"""
from types import SimpleNamespace

from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.navigation_planning import NavigationProposalAdapter
from wowbot.agent.quest_batch_planning import QuestBatchPolicy
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.agent.quest_model import QuestModel
from wowbot.agent.quest_runtime import QuestExecutionRuntime
from wowbot.agent.world import WorldModel

TURN_IN = {"x": -423., "y": -2611., "instance_id": 2175, "ui_map_id": 1409,
           "coordinate_space": "WORLD_YARDS", "source": "C_MAP_WORLD_POS"}


def _location(quest_id, world_position, x=.61, y=.82):
    return {"quest_id": quest_id, "map_id": 1409, "x": x, "y": y, "source": "QUEST_POI",
            "coordinate_space": "NORMALIZED_MAP", "world_position": dict(world_position)}


def _world(player, quests, locations, at=1.):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "batch", "frame_id": f"f:{at}", "timestamp": at, "monotonic_time": at,
        "map_id": 1409, "orientation": 0., "position": {"x": .61, "y": .82},
        "player_world_position": {"x": player[0], "y": player[1], "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS"},
        "active_quests": quests, "quest_locations": locations,
        "world_map_open": False, "player_present": True,
    }, at))
    return world


def test_arrived_turn_in_point_searches_for_the_npc_instead_of_moving_again():
    policy = QuestLocationPlanningPolicy()
    quests = [{"quest_id": 55122, "is_complete": True, "objectives": []}]
    far = _world((-480., -2611.), quests, [_location(55122, TURN_IN)])
    move = policy.propose_known_locations(far)[0]
    assert move.skill == "MOVE" and move.parameters["purpose"] == "LOCATE_TURN_IN_REGION"

    # The MOVE stops 6 yd short; the agent stands there (live 21:27:33).
    policy.mark_reached({**move.parameters, "x": -423., "y": -2611.}, far.state)
    there = _world((-417.5, -2611.8), quests, [_location(55122, TURN_IN)])
    search = policy.propose_known_locations(there)
    assert [p.skill for p in search] == ["SEEK_VISUAL_CUE"]
    assert search[0].parameters["purpose"] == "SEARCH_TURN_IN_AREA"
    assert search[0].parameters["search_area"]["x"] == -423.
    # Walking around the point (~20 yd away, toward Jaina) keeps searching.
    assert policy.propose_known_locations(
        _world((-440., -2611.), quests, [_location(55122, TURN_IN)]))[0].skill == "SEEK_VISUAL_CUE"
    # Pulled far away (e.g. by a fight): travel back to the point.
    assert policy.propose_known_locations(
        _world((-480., -2611.), quests, [_location(55122, TURN_IN)]))[0].skill == "MOVE"


def test_turn_in_search_alternates_camera_sweeps_and_area_cells():
    navigation = SimpleNamespace()
    regions = {}
    navigation.begin_search_region = lambda region_id, area: regions.setdefault(
        region_id, {"cells": [("c0", -423., -2611.), ("c1", -435., -2611.)], "visited": set()})
    navigation.observe_search_region = lambda *a, **k: None
    navigation.mark_search_cell_visited = lambda region_id, cell_id, now: regions[region_id]["visited"].add(cell_id)

    def next_waypoint(region_id, state):
        region = regions[region_id]
        for cell_id, x, y in region["cells"]:
            if cell_id not in region["visited"]:
                return {"x": x, "y": y, "search_cell_id": cell_id}
        return None
    navigation.next_search_waypoint = next_waypoint
    adapter = NavigationProposalAdapter(navigation)
    seek = QuestLocationPlanningPolicy().turn_in_search(55122, TURN_IN)

    def adapt(player, now, last=None):
        world = SimpleNamespace(state={"player_world_position": {
            "x": player[0], "y": player[1], "instance_id": 2175}})
        return adapter._search_waypoint(seek, world, now, last_result=last)

    assert adapt((-417.5, -2611.8), 1.).skill == "SEEK_VISUAL_CUE"         # look around first
    done = {"skill": "SEEK_VISUAL_CUE", "purpose": "SEARCH_TURN_IN_AREA", "action_id": "a1"}
    walk = adapt((-417.5, -2611.8), 9., done)
    assert walk.skill == "MOVE" and walk.parameters["purpose"] == "SEARCH_TURN_IN_AREA"
    assert walk.parameters["require_navmesh"] is True
    assert adapt((-418.5, -2611.8), 10., done).parameters["search_cell_id"] == walk.parameters["search_cell_id"]
    # Arrived at the cell: sweep again there, then walk on to the next cell.
    cell = (walk.parameters["x"], walk.parameters["y"])
    assert adapt(cell, 14., done).skill == "SEEK_VISUAL_CUE"
    second = adapt(cell, 20., {**done, "action_id": "a2"})
    assert second.skill == "MOVE" and second.parameters["search_cell_id"] != walk.parameters["search_cell_id"]


def test_turned_in_primary_quest_is_released_and_quests_are_batched():
    goal = SimpleNamespace(domain="QUEST", parameters={})
    runtime = QuestExecutionRuntime()
    one = QuestModel()
    one.ingest([{"quest_id": 55122, "objectives": []}], "o1", 1.)
    assert runtime.observe(goal, one, {}, 1.).quest_id == "55122"
    # 55122 turned in, two new quests accepted: nothing is pinned any more,
    # so every quest's objectives and turn-ins are planned.
    two = QuestModel()
    two.ingest([{"quest_id": 55186, "objectives": []}, {"quest_id": 55184, "objectives": []}], "o2", 2.)
    state = runtime.observe(goal, two, {}, 2.)
    assert state.quest_id is None and state.status == "NEEDS_SELECTION"
    # Only 55184 left (55186 turned in), already complete: it is the primary.
    last = QuestModel()
    last.ingest([{"quest_id": 55184, "is_complete": True, "objectives": []}], "o3", 3.)
    state = runtime.observe(goal, last, {}, 3.)
    assert state.quest_id == "55184" and state.status == "COMPLETED"


def test_turn_in_waits_while_another_quest_is_worked_on_nearby():
    batch = QuestBatchPolicy()
    quests = [{"quest_id": 1, "is_complete": True}, {"quest_id": 2, "is_complete": False}]
    turn_in = {**TURN_IN, "x": -423., "y": -2611.}
    near_work = {**TURN_IN, "x": 102., "y": -2408.}
    state = {"active_quests": quests,
             "player_world_position": {"x": 80., "y": -2400., "instance_id": 2175},
             "quest_locations": [_location(1, turn_in), _location(2, near_work)]}
    assert batch.deferred_turnins(state, 10.) == {"1"}
    # Standing at the turn-in already: hand it in now.
    at_npc = {**state, "player_world_position": {"x": -420., "y": -2611., "instance_id": 2175}}
    assert batch.deferred_turnins(at_npc, 11.) == frozenset()
    # The other quest's area is far away: go and turn in first.
    far_work = {**state, "quest_locations": [_location(1, turn_in),
                                             _location(2, {**TURN_IN, "x": 900., "y": 900.})]}
    assert batch.deferred_turnins(far_work, 12.) == frozenset()
    # Never wait for ever.
    assert batch.deferred_turnins(state, 10. + QuestBatchPolicy.MAX_DEFER_SECONDS + 1) == frozenset()


def test_deferred_turn_in_is_not_proposed():
    quests = [{"quest_id": 1, "is_complete": True, "objectives": []},
              {"quest_id": 2, "is_complete": False, "objectives": []}]
    world = _world((80., -2400.), quests, [_location(1, TURN_IN),
                                            _location(2, {**TURN_IN, "x": 102., "y": -2408.})])
    proposals = QuestLocationPlanningPolicy().propose_known_locations(world, deferred=frozenset({"1"}))
    assert [p.parameters["quest_id"] for p in proposals] == [2]
    assert proposals[0].parameters["purpose"] == "LOCATE_QUEST_OBJECTIVE_REGION"


def _gossip_state(**extra):
    return {"monotonic_time": 100., "target": {"guid": "Creature-0-1-2-3-154170-1", "attackable": False},
            "quest_ui": {"open": True, "entries": [
                {"kind": "AVAILABLE", "quest_id": 55186, "x": .093, "y": .40, "acceptable": True},
                {"kind": "AVAILABLE", "quest_id": 55184, "x": .093, "y": .45, "acceptable": True}]},
            "active_quests": [], **extra}


def test_every_offered_quest_is_taken_even_with_another_primary_quest():
    policy = QuestDialogPlanningPolicy()
    goal = Goal.parse("Questelj", 1.)
    proposals = policy.propose(_gossip_state(), goal, primary_quest_id="55173")
    rows = [p for p in proposals if p.skill == "QUEST_DIALOG"]
    assert [p.parameters["quest_id"] for p in rows] == [55186]
    assert not any(p.skill == "WAIT" for p in proposals)
    # The first one accepted: the second row is chosen next.
    after = _gossip_state(active_quests=[{"quest_id": 55186}])
    after["quest_ui"]["entries"] = after["quest_ui"]["entries"][1:]
    rows = [p for p in policy.propose(after, goal) if p.skill == "QUEST_DIALOG"]
    assert [p.parameters["quest_id"] for p in rows] == [55184]


def test_closed_dialog_with_offers_left_speaks_to_the_same_npc_again():
    policy = QuestDialogPlanningPolicy()
    goal = Goal.parse("Questelj", 1.)
    policy.propose(_gossip_state(), goal)
    closed = {"monotonic_time": 104., "target": {"guid": "Creature-0-1-2-3-154170-1", "attackable": False},
              "quest_ui": {"open": False}, "active_quests": [{"quest_id": 55186}]}
    again = [p for p in policy.propose(closed, goal) if p.skill == "INTERACT"]
    assert again and again[0].parameters["guid"] == "Creature-0-1-2-3-154170-1"
    assert again[0].parameters["pending_quest_ids"] == ["55184"]
    # All taken, or too late: nothing more.
    done = {**closed, "active_quests": [{"quest_id": 55186}, {"quest_id": 55184}]}
    assert not [p for p in policy.propose(done, goal) if p.skill == "INTERACT"]
    policy.propose(_gossip_state(), goal)
    late = {**closed, "monotonic_time": 100. + QuestDialogPlanningPolicy.PENDING_OFFER_SECONDS + 1}
    assert not [p for p in policy.propose(late, goal) if p.skill == "INTERACT"]


def test_an_explicit_quest_goal_still_filters_offers():
    policy = QuestDialogPlanningPolicy()
    goal = SimpleNamespace(domain="QUEST", parameters={"quest_id": 55184})
    rows = [p for p in policy.propose(_gossip_state(), goal) if p.skill == "QUEST_DIALOG"]
    assert [p.parameters["quest_id"] for p in rows] == [55184]


def test_active_quest_area_is_roamed_when_nothing_else_is_actionable():
    """Live 2026-10-03 (Cooking Meat, collect Raw Meat from wildlife): at the
    quest area, sweeps exhausted, the agent waited 2 minutes."""
    from wowbot.agent.visual_search_planning import VisualSearchPlanningPolicy
    meat = {**TURN_IN, "x": -196., "y": -2507.}
    state = {"active_quests": [{"quest_id": 55174, "is_complete": False, "objectives": [
                 {"type": "COLLECT", "is_complete": False}]}],
             "player_world_position": {"x": -180., "y": -2500., "instance_id": 2175},
             "quest_locations": [_location(55174, meat)]}
    area = VisualSearchPlanningPolicy.active_quest_area(state)
    assert area["quest_id"] == 55174 and area["objective_type"] == "COLLECT"
    assert area["search_area"]["x"] == -196. and area["search_area"]["radius"] == 30.
    far = {**state, "player_world_position": {"x": 400., "y": -2500., "instance_id": 2175}}
    assert VisualSearchPlanningPolicy.active_quest_area(far) is None

    navigation = SimpleNamespace(begun=[])
    navigation.begin_search_region = lambda region_id, area: navigation.begun.append(region_id)
    navigation.observe_search_region = lambda *a, **k: None
    navigation.next_search_waypoint = lambda region_id, state: (
        None if region_id.endswith(":0") else {"x": -190., "y": -2500., "search_cell_id": "c"})
    adapter = NavigationProposalAdapter(navigation)
    seek = Proposal.make("SEEK_VISUAL_CUE", "roam", {
        "purpose": "SEARCH_LOCAL_OBJECTIVE_AREA", "roam_quest_area": True, **area})
    world = SimpleNamespace(state={**state, "target": {}, "mouseover": {}})
    assert adapter._search_waypoint(seek, world, 1.).skill == "SEEK_VISUAL_CUE"   # gen 0 done
    again = adapter._search_waypoint(seek, world, 2.)                             # gen 1 restarts
    assert again.skill == "MOVE" and navigation.begun[-1].endswith(":1")


def test_objective_area_move_is_not_repeated_inside_the_area():
    """Live 2026-10-03: inside the Cooking Meat area each kill changed the quest
    signature and the objective MOVE came back and was blocked (WAIT)."""
    meat = {**TURN_IN, "x": -196., "y": -2507.}
    quests = [{"quest_id": 55174, "is_complete": False, "objectives": []}]
    inside = _world((-185., -2500.), quests, [_location(55174, meat)])
    assert QuestLocationPlanningPolicy().propose_known_locations(inside) == []
    outside = _world((-260., -2500.), quests, [_location(55174, meat)])
    assert QuestLocationPlanningPolicy().propose_known_locations(outside)[0].skill == "MOVE"


def test_objective_on_another_floor_does_not_defer_the_turn_in():
    """Issue #90: an objective tens of yards below (known Z) was 2D-"nearby"
    work and postponed a completed hand-in for up to 600 s."""
    def state(objective_z, z_known=True):
        return {
            "player_world_position": {"x": 0., "y": 0., "z": 100., "instance_id": 1,
                                      "coordinate_space": "WORLD_YARDS"},
            "active_quests": [{"quest_id": 1, "is_complete": True},
                              {"quest_id": 2, "is_complete": False}],
            "quest_locations": [
                _location(2, {"x": 10., "y": 0., "z": objective_z, "z_known": z_known,
                              "instance_id": 1, "coordinate_space": "WORLD_YARDS"}),
                _location(1, {"x": 500., "y": 500., "z": 100., "instance_id": 1,
                              "coordinate_space": "WORLD_YARDS"})]}
    assert QuestBatchPolicy().deferred_turnins(state(0.), 1.) == frozenset()
    # Same floor (or unknown objective Z) keeps the user's batching rule.
    assert QuestBatchPolicy().deferred_turnins(state(95.), 1.) == {"1"}
    assert QuestBatchPolicy().deferred_turnins(state(0., z_known=False), 1.) == {"1"}
