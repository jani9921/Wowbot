from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.vision.map_mouseover import classify_tooltip


def world(**extra):
    value = WorldModel()
    value.ingest(Observation.create({
        "session_id": "s",
        "frame_id": "f",
        "timestamp": 1,
        "map_id": 1409,
        "position": {"x": .5, "y": .5},
        "orientation": 0,
        "player_present": True,
        "world_map_open": False,
        **extra,
    }, 1))
    return value


def test_classify_tooltip_still_recognizes_giver_and_turn_in():
    assert classify_tooltip("Captain Garrick ~ <Expedition Leader> ~ Warming Up") == "UNKNOWN"
    assert classify_tooltip("Available Quest: Warming Up") == "QUEST_GIVER"
    assert classify_tooltip("Quest Complete: Warming Up") == "QUEST_TURN_IN"
    assert classify_tooltip("Random Villager ~ <Townsperson>") == "UNKNOWN"


def test_planner_proposes_talk_for_tooltip_confirmed_quest_giver():
    mouse = {"guid": "Creature-1", "name": "Captain Garrick", "is_attackable": False,
             "is_dead": False, "tooltip": "Available Quest: Warming Up"}
    target = {"guid": "Creature-1", "name": "Captain Garrick", "attackable": False, "dead": False}
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world(mouseover=mouse, target=target), 1)
    talks = [p for p in proposals if p.skill == "TALK" and p.parameters.get("quest_role") == "QUEST_GIVER"]
    assert len(talks) == 1
    assert talks[0].parameters["guid"] == "Creature-1"


def test_planner_proposes_talk_for_tooltip_confirmed_turn_in():
    mouse = {"guid": "Creature-2", "name": "Alaria", "is_attackable": False,
             "is_dead": False, "tooltip": "Quest Complete: Warming Up"}
    target = {"guid": "Creature-2", "name": "Alaria", "attackable": False, "dead": False}
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world(mouseover=mouse, target=target), 1)
    assert any(p.skill == "TALK" and p.parameters.get("quest_role") == "QUEST_TURN_IN" for p in proposals)


def test_planner_does_not_propose_tooltip_talk_for_a_plain_npc():
    mouse = {"guid": "Creature-3", "name": "Random Villager", "is_attackable": False,
             "is_dead": False, "tooltip": "Random Villager ~ <Townsperson>"}
    target = {"guid": "Creature-3", "name": "Random Villager", "attackable": False, "dead": False}
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world(mouseover=mouse, target=target), 1)
    assert not any(p.skill == "TALK" and "quest_role" in p.parameters for p in proposals)


def test_planner_does_not_propose_tooltip_talk_before_targeting_same_unit():
    mouse = {"guid": "Creature-1", "name": "Captain Garrick", "is_attackable": False,
             "is_dead": False, "tooltip": "Available Quest: Warming Up"}
    target = {"guid": "Creature-OTHER", "attackable": False, "dead": False}
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world(mouseover=mouse, target=target), 1)
    assert not any(p.skill == "TALK" and "quest_role" in p.parameters for p in proposals)


def test_planner_does_not_propose_tooltip_talk_while_dialog_is_open():
    mouse = {"guid": "Creature-1", "name": "Captain Garrick", "is_attackable": False,
             "is_dead": False, "tooltip": "Available Quest: Warming Up"}
    target = {"guid": "Creature-1", "name": "Captain Garrick", "attackable": False, "dead": False}
    quest_ui = {"open": True, "entries": [], "action": "", "x": 0, "y": 0}
    proposals = Planner(SkillRegistry()).candidates(
        Goal.parse("Questelj", 1), world(mouseover=mouse, target=target, quest_ui=quest_ui), 1)
    assert not any(p.skill == "TALK" and p.parameters.get("quest_role") == "QUEST_GIVER" for p in proposals)


def test_planner_keeps_generic_interact_fallback_for_friendly_target():
    mouse = {"guid": "Creature-3", "is_attackable": False, "is_dead": False}
    target = {"guid": "Creature-3", "attackable": False, "dead": False}
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world(mouseover=mouse, target=target), 1)
    assert any(p.skill == "INTERACT" for p in proposals)
