"""LIVE VISION route view (design doc §11; user 2026-10-05: "berajzolni a
waypointokat meg összekötni őket, hogy az agent így fog közlekedni")."""
import math

import numpy as np

from wowbot.diagnostics.navigation_overlay import bearing_text, draw_navigation, to_heading_up


def test_heading_up_matches_the_movement_controller_convention():
    player = {"x": 0., "y": 0., "facing": 0.}          # facing north (+x)
    assert to_heading_up(player, [10., 0., 0.]) == (0., 10.)                 # ahead
    right, forward = to_heading_up(player, [0., -10., 0.])                   # -y = east = right
    assert right > 9.9 and abs(forward) < 1e-9
    turned = {"x": 0., "y": 0., "facing": math.pi/2}  # facing west (+y)
    right, forward = to_heading_up(turned, [0., 10., 0.])
    assert abs(right) < 1e-9 and forward > 9.9


def test_bearing_names_side_distance_and_floor():
    navigation = {"player": {"x": 0., "y": 0., "z": 95., "facing": 0.},
                  "route": [[10., -10., 87.]], "next_index": 0, "purpose": "LOCATE_QUEST_OBJECTIVE_REGION"}
    text = bearing_text(navigation)
    assert "14 yd" in text and "jobbra" in text and "↓8 yd" in text


def test_the_inset_is_drawn_onto_the_frame():
    canvas = np.zeros((900, 1600, 3), np.uint8)
    navigation = {"player": {"x": 93., "y": -2249., "z": 95., "facing": 2.8},
                  "route": [[85., -2238., 91.], [81., -2224., 84.], [72., -2220., 78.]], "next_index": 0,
                  "destination": [85.9, -2208., -21.], "purpose": "zone sweep",
                  "sweep": {"hops": [[85., -2238., 91.], [81., -2224., 84.]], "visited": [0], "direction": "DOWN"}}
    draw_navigation(canvas, navigation)
    inset = canvas[900-220-70:900-70, 1600-220-10:1600-10]
    assert inset.any()                                   # route, arrow and frame painted
    assert canvas[820:860, 500:1100].any()               # bearing line
    draw_navigation(canvas, None)                         # no packet: nothing to do
