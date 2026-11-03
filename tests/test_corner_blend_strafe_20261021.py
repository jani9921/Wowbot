"""Smoother runs: lean into safe bends, trim small errors by strafing.

User 2026-10-20 ("csináld meg mind", after reading PixelBuddy's movement
controller: 40 % look-ahead within 15 yd of a bend, strafing for small heading
errors, a wider pass radius when mounted).  A bend is leaned into only where
the simulated path stays on walkable ground -- never over the pit's drop.
"""
import math
from types import SimpleNamespace

import pytest

from wowbot.agent.movement_controller import CORNER_BLEND_MAX, ReachMovementController, corner_heading
from wowbot.navigation import NavigationService
from wowbot.navigation.contracts import GlobalRoute
from wowbot.navigation.z_resolver import ResolvedPosition

# A 90 degree bend to the left: (0, 0) -> (20, 0) -> (20, 20), floor at 73.
ANCHORS = ({"x": 0., "y": 0., "z": 73., "instance_id": 2175},
           {"x": 20., "y": 0., "z": 73., "instance_id": 2175},
           {"x": 20., "y": 20., "z": 73., "instance_id": 2175})


class Floor:
    def walkable_heights_at(self, instance_id, point, radius=2.5):
        return [73.]


class LedgeAlongTheLegs:
    """Only a 1.5 yd wide walkway along the legs; the bend's inside is a drop."""

    def walkable_heights_at(self, instance_id, point, radius=2.5):
        x, y = point["x"], point["y"]
        on_first = -1.5 <= y <= 1.5 and x <= 21.5
        on_second = 18.5 <= x <= 21.5 and y >= -1.5
        return [73.] if on_first or on_second else [10.]


def route_nav(geometry):
    nav = NavigationService(navmesh=geometry)
    nav._active_route = GlobalRoute("r", ANCHORS, (), 1., 1., 0., 1.)
    nav._active_request = SimpleNamespace(destination={"instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
                                          target_entity_id=None, avoid_combat=False, allow_combat=True,
                                          arrival=SimpleNamespace(radius=None, desired_range=None))
    nav._route_waypoint_index = 1
    nav._z.player = ResolvedPosition(10., 0., 73., .9, "MMAP", 2175, at=1.)
    return nav


def test_the_heading_leans_toward_the_next_waypoint_only_inside_the_window():
    straight = corner_heading((0., 0.), (20., 0.), (20., 20.), 10.)
    assert straight == pytest.approx(0.)                    # 20 yd out: just the corner
    close = corner_heading((19.9, 0.), (20., 0.), (20., 20.), 10.)
    to_next = math.atan2(20., .1)
    assert close == pytest.approx(CORNER_BLEND_MAX * (1-.01) * to_next, rel=1e-3)


def test_open_ground_grants_a_bend_window_and_the_waypoint_carries_it():
    nav = route_nav(Floor())
    destination = nav._current_route_destination()
    assert destination["corner_blend_yards"] == 10.
    assert destination["corner_next"] == {"x": 20., "y": 20.}


def test_no_window_where_the_cut_would_leave_the_walkway():
    nav = route_nav(LedgeAlongTheLegs())
    assert nav._corner_window(1) == 0.
    assert nav._current_route_destination()["corner_blend_yards"] == 0.


def test_no_window_for_the_final_waypoint_or_without_a_navmesh():
    nav = route_nav(Floor())
    assert nav._corner_window(2) == 0.
    bare = route_nav(None)
    assert bare._corner_window(1) == 0.


def test_the_controller_starts_the_bend_early_inside_a_window():
    destination = {"coordinate_space": "WORLD_YARDS", "x": 20., "y": 0., "route_waypoint_final": False,
                   "route_id": "r", "instance_id": 2175, "corner_next": {"x": 20., "y": 20.}}

    def first(window):
        controller = ReachMovementController()
        controller.last_forward_at = .8
        state = {"player_world_position": {"x": 15., "y": 0., "coordinate_space": "WORLD_YARDS",
                                           "sample_time": 1.}, "orientation": 0., "monotonic_time": 1.}
        controller.start({**destination, "corner_blend_yards": window}, state, "s", 1., continuing=True)
        return controller.command({**state, "monotonic_time": 1.05}, "c", 1.05)[0]

    assert first(0.).simultaneous == ()                     # no window: straight at the corner
    leaning = first(10.)
    assert leaning.binding == "MOVEFORWARD" and leaning.simultaneous == ("TURNLEFT",)


def test_mounted_a_safe_bend_is_passed_from_three_yards():
    nav = route_nav(Floor())
    beside = {"player_world_position": {"x": 17.6, "y": 1., "instance_id": 2175}}
    assert not nav._intermediate_waypoint_passed(beside)
    nav._route_previous_position = None
    assert nav._intermediate_waypoint_passed({**beside, "is_mounted": True})
    ledge = route_nav(LedgeAlongTheLegs())
    assert not ledge._intermediate_waypoint_passed({**beside, "is_mounted": True})


def run_straight(error, *, steps=50, distance=40.):
    """Commands of a running controller facing ``error`` off the bearing."""
    controller = ReachMovementController()
    controller.last_forward_at = .9
    goal = {"coordinate_space": "WORLD_YARDS", "x": distance*math.cos(error), "y": distance*math.sin(error),
            "route_waypoint_final": True, "instance_id": 2175}
    state = {"player_world_position": {"x": 0., "y": 0., "coordinate_space": "WORLD_YARDS",
                                       "sample_time": 1.}, "orientation": 0., "monotonic_time": 1.}
    controller.start(goal, state, "s", 1., continuing=True)
    commands = []
    for k in range(steps):
        at = 1. + .04*(k+1)
        commands.extend(controller.command({**state, "monotonic_time": at}, f"c{k}", at))
    return commands


def test_a_small_error_is_trimmed_by_strafing_in_proportion():
    commands = run_straight(.08)
    strafes = [c for c in commands if c.simultaneous == ("STRAFELEFT",)]
    assert all(c.binding == "MOVEFORWARD" for c in commands)
    # Strafe share ~ error / 45 deg (.08 / .785 = 10 %).
    assert .05 <= len(strafes)/len(commands) <= .2
    right = run_straight(-.08)
    assert any(c.simultaneous == ("STRAFERIGHT",) for c in right)


def test_no_strafe_for_a_tiny_error_or_close_to_the_destination():
    assert not any(c.simultaneous for c in run_straight(.02))
    assert not any(c.simultaneous for c in run_straight(.08, distance=6.))
