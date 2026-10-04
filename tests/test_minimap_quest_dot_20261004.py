"""Yellow quest-objective dots on the minimap (user 2026-10-04).

Live 00:25-00:28: Enhanced Combat Tactics (59254) — "Abilities proven
against Captain Garrick" — showed Garrick as a yellow minimap dot ~38 yd from
the player, inside the camp outline; the agent only searched visually.  No
API exposes NPC or minimap-blip positions."""
import math
from pathlib import Path

import numpy as np
import pytest

from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.vision.minimap_quest_dot import detect_quest_dots

CAPTURE = Path("output/agent/pid-15020/live-captures/20261004-002251-581-002/0405-002807-403-critical.jpg")
QUEST = {"quest_id": 59254, "title": "Enhanced Combat Tactics", "is_complete": False,
         "objectives": [{"description": "0/3 Abilities proven against Captain Garrick",
                         "type": "KILL", "required": 3, "current": 0, "is_complete": False}]}
POI = {"quest_id": 59254, "map_id": 1409, "x": .5845, "y": .7414, "source": "QUEST_POI",
       "coordinate_space": "NORMALIZED_MAP",
       "world_position": {"x": -238., "y": -2495., "instance_id": 2175, "ui_map_id": 1409,
                          "coordinate_space": "WORLD_YARDS", "source": "C_MAP_WORLD_POS"}}
DOTS = {"track_id": "minimap:quest_dots", "kind": "minimap_quest_dot", "source": "MINIMAP_CV",
        "inspectable": False, "view_radius_yards": 233.3, "rotate_minimap": False,
        "dots": [{"offset": [-.1194, -.1181], "distance_fraction": .1679, "pixels": 7}]}


def _synthetic_minimap():
    image = np.full((120, 120, 3), (70, 60, 40), dtype=np.uint8)       # dark ground
    image[30:34, 40:44] = (230, 196, 86)                               # the quest dot
    image[58:62, 58:62] = (235, 235, 235)                              # player arrow
    image[80:84, 30:34] = (220, 120, 40)                               # orange foliage
    return image


def test_detector_finds_the_yellow_dot_but_not_orange_foliage_or_the_arrow():
    dots = detect_quest_dots(_synthetic_minimap(), (60., 60.), 50.)
    assert len(dots) == 1
    dx, dy = dots[0]["offset"]
    assert dx == pytest.approx((41.5-60)/50, abs=.01) and dy == pytest.approx((31.5-60)/50, abs=.01)


@pytest.mark.skipif(not CAPTURE.is_file(), reason="live capture not present")
def test_detector_on_the_live_garrick_capture():
    from PIL import Image
    image = np.array(Image.open(CAPTURE).convert("RGB"))
    height, width = image.shape[:2]
    dots = detect_quest_dots(image, (.94108569*width, .13592452*height), .0941014*height)
    assert [dot["offset"] for dot in dots] == [[-.1194, -.1181]]


def _world(**extra):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "dot", "timestamp": 1., "frame_id": "f1", "monotonic_time": 1.,
        "map_id": 1409, "orientation": 0., "position": {"x": .584, "y": .745},
        "player_world_position": {"x": -246.05, "y": -2540.55, "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS"},
        "active_quests": [QUEST], "quest_locations": [POI], "visual_candidates": [DOTS],
        "world_map_open": False, "player_present": True, **extra}, 1.))
    return world


def test_planner_walks_to_the_minimap_dot():
    planner = Planner(SkillRegistry())
    proposals = planner.quest.location_policy.propose_known_locations(_world())
    move = next(p for p in proposals if p.parameters.get("purpose") == "APPROACH_MINIMAP_QUEST_DOT")
    # North-up minimap: up = +x (north), left = +y (west); 0.1194*233 ~ 27.9 yd.
    assert move.parameters["x"] == pytest.approx(-246.05 + .1181*233.3, abs=.2)
    assert move.parameters["y"] == pytest.approx(-2540.55 + .1194*233.3, abs=.2)
    assert move.parameters["quest_id"] == 59254


def test_no_dot_move_while_a_unit_is_selected():
    # A selected unit is drawn as a yellow dot too (user 2026-10-04); the
    # objective NPC itself, once selected, belongs to COMBAT/INTERACT.
    planner = Planner(SkillRegistry())
    for target in ({"guid": "Creature-0-1-2-3-4-5", "name": "Wandering Boar", "attackable": True},
                   {"guid": "Creature-0-1-2-3-4-6", "name": "Captain Garrick", "attackable": True}):
        proposals = planner.quest.location_policy.propose_known_locations(_world(target=target))
        assert not any(p.parameters.get("purpose") == "APPROACH_MINIMAP_QUEST_DOT" for p in proposals)


def test_running_dot_move_hands_over_when_the_objective_npc_is_selected():
    from types import SimpleNamespace
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    attempt = SimpleNamespace(proposal=SimpleNamespace(
        skill="MOVE", parameters={"purpose": "APPROACH_MINIMAP_QUEST_DOT", "x": -218.9, "y": -2513.7}))
    state = {"active_quests": [QUEST], "player_world_position": {"x": -208.2, "y": -2512.6}}
    assert movement_visual_interrupt(attempt, {**state, "target": {}}) is None
    boar = {"guid": "Creature-0-1-2-3-4-5", "name": "Wandering Boar", "attackable": True}
    assert movement_visual_interrupt(attempt, {**state, "target": boar}) is None
    garrick = {"guid": "Creature-0-1-2-3-4-6", "name": "Captain Garrick", "attackable": True}
    interrupt = movement_visual_interrupt(attempt, {**state, "target": garrick})
    assert interrupt["kind"] == "OBJECTIVE_NPC_TARGETED"


def test_planner_candidates_choose_the_dot_move():
    planner = Planner(SkillRegistry())
    first = planner.candidates(Goal.parse("Questelj", 1.), _world(), 1.)[0]
    assert first.skill == "MOVE" and first.parameters["purpose"] == "APPROACH_MINIMAP_QUEST_DOT"


def test_dot_at_a_completed_quests_turn_in_point_is_not_an_objective():
    # Live 09:20: Down with the Quilboar complete (turn-in ~(105,-2415)), Quilboar
    # Shadow Magic open (POI (37,-2601)); the dot 10-15 yd from the turn-in point
    # is the quest ender, 200 yd from the open quest's POI.
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    world = WorldModel()
    player = {"x": 64., "y": -2481., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}
    # dot at (115,-2416): up = +x north 51 yd, left = +y west 65 yd.
    dots = {**DOTS, "dots": [{"offset": [-65/233.3, -51/233.3], "distance_fraction": .35, "pixels": 3}]}
    world.ingest(Observation.create({
        "session_id": "dot", "timestamp": 1., "frame_id": "f1", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .6, "y": .7}, "player_world_position": player,
        "active_quests": [{"quest_id": 55186, "is_complete": True, "objectives": []},
                          {"quest_id": 55184, "is_complete": False,
                           "objectives": [{"description": "2/7 Quilboar slain"}]}],
        "quest_locations": [
            {**POI, "quest_id": 55184, "world_position": {**POI["world_position"], "x": 37., "y": -2601.}},
            {**POI, "quest_id": 55186, "world_position": {**POI["world_position"], "x": 105., "y": -2415.}}],
        "visual_candidates": [dots], "world_map_open": False, "player_present": True}, 1.))
    assert QuestLocationPlanningPolicy().minimap_dot_move(world) is None
