"""Live 2026-10-03 23:50: Cooking Meat was complete and the agent stood at
its turn-in point; a World Map opened in a tick where the turn-in point was
missing stayed open, the turn-in branch skipped the map policy that closes
it, and the "?" SEEK is unavailable over an open map -- 8 minutes of WAIT."""
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel


def _world(map_open: bool) -> WorldModel:
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "a", "timestamp": 1., "frame_id": "one", "map_id": 1409,
        "world_map_open": map_open, "position": {"x": .58, "y": .74}, "orientation": 0.,
        "player_present": True,
        "player_world_position": {"x": -250., "y": -2501.9, "z_known": False,
                                  "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "active_quests": [{"quest_id": 55174, "is_complete": True, "objectives": []}],
        "quest_locations": [{
            "quest_id": 55174, "map_id": 1409, "x": .5836, "y": .7445,
            "coordinate_space": "NORMALIZED_MAP", "source": "QUEST_POI",
            "world_position": {"x": -245., "y": -2492., "z_known": False, "instance_id": 2175,
                               "ui_map_id": 1409, "coordinate_space": "WORLD_YARDS",
                               "source": "C_MAP_WORLD_POS"}}],
    }, 1.))
    return world


def test_open_map_at_a_known_turn_in_point_is_closed():
    planner = Planner(SkillRegistry())
    goal = Goal.parse("Questelj", 1.)
    proposal = planner.candidates(goal, _world(True), 1.)[0]
    assert proposal.skill == "CLOSE_MAP"
    assert proposal.parameters["purpose"] == "RESTORE_WORLD3D_FOR_TURN_IN"
    assert planner.candidates(goal, _world(False), 2.)[0].skill != "CLOSE_MAP"
