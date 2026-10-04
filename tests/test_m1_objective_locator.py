from types import SimpleNamespace

from wowbot.agent.objective_locator import ObjectiveLocator
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.runtime import ObjectiveLocationStatus


def objective(**values):
    base = {"target_entity": None, "target_location": None, "location_candidates": (),
            "confidence": .8, "raw": {}}
    base.update(values)
    return SimpleNamespace(**base)


def test_locator_prioritizes_matching_local_entity_over_map_location():
    result = ObjectiveLocator().locate(
        objective(target_entity={"npc_id": 5}, target_location={"map_id": 1, "x": .2, "y": .3}),
        SimpleNamespace(known_locations=[]), {"map_id": 1, "target": {"npc_id": 5}})
    assert result.status is ObjectiveLocationStatus.LOCAL_ENTITY


def test_locator_distinguishes_local_marker_world_map_and_memory():
    locator = ObjectiveLocator()
    local = locator.locate(objective(target_location={"map_id": 1, "x": .2, "y": .3}),
                           SimpleNamespace(known_locations=[]), {"map_id": 1})
    assert local.status is ObjectiveLocationStatus.LOCAL_MARKER
    world = locator.locate(objective(target_location={"map_id": 2, "x": .2, "y": .3}),
                           SimpleNamespace(known_locations=[]), {"map_id": 1})
    assert world.status is ObjectiveLocationStatus.WORLD_MAP_LOCATION
    memory = locator.locate(objective(location_candidates=({"map_id": 2, "x": .2, "y": .3,
                                                            "confidence": .7, "source": "MEMORY"},)),
                            SimpleNamespace(known_locations=[]), {"map_id": 1})
    assert memory.status is ObjectiveLocationStatus.KNOWN_LOCATION


def test_search_area_becomes_bounded_local_search_after_arrival_not_map_fallback():
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f", "map_id": 1,
        "position": {"x": .5, "y": .5}, "orientation": 0., "world_map_open": False,
        "active_quests": [{"quest_id": 7, "objectives": [{
            "objective_id": "7:0", "description": "Find the missing supplies",
            "search_area": {"map_id": 1, "x": .5, "y": .5},
        }]}],
    }, 1.))
    world.set_runtime_context(primary_quest={"quest_id": "7", "objective_id": "7:0"})

    proposal = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)[0]
    assert proposal.skill == "SEEK_VISUAL_CUE"
    assert proposal.parameters["purpose"] == "SEARCH_LOCAL_OBJECTIVE_AREA"
    assert proposal.parameters["scan_budget"] == 4


def test_completed_quest_waypoint_needs_confirmed_npc_turn_in_mode():
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f", "map_id": 1,
        "position": {"x": .1, "y": .1}, "orientation": 0., "world_map_open": False,
        "active_quests": [{"quest_id": 7, "is_complete": True,
                           "waypoint": {"map_id": 1, "x": .8, "y": .8}, "objectives": []}],
    }, 1.))
    planner = Planner(SkillRegistry())
    goal = Goal.parse("Questelj", 1.)
    # A remembered/generic waypoint is not the live Quest API completion
    # waypoint and must not invent an NPC turn-in route.
    world.quest_model.records[7].known_locations[0]["source"] = "MEMORY"
    world.set_runtime_context(primary_quest={"quest_id": "7", "completion_mode": "UNKNOWN"})
    assert not any(item.skill == "MOVE" and item.parameters.get("quest_id") == 7
                   for item in planner.candidates(goal, world, 1.))

    world.set_runtime_context(primary_quest={"quest_id": "7", "completion_mode": "NPC_TURN_IN"})
    # Confirmation of the turn-in mode does not make normalized UI-map
    # coordinates safe for locomotion.  A world-space point is still required.
    assert not any(item.skill == "MOVE" and item.parameters.get("quest_id") == 7
                   for item in planner.candidates(goal, world, 2.))

    location = world.quest_model.records[7].known_locations[0]
    location["world_position"] = {
        "x": 100.0, "y": 200.0, "instance_id": 2175,
        "ui_map_id": 1, "coordinate_space": "WORLD_YARDS",
        "source": "C_MAP_WORLD_POS", "z_known": False,
    }
    world.state["player_world_position"] = {
        "x": 90.0, "y": 190.0, "z": 12.0, "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS", "z_known": True,
    }
    moves = [item for item in planner.candidates(goal, world, 3.)
             if item.skill == "MOVE" and item.parameters.get("quest_id") == 7]
    assert moves
    assert moves[0].parameters["require_navmesh"] is True
    assert moves[0].parameters["coordinate_space"] == "WORLD_YARDS"


def test_primary_objective_context_excludes_competing_ready_objective_proposals():
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f", "map_id": 1,
        "position": {"x": .1, "y": .1}, "orientation": 0., "world_map_open": False,
        "active_quests": [{"quest_id": 7, "objectives": [
            {"objective_id": "7:one", "type": "TRAVEL_TO", "target_location": {"map_id": 1, "x": .2, "y": .2}},
            {"objective_id": "7:two", "type": "TRAVEL_TO", "target_location": {"map_id": 1, "x": .8, "y": .8}},
        ]}],
    }, 1.))
    world.set_runtime_context(primary_quest={"quest_id": "7", "objective_id": "7:two"})

    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    moves = [item for item in proposals if item.skill == "MOVE"]
    # Normalized UI-map coordinates alone are location evidence, not a safe
    # physical route endpoint.
    assert not moves


def test_active_quest_objective_world_point_requires_mmap_route():
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f", "map_id": 1409,
        "position": {"x": .1, "y": .1}, "orientation": 0., "world_map_open": False,
        "player_world_position": {
            "x": -400., "y": -2500., "instance_id": 2175,
            "coordinate_space": "WORLD_YARDS"},
        "visual_candidates": [{
            "source": "WORLD3D", "semantic_type": "UNKNOWN",
            "kind": "unknown_subject_candidate", "track_id": "background-unknown",
            "x": .4, "y": .4, "bbox_height_fraction": .08,
            "stable_frames": 10, "confidence": .8, "inspectable": True,
            "lifecycle": "STABLE", "appearance": {"proposal_score": .8},
        }],
        "active_quests": [{"quest_id": 7, "objectives": [{
            "objective_id": "7:one", "type": "TRAVEL_TO", "map_id": 1409,
            "x": .2, "y": .2, "coordinate_space": "NORMALIZED_MAP",
            "world_position": {"x": -450., "y": -2600., "instance_id": 2175,
                               "ui_map_id": 1409,
                               "coordinate_space": "WORLD_YARDS",
                               "source": "C_MAP_WORLD_POS", "z_known": False},
        }]}],
    }, 1.))
    world.set_runtime_context(primary_quest={"quest_id": "7", "objective_id": "7:one"})

    moves = [item for item in Planner(SkillRegistry()).candidates(
        Goal.parse("Questelj", 1.), world, 1.) if item.skill == "MOVE"]

    assert moves
    assert moves[0].parameters["coordinate_space"] == "WORLD_YARDS"
    assert moves[0].parameters["instance_id"] == 2175
    assert moves[0].parameters["require_navmesh"] is True
    assert moves[0].parameters["purpose"] == "LOCATE_QUEST_OBJECTIVE_REGION"
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert not any(item.skill in {"INSPECT", "SEEK_VISUAL_CUE", "OPEN_MAP"}
                   for item in proposals)
