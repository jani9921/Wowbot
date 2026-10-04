"""Live 2026-10-04 09:42: The Scout-o-Matic 5000 -- "0/1 Use Scout-o-Matic 5000
to scout the area" -- arrives as a `monster` objective (normalized KILL).  The
Scout-o-Matic is a friendly vehicle NPC; the agent hovered it but never
selected or used it, because a friendly NPC is not relevant to a KILL objective."""
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.quest_model import objective_type, use_npc_subject
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel

OBJECTIVE = {"description": "0/1 Use Scout-o-Matic 5000 to scout the area", "type": "KILL",
             "raw_type": "monster", "current": 0, "required": 1, "is_complete": False}
QUEST = {"quest_id": 55193, "title": "The Scout-o-Matic 5000", "is_complete": False,
         "is_campaign": True, "objectives": [OBJECTIVE]}
SCOUT = {"guid": "Vehicle-0-3113-2175-63341-156518-00004115E3", "name": "Scout-o-Matic 5000",
         "npc_id": 156518, "is_attackable": False}


def test_use_clause_on_a_monster_objective_is_an_npc_interaction():
    assert use_npc_subject(OBJECTIVE) == "scout-o-matic 5000"
    assert objective_type(OBJECTIVE)[0] == "INTERACT_NPC"
    assert objective_type({"description": "0/7 Quilboar slain", "type": "KILL",
                           "raw_type": "monster"})[0] == "KILL"


def _world(**extra):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .62, "y": .6}, "player_present": True,
        "player_world_position": {"x": 93., "y": -2424., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "active_quests": [QUEST], "world_map_open": False, **extra}, 1.))
    return world


def test_hovered_scout_o_matic_is_selected():
    world = _world(mouseover=SCOUT, cursor_position={"nx": .52, "ny": .48, "sample_time": 1.},
                   target={})
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert any(p.skill == "TARGET" and p.parameters.get("guid") == SCOUT["guid"] for p in proposals)


def test_selected_scout_o_matic_is_used():
    world = _world(target={**SCOUT, "attackable": False})
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert proposals[0].skill == "INTERACT"
    assert proposals[0].parameters.get("guid") == SCOUT["guid"]


def test_vehicle_npc_is_used_with_interact_and_the_seat_verifies_it():
    from wowbot.verification.interaction import InteractionVerifier
    world = _world(target={**SCOUT, "attackable": False})
    first = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)[0]
    assert first.skill == "INTERACT"
    result = InteractionVerifier().evaluate({"in_vehicle": False, "target": SCOUT},
                                            {"in_vehicle": True, "target": SCOUT},
                                            expected_guid=SCOUT["guid"])
    assert result.success and "vehicle_entered" in result.evidence


def test_riding_a_vehicle_waits_for_the_scripted_path():
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), _world(in_vehicle=True), 1.)
    assert [p.skill for p in proposals] == ["WAIT"]


def test_only_the_named_npc_is_relevant_for_a_named_npc_objective():
    # Live 10:27: with "Use Scout-o-Matic 5000" open, Lindie Springstock was
    # selected and approached again and again.
    lindie = {"guid": "Creature-0-3113-2175-63341-149899-00004115E3", "name": "Lindie Springstock",
              "npc_id": 149899, "is_attackable": False}
    world = _world(mouseover=lindie, cursor_position={"nx": .46, "ny": .69, "sample_time": 1.}, target={})
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert not any(p.skill == "TARGET" and p.parameters.get("guid") == lindie["guid"] for p in proposals)


RIDE = {"quest_id": 55879, "title": "Ride of the Scientifically Enhanced Boar", "is_complete": False,
        "is_campaign": True, "objectives": [{"description": "0/1 Ride the Giant Boar", "type": "KILL",
                                             "raw_type": "monster", "current": 0, "required": 1,
                                             "is_complete": False}]}
GIANT_BOAR = {"guid": "Creature-0-3113-2175-63341-156595-0000421234", "name": "Giant Boar",
              "npc_id": 156595, "is_attackable": False}


def test_ride_clause_is_an_npc_interaction_and_excludes_item_on_unit():
    assert use_npc_subject(RIDE["objectives"][0]) == "giant boar"
    assert objective_type(RIDE["objectives"][0])[0] == "INTERACT_NPC"
    assert use_npc_subject({"description": "Use the Re-Sizer on boars", "type": "KILL",
                            "raw_type": "monster"}) is None


def test_giant_boar_is_selected_then_mounted_with_interact():
    hovered = _world(active_quests=[RIDE], mouseover=GIANT_BOAR,
                     cursor_position={"nx": .5, "ny": .5, "sample_time": 1.}, target={})
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), hovered, 1.)
    assert any(p.skill == "TARGET" and p.parameters.get("guid") == GIANT_BOAR["guid"] for p in proposals)
    selected = _world(active_quests=[RIDE], target={**GIANT_BOAR, "attackable": False})
    first = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), selected, 1.)[0]
    assert first.skill == "INTERACT" and first.parameters.get("guid") == GIANT_BOAR["guid"]
