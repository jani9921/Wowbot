"""Live 2026-10-04 00:41: the MOVE to Captain Garrick's minimap dot never
moved.  Detour's first corner lay 1.1 yd from the player; every replan (the
danger map changed with nearby mobs) restarted the route at that corner, it
counted as arrived at once, and no movement command was ever issued."""
from pathlib import Path
import tempfile

from test_agent_core import binding_file

from wowbot.agent.bindings import BindingsCache
from wowbot.navigation.contracts import GlobalRoute
from wowbot.navigation.service import NavigationService


def _anchor(x, y):
    return {"x": x, "y": y, "z": 28., "instance_id": 2175, "coordinate_space": "WORLD_YARDS",
            "source": "TRINITYCORE_MMAP"}


class _Planner:
    def plan(self, request, state, now, danger_map=None):
        position = state["player_world_position"]
        return GlobalRoute("route:test", (_anchor(position["x"], position["y"]),
                                          _anchor(position["x"]+1., position["y"]+.5),
                                          _anchor(-212.8, -2512.)), (), 39., 1., now, now+60.)

    def needs_replan(self, *args, **kwargs):
        return True          # as live: the danger map revision kept changing


def _state(t):
    return {"session_id": "s", "map_id": 1409, "orientation": .8, "monotonic_time": t,
            "player_world_position": {"x": -241.52, "y": -2538.1, "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS", "sample_time": t},
            "movement": {"speed": 0., "moving": False}}


def test_replanned_route_does_not_restart_at_the_corner_under_the_player():
    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))))
    nav._global_planner = _Planner()
    nav.start_skill_request("MOVE", {"x": -212.8, "y": -2512., "coordinate_space": "WORLD_YARDS",
                                     "instance_id": 2175, "map_id": 1409, "stop_distance": 4.,
                                     "require_navmesh": True}, _state(1.), "obs0", 1.)
    issued = []
    for step in range(1, 5):
        at = 1. + step * .1
        nav.observe(_state(at), f"obs{step}", at)
        issued += [command.binding for command in nav.command(_state(at), f"obs{step}", at)]
    assert nav._route_waypoint_index == 2
    assert "MOVEFORWARD" in issued
