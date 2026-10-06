"""Live 2026-10-06 (Hrun's pit): the player fell off the spiral (FALL_STARTED /
FALL_ENDED events).  The addon has no height, so the route projection kept
him on the upper layer; every replan started there and the next waypoint
(z 94.8) sat right above him -- he walked into the wall "in a straight line"
(user: it should plan again and go on)."""
from pathlib import Path
import tempfile

from test_agent_core import binding_file

from wowbot.agent.bindings import BindingsCache
from wowbot.navigation.mmap_navmesh import NavMeshPath
from wowbot.navigation.service import NavigationService

UPPER, LOWER = 79.3, 60.4


class _Navmesh:
    def __init__(self):
        self.starts = []

    def walkable_heights_at(self, instance_id, point, radius=2.5):
        # Beside the spiral (y < -2226) only the floor below remains.
        return [LOWER] if point["y"] < -2226. else [LOWER, UPPER]

    def find_path(self, instance_id, start, end):
        self.starts.append(start.get("z"))
        z = float(start.get("z") or UPPER)
        end_z = float(end.get("z", z))
        anchor = {"instance_id": instance_id, "coordinate_space": "WORLD_YARDS", "source": "TRINITYCORE_MMAP"}
        return NavMeshPath(({**anchor, "x": start["x"], "y": start["y"], "z": z},
                            {**anchor, "x": end["x"], "y": end["y"], "z": end_z}), 3, 1, 40.)


def _state(t, events=(), stamp=1000, y=-2224.8):
    return {"session_id": "s", "map_id": 1409, "orientation": 4., "monotonic_time": t, "timestamp": stamp,
            "events": list(events),
            "player_world_position": {"x": 80.4, "y": y, "z": None, "z_known": False,
                                      "instance_id": 2175, "coordinate_space": "WORLD_YARDS",
                                      "sample_time": t},
            "movement": {"speed": 7., "moving": True}}


def _fall(sequence, stamp=1000):
    return {"event_type": "FALL_ENDED", "sequence": sequence, "timestamp": stamp, "payload": {}}


def _navigation():
    navmesh = _Navmesh()
    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))), navmesh=navmesh)
    nav._player_layer = (2175, 80.4, -2224.8, UPPER, 1.)
    nav.start_skill_request("MOVE", {"x": 76.8, "y": -2264.0, "coordinate_space": "WORLD_YARDS",
                                     "instance_id": 2175, "map_id": 1409, "stop_distance": 15.,
                                     "require_navmesh": True}, _state(1.), "obs0", 1.)
    return nav, navmesh


def test_fall_moves_the_player_to_the_layer_below_and_replans():
    nav, navmesh = _navigation()
    assert navmesh.starts[-1] == UPPER
    nav.observe(_state(2., events=[_fall(4, stamp=900)], stamp=999), "obs1", 2.)   # baseline: an old fall
    result = nav.observe(_state(3., events=[_fall(4), _fall(5)], y=-2227.), "obs2", 3.)
    assert result.reason == "route_replanned_after_fall"
    assert navmesh.starts[-1] == LOWER and nav._player_layer[3] == LOWER
    again = nav.observe(_state(4., events=[_fall(5)]), "obs3", 4.)
    assert again.reason != "route_replanned_after_fall"


def test_a_stale_fall_in_the_first_snapshot_changes_nothing():
    nav, navmesh = _navigation()
    planned = len(navmesh.starts)
    result = nav.observe(_state(2., events=[_fall(5, stamp=900)], stamp=1000), "obs1", 2.)
    assert result.reason != "route_replanned_after_fall"
    assert len(navmesh.starts) == planned and nav._player_layer[3] == UPPER


def test_a_downward_sweep_hop_above_the_landing_is_passed():
    navmesh = _Navmesh()
    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))), navmesh=navmesh)
    nav._player_layer = (2175, 80.4, -2224.8, UPPER, 1.)
    nav.start_skill_request("MOVE", {"x": 81.6, "y": -2224.2, "z": 83.7, "z_estimated": True,
                                     "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                     "map_id": 1409, "stop_distance": 6., "require_navmesh": True,
                                     "sweep_direction": "DOWN", "location_source": "QUEST_ZONE_SWEEP"},
                            _state(1.), "obs0", 1.)
    passed = nav.observe(_state(3., events=[_fall(5)], y=-2227.), "obs1", 3.)
    assert passed.terminal and passed.success and passed.reason == "zone_sweep_hop_passed"


def test_after_a_fall_the_sweep_continues_below_not_with_the_hop_above():
    nav, _ = _navigation()
    hops = [{"x": 84.6, "y": -2235., "z": 91.7}, {"x": 81.6, "y": -2224.2, "z": 83.7},
            {"x": 70., "y": -2224., "z": 76.7}, {"x": 66.3, "y": -2236., "z": 68.0}]
    nav.__dict__["_zone_sweeps"] = {"k": {"hops": hops, "visited": {0}, "upward": False, "done": False}}
    nav._player_layer = (2175, 80.4, -2224.8, 74.9, 5.)          # landed below hop 1
    hop = nav.zone_sweep_next(_state(5.), {"x": 81., "y": -2242.}, "k")
    assert hop["sweep_hop"] == 2 and hop["sweep_direction"] == "DOWN"


def test_a_waypoint_on_another_layer_is_not_passed_in_2d():
    nav, _ = _navigation()
    route = nav._active_route
    from dataclasses import replace
    anchors = ({"x": 80.4, "y": -2224.8, "z": UPPER}, {"x": 81.0, "y": -2225.5, "z": LOWER - 20.},
               {"x": 76.8, "y": -2264.0, "z": UPPER})
    nav._active_route = replace(route, anchors=anchors)
    nav._route_waypoint_index = 1
    nav._z.seed_player(2175, 80.4, -2224.8, UPPER, 2.)
    assert not nav._intermediate_waypoint_passed(_state(2.))


def test_standing_over_the_destination_on_another_layer_ends_the_move():
    """Live 2026-10-06: 0.4 yd from the cocoon ledge in X/Y, 35 yd above it, turning for 35 s."""
    nav, _ = _navigation()
    nav._movement.destination.update({"x": 80.6, "y": -2224.6, "layer_z": LOWER, "route_waypoint_final": True})
    state = _state(5.)
    state["player_world_position"].update({"z": UPPER, "z_source": "NAVMESH_SURFACE"})
    from types import SimpleNamespace
    result = nav._destination_on_other_layer(state, SimpleNamespace(terminal=False))
    assert result.terminal and result.reason == "destination_on_other_layer"


def test_a_downward_hop_we_are_already_below_ends_without_a_fall_event():
    """Live 2026-10-06: off the spiral without a reported fall, the hop at 83 stayed the target."""
    navmesh = _Navmesh()
    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))), navmesh=navmesh)
    nav._player_layer = (2175, 80.4, -2224.8, UPPER, 1.)
    nav.start_skill_request("MOVE", {"x": 81.6, "y": -2224.2, "z": 83.7, "z_estimated": True,
                                     "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                     "map_id": 1409, "stop_distance": 6., "require_navmesh": True,
                                     "sweep_direction": "DOWN", "location_source": "QUEST_ZONE_SWEEP"},
                            _state(1.), "obs0", 1.)
    nav._z.seed_player(2175, 80.4, -2227., LOWER, 2.)
    passed = nav.observe(_state(3., y=-2227.), "obs1", 3.)
    assert passed.terminal and passed.success and passed.reason == "zone_sweep_hop_passed"
