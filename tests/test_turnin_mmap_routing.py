from wowbot.agent.models import Observation
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from types import SimpleNamespace


def _world(location):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "turnin", "frame_id": "turnin", "timestamp": 1.,
        "monotonic_time": 1., "map_id": 1409, "orientation": 0.,
        "position": {"x": .53, "y": .55},
        "player_world_position": {"x": -450., "y": -2614., "z": 6.,
                                  "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS"},
        "active_quests": [{"quest_id": 58914, "is_complete": True,
                           "objectives": []}],
        "quest_locations": [location], "world_map_open": False,
        "player_present": True,
    }, 1.))
    return world


def test_completed_quest_normalized_marker_cannot_launch_direct_move():
    world = _world({"quest_id": 58914, "map_id": 1409, "x": .52, "y": .49,
                    "coordinate_space": "NORMALIZED_MAP", "source": "QUEST_POI"})

    proposals = QuestLocationPlanningPolicy().propose_known_locations(world)

    assert not any(proposal.skill == "MOVE" for proposal in proposals)


def test_turnin_resolver_map_only_region_cannot_launch_direct_move():
    record = SimpleNamespace(
        quest_id=58914, current_state="COMPLETED",
        lifecycle_state="READY_TO_TURN_IN",
        known_locations=[{"map_id": 1409, "x": .52, "y": .49,
                          "coordinate_space": "NORMALIZED_MAP",
                          "source": "QUEST_API_WAYPOINT"}],
    )

    proposals = QuestLocationPlanningPolicy().propose_turnins(
        {58914: record}, {"map_id": 1409}, {})

    assert proposals == []


def test_completed_quest_api_world_point_requires_mmap_route():
    world = _world({
        "quest_id": 58914, "map_id": 1409, "x": .52, "y": .49,
        "coordinate_space": "NORMALIZED_MAP", "source": "QUEST_POI",
        "world_position": {"x": -420., "y": -2600., "instance_id": 2175,
                           "ui_map_id": 1409, "coordinate_space": "WORLD_YARDS",
                           "source": "C_MAP_WORLD_POS", "z_known": False},
    })

    proposal = QuestLocationPlanningPolicy().propose_known_locations(world)[0]

    assert proposal.skill == "MOVE"
    assert proposal.parameters["coordinate_space"] == "WORLD_YARDS"
    assert proposal.parameters["instance_id"] == 2175
    assert proposal.parameters["map_id"] == 1409
    assert proposal.parameters["purpose"] == "LOCATE_TURN_IN_REGION"
    assert proposal.parameters["require_navmesh"] is True
    assert proposal.priority >= 100
    assert SkillRegistry().available(proposal, world)


def test_in_progress_quest_api_world_point_requires_mmap_route():
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "progress", "frame_id": "progress", "timestamp": 1.,
        "monotonic_time": 1., "map_id": 1409, "orientation": 0.,
        "position": {"x": .53, "y": .55},
        "player_world_position": {"x": -450., "y": -2614.,
                                  "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS"},
        "active_quests": [{"quest_id": 58914, "is_complete": False,
                           "objectives": []}],
        "quest_locations": [{
            "quest_id": 58914, "map_id": 1409, "x": .52, "y": .49,
            "coordinate_space": "NORMALIZED_MAP", "source": "QUEST_POI",
            "world_position": {"x": -420., "y": -2600., "instance_id": 2175,
                               "ui_map_id": 1409, "coordinate_space": "WORLD_YARDS",
                               "source": "C_MAP_WORLD_POS", "z_known": False},
        }], "world_map_open": False, "player_present": True,
    }, 1.))

    proposal = QuestLocationPlanningPolicy().propose_known_locations(world)[0]

    assert proposal.parameters["coordinate_space"] == "WORLD_YARDS"
    assert proposal.parameters["instance_id"] == 2175
    assert proposal.parameters["purpose"] == "LOCATE_QUEST_OBJECTIVE_REGION"
    assert proposal.parameters["require_navmesh"] is True
    assert SkillRegistry().available(proposal, world)

    policy = QuestLocationPlanningPolicy()
    proposal = policy.propose_known_locations(world)[0]
    policy.mark_reached(proposal.parameters, world.state)
    assert policy.propose_known_locations(world) == []
