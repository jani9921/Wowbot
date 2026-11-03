"""Live 2026-10-27 16:10:27-16:11:08 (Obsidian Citadel): a MOVE planned while
the own height was unknown followed a courtyard route (z ~216) while the
player stood on the wall top (own movement packets z ~260).  It ran back and
forth 1-4 yd around an intermediate waypoint for 40 s and never re-planned
to the usable South Siege Arbalest on the same wall."""
import tempfile
from pathlib import Path
from types import SimpleNamespace

from wowbot.agent.bindings import BindingsCache
from wowbot.navigation.service import NavigationService

from test_agent_core import binding_file

WALL, COURTYARD = 260.3, 216.66


def _state(t, *, z=WALL, source="PACKET_CLIENT_MOVEMENT", x=2250.1, falling=False):
    return {"session_id": "s", "map_id": 2022, "orientation": 2.4, "monotonic_time": t,
            "player_world_position": {"x": x, "y": 2509.6, "z": z, "z_known": z is not None,
                                      "z_observed": z is not None, "source": source, "z_source": source,
                                      "instance_id": 2444, "coordinate_space": "WORLD_YARDS", "sample_time": t},
            "movement": {"speed": 7., "moving": True, "falling": falling}}


def _navigation():
    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))), navmesh=None)
    nav._movement.destination = {"x": 2249.3, "y": 2510.3, "z": COURTYARD, "layer_z": COURTYARD,
                                 "coordinate_space": "WORLD_YARDS", "route_waypoint_final": False,
                                 "route_waypoint_index": 1}
    return nav


RUNNING = SimpleNamespace(terminal=False)


def test_a_route_on_the_floor_below_the_observed_height_fails_after_two_seconds():
    nav = _navigation()
    assert nav._route_on_observed_other_layer(_state(10.), RUNNING, 10.) is None
    assert nav._route_on_observed_other_layer(_state(11., z=None, source="C_MAP_PLAYER_WORLD_POS"),
                                              RUNNING, 11.) is None          # z gaps keep the last packet z
    result = nav._route_on_observed_other_layer(_state(12.2), RUNNING, 12.2)
    assert result.terminal and not result.success and result.reason == "route_on_observed_other_layer"


def test_same_floor_falls_and_far_waypoints_do_not_fail():
    nav = _navigation()
    for t in (10., 12., 14.):
        assert nav._route_on_observed_other_layer(_state(t, z=COURTYARD+3.), RUNNING, t) is None
    nav = _navigation()
    for t in (10., 12., 14.):
        assert nav._route_on_observed_other_layer(_state(t, falling=True), RUNNING, t) is None
    nav = _navigation()
    for t in (10., 12., 14.):
        assert nav._route_on_observed_other_layer(_state(t, x=2270.), RUNNING, t) is None
    nav = _navigation()
    nav._route_on_observed_other_layer(_state(10.), RUNNING, 10.)
    assert nav._route_on_observed_other_layer(_state(13., z=None, source="C_MAP_PLAYER_WORLD_POS"),
                                              RUNNING, 13.) is None          # the packet height went stale


def test_a_layer_probe_stops_at_the_first_contradicting_server_height():
    nav = _navigation()
    nav._layer_probe = True
    result = nav._route_on_observed_other_layer(_state(10.), RUNNING, 10.)
    assert result.terminal and result.reason == "route_on_observed_other_layer"
