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


class _VanishingPlanner(_Planner):
    """First plan succeeds, every replan returns an empty navmesh route."""
    def __init__(self):
        self.calls = 0

    def plan(self, request, state, now, danger_map=None):
        self.calls += 1
        if self.calls == 1:
            return super().plan(request, state, now, danger_map)
        return GlobalRoute("route:empty", (), (), 0., 0., now, now+60.)


def test_replan_that_loses_the_navmesh_route_fails_closed_without_keyerror():
    # Issue #83: local_plan's replan branch called start({}) -> KeyError 'x'.
    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))))
    nav._global_planner = _VanishingPlanner()
    nav.start_skill_request("MOVE", {"x": -212.8, "y": -2512., "coordinate_space": "WORLD_YARDS",
                                     "instance_id": 2175, "map_id": 1409, "stop_distance": 4.,
                                     "require_navmesh": True}, _state(1.), "obs0", 1.)
    assert nav._route_failure_reason is None
    assert nav.local_plan(_state(1.1), now=1.1, observation_id="o") is None
    assert nav._route_failure_reason == "required_navmesh_route_unavailable"
    commands = nav.command(_state(1.2), "obs2", 1.2)
    assert not any(command.binding == "MOVEFORWARD" for command in commands)


def test_context_reset_clears_floor_and_sweep_state_but_goal_change_keeps_floor():
    # Issue #84: reset() left the Z resolver's player floor and the cave
    # sweep/lower-layer caches in place across session/death/phase changes.
    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))))
    nav._z.seed_player(1, 10., 20., 50., 1.)
    nav._zone_sweeps = {"k": {"done": True}}
    nav._last_sweep_key = "k"
    nav._lower_layer_cache = {"k": 1}
    nav.reset(keep_floor=True)
    assert nav._z.player is not None and nav._z.player.z == 50.
    assert "_zone_sweeps" not in nav.__dict__ and "_lower_layer_cache" not in nav.__dict__
    nav.reset()
    assert nav._z.player is None
    assert "_last_sweep_key" not in nav.__dict__


def _floor_state(t, z):
    return {**_state(t), "player_world_position": {
        "x": 10., "y": 20., "z": z, "z_source": "NAVMESH_SURFACE", "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS", "sample_time": t},
        "target": {"guid": "Creature-0-1-2-3-4-5", "dead": True, "sample_time": t,
                   "world_position": {"x": 10., "y": 20., "z": 0., "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"}}}


def test_entity_approach_does_not_arrive_one_floor_away():
    """Issue #101: same X/Y but 50 yd above the corpse reported ARRIVED."""
    from wowbot.agent.movement_controller import MovementPhase
    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))))
    destination = nav.move_to_entity(_floor_state(1., 50.), "Creature-0-1-2-3-4-5", "o1", 1.,
                                     stop_distance=3.5, allow_dead=True)
    assert destination["layer_z"] == 0.
    assessment = nav._movement.observe(_floor_state(1.1, 50.), "o2", 1.1, commanded=True)
    assert assessment.phase != MovementPhase.ARRIVED
    on_floor = nav._movement.observe(_floor_state(1.2, .5), "o3", 1.2, commanded=True)
    assert on_floor.phase == MovementPhase.ARRIVED


def test_entity_approach_never_invents_a_zero_height():
    nav = NavigationService(BindingsCache(binding_file(Path(tempfile.mkdtemp()))))
    state = _floor_state(1., 50.)
    state["target"]["world_position"]["z_known"] = False
    destination = nav.move_to_entity(state, "Creature-0-1-2-3-4-5", "o1", 1.,
                                     stop_distance=3.5, allow_dead=True)
    assert "z" not in destination and "layer_z" not in destination
    assert destination["z_known"] is False
