"""User 2026-10-04: the agent inspected several NPCs at a hub before finding
the one to turn a quest in to.  The quest's own words (or its giver,
recorded by addon 0.9.52) name the ender; the local LLM reads the rest."""
from wowbot.agent.models import Observation
from wowbot.agent.quest_giver_evidence import friendly_npc_relevant
from wowbot.agent.quest_turn_in import turn_in_from_text, turn_in_names
from wowbot.agent.semantic_advisor import turnin_request, validate_turnin
from wowbot.agent.world import WorldModel


def test_explicit_return_lines_and_back_to_me_name_the_ender():
    assert turn_in_from_text({"objectives": [{"description": "Return to Captain Garrick at the beach"}]})["name"] \
        == "Captain Garrick"
    assert turn_in_from_text({"objectives": []}, {"objectives_text": "Speak with Lindie Springstock."})["name"] \
        == "Lindie Springstock"
    assert turn_in_from_text({"waypoint": {"text": "Return to Lady Jaina Proudmoore"}, "objectives": []})["name"] \
        == "Lady Jaina Proudmoore"
    giver = turn_in_from_text({"objectives": []}, {"objectives_text": "Slay them, then report back to me.",
                                                   "giver_name": "Austin Huxworth"})
    assert giver["name"] == "Austin Huxworth" and giver["source"].startswith("QUEST_GIVER")
    # A story naming people is not an instruction; nothing explicit -> unknown.
    assert turn_in_from_text({"objectives": [{"description": "0/8 Monstrous Cadaver slain"}]},
                             {"description": "Lindie says the boars are huge."}) is None


def test_llm_turn_in_answer_must_be_the_giver_or_copied():
    quest = {"quest_id": 5, "title": "Q"}
    key, payload = turnin_request(quest, {"giver_name": "Lindie Springstock",
                                          "description": "Find Kee-la near the cave; she will reward you."})
    assert validate_turnin(payload, {"turn_in_to": "GIVER"}) == {"name": "Lindie Springstock", "giver": True}
    assert validate_turnin(payload, {"turn_in_to": "Kee-la"})["name"] == "Kee-la"
    assert validate_turnin(payload, {"turn_in_to": "Marshal Dughan"})["name"] is None
    assert turnin_request(quest, {}) is None


COMPLETE = {"quest_id": 55879, "title": "Ride of the Scientifically Enhanced Boar", "is_complete": True,
            "objectives": [{"description": "8/8 Monstrous Cadaver slain", "raw_type": "monster", "type": "KILL",
                            "current": 8, "required": 8, "is_complete": True}]}


def _world(**extra):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .5, "y": .5}, "player_present": True,
        "player_world_position": {"x": 0., "y": 0.}, "active_quests": [COMPLETE], **extra}, 1.))
    return world


def test_recorded_giver_makes_that_npc_the_relevant_turn_in_target():
    world = _world(quest_text={"quest_id": 55879, "giver_name": "Lady Jaina Proudmoore",
                               "objectives_text": "Trample the cadavers, then report back to me."})
    assert world.state["quest_turn_in_names"]["55879"]["name"] == "Lady Jaina Proudmoore"
    assert turn_in_names(world.state) == ["Lady Jaina Proudmoore"]
    state = world.state
    assert friendly_npc_relevant(state, "Creature-0-1-2-3-4-5", {"KILL"}, unit_name="Lady Jaina Proudmoore")
    assert not friendly_npc_relevant(state, "Creature-0-1-2-3-4-6", {"KILL"}, unit_name="Lindie Springstock")


def test_selected_ender_is_a_turn_in_candidate():
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    world = _world(quest_text={"quest_id": 55879, "giver_name": "Lady Jaina Proudmoore",
                               "objectives_text": "Report back to me."})
    quest = Planner(SkillRegistry()).quest
    assert quest._turn_in_candidate(world.state, {"name": "Lady Jaina Proudmoore", "attackable": False})
    assert not quest._turn_in_candidate(world.state, {"name": "Lindie Springstock", "attackable": False})


def test_meet_names_the_turn_in_npc_and_an_llm_guess_keeps_the_giver():
    # Live 2026-10-05: "Meet Bjorn Stouthands west of the Alliance Camp."
    found = turn_in_from_text({"objectives": []},
                              {"objectives_text": "Meet Bjorn Stouthands west of the Alliance Camp."})
    assert found["name"] == "Bjorn Stouthands"
    assert turn_in_from_text({"objectives": []}, {"objectives_text": "Meet with Captain Garrick."})["name"] \
        == "Captain Garrick"
    # The vendor quest's ender was its giver; the model guessed the vendor.
    state = {"active_quests": [{"quest_id": 55194, "is_complete": True}],
             "quest_turn_in_names": {"55194": {"name": "Quartermaster Richter", "source": "LLM_SEMANTIC",
                                               "giver_name": "Captain Garrick"}}}
    assert turn_in_names(state) == ["Quartermaster Richter", "Captain Garrick"]
    state["quest_turn_in_names"]["55194"]["source"] = "QUEST_TEXT_PATTERN:OBJECTIVE_TEXT"
    assert turn_in_names(state) == ["Quartermaster Richter"]
