"""Minimap objective dots and their floor (user 2026-10-05, Hrun's pit):
yellow = our space, grey = a space we are not in, a triangle under/over a dot
= the objective is lower/higher than us."""
from pathlib import Path

import numpy as np
from PIL import Image

from wowbot.vision.minimap_floor_markers import detect_floor_markers

HERE = Path(__file__).parent


def _load(path):
    return np.asarray(Image.open(path).convert("RGB"))


def test_grey_dots_with_a_down_arrow_are_below_us():
    """The user's 1600x900 screenshot at the pit rim: four grey dots, each with a "▼"."""
    image = _load(HERE / "fixtures" / "minimap" / "grey_dots_below_1600x900.png")
    for radius in (72., 75., 78.):
        markers = detect_floor_markers(image, (85., 85.), radius)
        assert [(m["colour"], m["floor"]) for m in markers] == [("GREY", "BELOW")] * 4


def test_glyphs_and_the_target_crosshair_are_not_objective_dots():
    for name in ("friendly_green", "hostile_red", "neutral_yellow"):
        markers = detect_floor_markers(_load(HERE / "data" / "minimap_target_marker" / f"{name}.png"),
                                       (80., 80.), 76.)
        assert not [m for m in markers if m["colour"] == "YELLOW"]


def test_a_yellow_dot_with_a_floor_arrow_is_not_walked_to_on_this_floor():
    from types import SimpleNamespace
    from wowbot.agent.quest_location_planning import minimap_objective_dots
    state = {"player_world_position": {"x": 0., "y": 0., "instance_id": 2175}, "orientation": 0.,
             "active_quests": [{"quest_id": 55639, "is_complete": False}],
             "visual_candidates": [{"source": "MINIMAP_CV", "kind": "minimap_quest_dot", "view_radius_yards": 160.,
                                    "dots": [{"offset": [.2, .1], "floor": "BELOW"}]}]}
    assert minimap_objective_dots(state) == []
    state["visual_candidates"][0]["dots"][0]["floor"] = "SAME"
    assert len(minimap_objective_dots(state)) == 1
