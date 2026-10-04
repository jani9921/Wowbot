"""Selected-target minimap marker (user 2026-10-04 screenshots, 1600x900).

The current target is drawn as a reaction-coloured dot (green friendly,
yellow neutral, red hostile) inside four gold crosshair pips.  The crops are
160x160 px around the minimap (disc centre (80, 80), radius ~76 px)."""
from pathlib import Path

import numpy as np
import pytest

from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel
from wowbot.vision.minimap_quest_dot import detect_quest_dots
from wowbot.vision.minimap_target_marker import detect_target_markers

DATA = Path(__file__).parent / "data" / "minimap_target_marker"
CENTER, RADIUS = (80., 80.), 76.


def _load(name):
    from PIL import Image
    return np.array(Image.open(DATA / f"{name}.png").convert("RGB"))


@pytest.mark.parametrize("name,colour", [("friendly_green", "GREEN"), ("neutral_yellow", "YELLOW"),
                                          ("hostile_red", "RED")])
def test_exactly_one_target_marker_in_the_reaction_colour(name, colour):
    markers = detect_target_markers(_load(name), CENTER, RADIUS)
    assert [marker["colour"] for marker in markers] == [colour]
    assert markers[0]["pips"] >= 3


@pytest.mark.parametrize("name", ["friendly_green", "neutral_yellow", "hostile_red"])
def test_quest_dot_detector_ignores_the_target_marker_and_the_turn_in_glyph(name):
    # Each crop also shows a turn-in "?" icon; neither it nor the yellow
    # target marker is a quest objective dot.
    assert detect_quest_dots(_load(name), CENTER, RADIUS) == []


def test_selected_target_gets_a_world_position_from_its_marker():
    marker = {"colour": "RED", "offset": [.212, .2325], "distance_fraction": .3146, "pixels": 9, "pips": 4}
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "m", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .6, "y": .7}, "player_present": True,
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "target": {"guid": "Creature-0-1-2-3-4-5", "name": "Geolord Grek'og", "attackable": True,
                   "reaction": "hostile"},
        "visual_candidates": [{"kind": "minimap_target_marker", "source": "MINIMAP_CV",
                               "view_radius_yards": 100., "markers": [marker]}]}, 1.))
    position = world.state["target"]["world_position"]
    # North-up: down (+dy) is south (-x), right (+dx) is east (-y).
    assert position["source"] == "MINIMAP_TARGET_MARKER"
    assert position["x"] == pytest.approx(-23.25, abs=.1) and position["y"] == pytest.approx(-21.2, abs=.1)
    # A marker in the wrong reaction colour is not this target's.
    world2 = WorldModel()
    world2.ingest(Observation.create({
        "session_id": "m", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .6, "y": .7}, "player_present": True,
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "target": {"guid": "Creature-0-1-2-3-4-6", "name": "Austin", "attackable": False,
                   "reaction": "friendly"},
        "visual_candidates": [{"kind": "minimap_target_marker", "source": "MINIMAP_CV",
                               "view_radius_yards": 100., "markers": [marker]}]}, 1.))
    assert "world_position" not in world2.state["target"]
