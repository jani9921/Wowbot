from types import SimpleNamespace

from wowbot.agent.models import Goal, Observation
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.agent.planner import Planner
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel


def _objective(**overrides):
    values = {
        "type": "USE_OBJECT", "objective_id": "10:0", "description": "Open the Ancient Chest",
        "target_object": {"object_id": 77}, "target_entity": None,
        "target_location": {"map_id": 1409, "x": .4, "y": .6},
        "location_candidates": (), "confidence": .85,
        "optional": False, "raw": {"description": "Open the Ancient Chest"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _world(mouseover=None):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "object-flow", "timestamp": 1., "monotonic_time": 1.,
        "frame_id": "one", "map_id": 1409, "position": {"x": .4, "y": .6},
        "mouseover": mouseover or {}, "active_quests": [{"quest_id": 10,
            "objectives": [{"objective_id": "10:0", "type": "USE_OBJECT",
                            "object_id": 77,
                            "target_location": {"map_id": 1409, "x": .4, "y": .6},
                            "current": 0, "required": 1}]}],
    }, 1.))
    return world


def test_explicit_object_id_cannot_be_replaced_by_matching_tooltip_text():
    identity = {"object_id": 77, "item_id": None,
                "expected_tooltips": ["ancient chest"]}
    assert ObjectInteractionFlow.mouseover_matches(identity, {"object_id": 77})
    assert not ObjectInteractionFlow.mouseover_matches(
        identity, {"object_id": 88, "tooltip": "Ancient Chest"})


def test_reached_object_area_search_carries_expected_identity_to_active_perception():
    world, policy, objective = _world(), QuestLocationPlanningPolicy(), _objective()
    record = SimpleNamespace(quest_id=10, known_locations=[])
    policy.mark_reached({"quest_id": 10, "map_id": 1409, "x": .4, "y": .6}, world.state)

    proposals = policy.propose_objective(world, objective, record, "10")

    assert len(proposals) == 1 and proposals[0].skill == "SEEK_VISUAL_CUE"
    assert proposals[0].parameters["search_capability"] == "SEARCH_LOCAL_OBJECT"
    assert proposals[0].parameters["object_id"] == 77
    assert proposals[0].parameters["objective_id"] == "10:0"


def test_confirmed_object_mouseover_hands_off_without_repeating_move_or_search():
    world, policy, objective = _world({"object_id": 77, "tooltip": "Ancient Chest"}), QuestLocationPlanningPolicy(), _objective()
    record = SimpleNamespace(quest_id=10, known_locations=[])

    assert policy.propose_objective(world, objective, record, "10") == []


def test_planner_completes_arrival_search_identity_and_object_use_handoff():
    world, planner = _world(), Planner(SkillRegistry())
    location = {"quest_id": 10, "map_id": 1409, "x": .4, "y": .6}
    planner.quest.mark_location_reached(location, world.state)

    search = planner.candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert search[0].skill == "SEEK_VISUAL_CUE"
    assert search[0].parameters["object_id"] == 77

    world.ingest(Observation.create({
        "session_id": "object-flow", "timestamp": 1.1, "monotonic_time": 1.1,
        "frame_id": "two", "map_id": 1409, "position": {"x": .4, "y": .6},
        "mouseover": {"object_id": 77, "tooltip": "Ancient Chest"},
        "cursor_position": {"nx": .45, "ny": .55},
        "active_quests": [{"quest_id": 10, "objectives": [{
            "objective_id": "10:0", "type": "USE_OBJECT", "object_id": 77,
            "target_location": {"map_id": 1409, "x": .4, "y": .6},
            "current": 0, "required": 1}]}],
    }, 1.1))
    use = planner.candidates(Goal.parse("Questelj", 1.), world, 1.1)
    assert use[0].skill == "OBJECT_USE"
    assert use[0].parameters["object_id"] == 77
