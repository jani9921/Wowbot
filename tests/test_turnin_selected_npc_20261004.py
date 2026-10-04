"""Live 2026-10-04 00:55 and 08:52: Captain Garrick (turn-in NPC of the
completed Enhanced Combat Tactics) was selected next to the turn-in point,
but the turn-in route MOVE kept winning and the agent went on inspecting
for "?" (user)."""
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel

GARRICK = {"guid": "Creature-0-3113-2175-63341-164577-00004180D8", "name": "Captain Garrick",
           "npc_id": 164577, "attackable": False}
QUEST = {"quest_id": 59254, "title": "Enhanced Combat Tactics", "is_complete": True,
         "objectives": [{"description": "3/3 Abilities proven against Captain Garrick",
                         "is_complete": True, "current": 3, "required": 3}]}
POI = {"quest_id": 59254, "map_id": 1409, "x": .584, "y": .742, "source": "QUEST_POI",
       "coordinate_space": "NORMALIZED_MAP",
       "world_position": {"x": -247., "y": -2484., "instance_id": 2175, "ui_map_id": 1409,
                          "coordinate_space": "WORLD_YARDS", "source": "C_MAP_WORLD_POS"}}


def _world(target, player=(-229.7, -2485.9), quest=QUEST):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "t", "timestamp": 1., "frame_id": "f1", "monotonic_time": 1.,
        "map_id": 1409, "orientation": 0., "position": {"x": .584, "y": .742},
        "player_world_position": {"x": player[0], "y": player[1], "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS"},
        "active_quests": [quest], "quest_locations": [POI], "target": target,
        "ui_error": "You need to be closer to interact with that target.",
        "world_map_open": False, "player_present": True}, 1.))
    return world


def test_selected_turn_in_npc_is_talked_to_instead_of_routing_to_the_point():
    planner = Planner(SkillRegistry())
    proposal = planner.candidates(Goal.parse("Questelj", 1.), _world(GARRICK), 1.)[0]
    assert proposal.skill == "INTERACT"
    assert proposal.parameters == {"guid": GARRICK["guid"], "purpose": "TURN_IN_CANDIDATE"}


def test_attackable_or_far_unnamed_target_is_not_a_turn_in_candidate():
    planner = Planner(SkillRegistry())
    boar = {"guid": "Creature-0-1-2-3-4-5", "name": "Wandering Boar", "attackable": True}
    assert not planner.quest._turn_in_candidate(_world(boar).state, boar)
    stranger = {"guid": "Creature-0-1-2-3-4-7", "name": "Goldilox", "attackable": False}
    assert planner.quest._turn_in_candidate(_world(stranger).state, stranger)   # 17 yd from the point
    assert not planner.quest._turn_in_candidate(_world(stranger, player=(-180., -2400.)).state, stranger)
    open_quest = {**QUEST, "is_complete": False}
    assert not planner.quest._turn_in_candidate(_world(GARRICK, quest=open_quest).state, GARRICK)
