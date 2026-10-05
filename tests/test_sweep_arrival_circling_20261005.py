"""Live 2026-10-05 (Hrun's pit, quest 55639): at zone-sweep hop 4 the agent
turned on the spot for 30 s, 0.08-0.46 yd from its destination.

* The mmap route ends on Detour's float32 point, 7.5e-5 yd from the
  requested float64 destination, so ``needs_replan`` was true on every
  ``command()``; each replan restarted the controller and reset ARRIVED to
  MOVING.
* The FAST lane consumed the arriving sample and saw ARRIVED, but only the
  medium tick finishes a skill, and on that same sample it saw no fresh
  position ("awaiting"), so the MOVE never ended.

The cocoon's minimap dot (yellow, arrow below) also flickered to "same
floor" on two frames: a dim arrow and a 1 px outline row over its base.
"""
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image

from test_agent_core import binding_file

from wowbot.agent.bindings import BindingsCache
from wowbot.agent.movement_controller import ReachMovementController as MovementController
from wowbot.navigation.mmap_navmesh import NavMeshPath
from wowbot.navigation.service import NavigationService
from wowbot.vision.minimap_floor_markers import detect_floor_markers

FIXTURES = Path(__file__).parent / "fixtures" / "minimap"
# Request (float64) and Detour end (float32) of the live hop 4.
REQUESTED = (69.79095273988392, -2246.5808860550665)
DETOUR_END = (69.79095458984375, -2246.580810546875)


class _Navmesh:
    def __init__(self):
        self.calls = 0

    def find_path(self, instance_id, start, end):
        self.calls += 1
        anchor = {"instance_id": instance_id, "coordinate_space": "WORLD_YARDS",
                  "source": "TRINITYCORE_MMAP", "z": 68.15}
        return NavMeshPath(({**anchor, "x": start["x"], "y": start["y"]},
                            {**anchor, "x": DETOUR_END[0], "y": DETOUR_END[1]}), 3, 1, 6.)


def _state(x, y, sample_time, orientation=4.3):
    return {"session_id": "s", "map_id": 1409, "orientation": orientation,
            "monotonic_time": sample_time,
            "player_world_position": {"x": x, "y": y, "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS",
                                      "sample_time": sample_time},
            "movement": {"speed": 0., "moving": False}}


def _hop():
    return {"x": REQUESTED[0], "y": REQUESTED[1], "z": 68.02, "z_estimated": True,
            "coordinate_space": "WORLD_YARDS", "instance_id": 2175, "map_id": 1409,
            "stop_distance": 6., "require_navmesh": True,
            "purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "location_source": "QUEST_ZONE_SWEEP"}


def _navigation():
    navmesh = _Navmesh()
    return NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))),
                             navmesh=navmesh), navmesh


def test_detour_float32_end_does_not_replan_every_command():
    nav, navmesh = _navigation()
    nav.start_skill_request("MOVE", _hop(), _state(60., -2250., 1.), "obs0", 1.)
    for step in range(1, 6):
        at = 1. + step*.2
        state = _state(60.+step, -2250.+step*.5, at)
        nav.observe(state, f"obs{step}", at)
        nav.command(state, f"obs{step}", at)
    assert navmesh.calls == 1


def test_fast_lane_arrival_ends_the_medium_tick_on_the_same_sample():
    nav, _ = _navigation()
    nav.start_skill_request("MOVE", _hop(), _state(66., -2248., 1.), "obs0", 1.)
    arrived = _state(69.84, -2247.04, 2.)
    fast = nav.observe(arrived, "fast", 2.)
    assert fast.terminal and fast.success
    # The medium tick re-reads the very sample the FAST lane consumed.
    medium = nav.observe(arrived, "medium", 2.)
    assert medium.terminal and medium.success
    assert medium.reason == "reach_arrival_verified"
    assert nav.command(arrived, "medium", 2.) == ()


def test_terminal_verdict_is_cleared_by_a_new_start():
    controller = MovementController()
    destination = {"x": 10., "y": 0., "coordinate_space": "WORLD_YARDS", "stop_distance": 2.}
    controller.start(destination, _state(0., 0., 1., 0.), "a", 1.)
    assert controller.observe(_state(9.5, 0., 2., 0.), "b", 2.).terminal
    assert controller.observe(_state(9.5, 0., 2., 0.), "c", 2.).terminal
    controller.start({**destination, "x": 30.}, _state(9.5, 0., 2., 0.), "d", 2.)
    later = controller.observe(_state(9.5, 0., 2., 0.), "e", 2.)
    assert not later.terminal


def _markers(name):
    rgb = np.asarray(Image.open(FIXTURES / name).convert("RGB"))
    return detect_floor_markers(rgb, (84.32, 84.68), 78.01)


def test_cocoon_dot_keeps_its_arrow_with_an_outline_row_and_when_dim():
    for name in ("cocoon_below_outline_1600x829.png", "cocoon_below_dim_1600x829.png"):
        markers = _markers(name)
        assert [(m["colour"], m["floor"]) for m in markers] == [("YELLOW", "BELOW")], name


def test_bright_arrow_is_not_also_a_grey_dot():
    markers = _markers("pit_grey_below_1600x829.png")
    assert [m["floor"] for m in markers] == ["BELOW"] * 4
