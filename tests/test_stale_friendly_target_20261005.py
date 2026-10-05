"""Live 2026-10-05 05:39 (pid 1212): after "Stocking Up on Supplies" was
turned in, Captain Garrick stayed selected.  With an empty quest log every
selected friendly unit counted as relevant, so his approach/WAIT branch ended
planning before the mouseover hand-off: Private Cole (a "!" over his head,
58914 A Warrior's End) was hovered and left, Henry Garrick (55196 The Harpy
Problem) was hovered at his pin and left, and only Bjorn -- found after the
client dropped the far target -- was taken (user: "harom questgiverhez ment
oda es a harmadikat vette csak fel").  A friendly unit already dealt with
that shows no "!" is released: it no longer steers or blocks planning.
"""
from wowbot.agent.models import Goal
from wowbot.agent.quest_giver_evidence import selected_npc_shows_quest_symbol

from test_agent_core import agent, quest_npc_boxes, state

GARRICK = {"guid": "Creature-0-3113-2175-63341-245394-00004115E3", "name": "Captain Garrick",
           "npc_id": 245394, "unit_type": "NPC", "attackable": False}
COLE = {"guid": "Creature-0-3113-2175-63341-156801-0000C115E3", "name": "Private Cole",
        "npc_id": 156801, "unit_type": "NPC", "is_attackable": False}


def _pin(quest_id, name, x, y):
    return {"quest_id": quest_id, "quest_name": name, "is_campaign": True, "x": .5, "y": .5,
            "source": "QUESTLINE_API", "map_id": 1409,
            "world_position": {"x": x, "y": y, "instance_id": 2175, "ui_map_id": 1409,
                               "coordinate_space": "WORLD_YARDS", "source": "C_MAP_WORLD_POS"}}


PINS = [_pin(58914, "A Warrior's End", 187., -2280.), _pin(55965, "Westward Bound", 199., -2271.),
        _pin(55196, "The Harpy Problem", 267., -2339.)]


def _frame(t, **overrides):
    values = dict(
        map_id=1409, target=GARRICK, mouseover=COLE, cursor_position={"nx": .5, "ny": .6},
        cursor_sample_time=t, mouseover_sample_time=t, active_quests=[],
        player_world_position={"x": 183.2, "y": -2285.6, "instance_id": 2175,
                               "coordinate_space": "WORLD_YARDS"},
        map_pois={"available_quests": PINS}, world_map_open=False,
        visual_candidates=quest_npc_boxes(.5, .6, "WORLD3D:cole"))
    values.update(overrides)
    return state(t, **values)


def _handled(value, guid, at):
    value.planner.quest.interacted_at[guid] = at
    value.planner.quest.interacted_guids[guid] = "[]"


def test_the_hovered_quest_giver_is_taken_while_a_handled_npc_is_still_selected():
    value, _ = agent()
    _handled(value, GARRICK["guid"], .5)
    value.tick(_frame(1.), 1.)
    assert value.last_decision["skill"] == "TARGET"
    assert value.pending.proposal.parameters["guid"] == COLE["guid"]


def test_a_handled_selected_npc_without_a_symbol_is_not_approached_again():
    """Live 05:40: VISUAL_APPROACH to Captain Garrick from the Harpy pin, 88 yd away."""
    value, _ = agent()
    _handled(value, GARRICK["guid"], .5)
    frame = _frame(1., mouseover=None, visual_candidates=[], player_world_position={
        "x": 260.2, "y": -2332.7, "instance_id": 2175, "coordinate_space": "WORLD_YARDS"})
    proposals = value.planner.candidates(Goal.parse("Questelj", 1.), _world(value, frame), 1.)
    assert not any(p.parameters.get("guid") == GARRICK["guid"] for p in proposals)


def test_a_selected_npc_with_a_quest_symbol_stays_relevant():
    """A follow-up quest at the same NPC keeps him: the "!" is the evidence."""
    value, _ = agent()
    _handled(value, GARRICK["guid"], .5)
    frame = _frame(1., mouseover=GARRICK, visual_candidates=quest_npc_boxes(.5, .6, "WORLD3D:garrick"))
    world = _world(value, frame)
    assert value.planner.quest._friendly_target_relevant(world, Goal.parse("Questelj", 1.), GARRICK)


def test_an_npc_not_yet_dealt_with_keeps_the_discovery_rule():
    """Selected but never talked to: the no-quest discovery path is unchanged."""
    value, _ = agent()
    frame = _frame(1., mouseover=None, visual_candidates=[])
    world = _world(value, frame)
    assert value.planner.quest._friendly_target_relevant(world, Goal.parse("Questelj", 1.), GARRICK)


def test_symbol_over_a_selected_npc_needs_its_own_box():
    """Not hovered and no bound track: the cursor's box (Cole) is not Garrick's."""
    frame = _frame(1.)
    assert not selected_npc_shows_quest_symbol(frame, GARRICK["guid"])
    assert selected_npc_shows_quest_symbol(frame, COLE["guid"])          # hovered, "!" over him
    bound = {**frame, "mouseover": None,
             "confirmed_mouseover_anchors": {GARRICK["guid"]: {"track_id": "WORLD3D:cole"}}}
    assert selected_npc_shows_quest_symbol(bound, GARRICK["guid"])


def _world(value, frame):
    from wowbot.agent.models import Observation
    value.world.ingest(Observation.create(frame, frame["monotonic_time"]))
    return value.world
