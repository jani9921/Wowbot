"""Stuck at an obstacle the mmap does not know (live 2026-10-02, shipwreck).

User: jump while running ("Space"), back off further than one step, and do
not run the same route into the same wreck again -- learn it and go around.
"""
import math

from wowbot.agent.executor import InputExecutor
from wowbot.agent.models import Command, Proposal
from wowbot.agent.movement_controller import MovementPhase, ReachMovementController
from wowbot.agent.skills import SkillRegistry
from wowbot.navigation import ArrivalEnvelope, NavigationRequest, NavigationService
from wowbot.navigation.danger import DangerMap
from wowbot.navigation.progress import ProgressPhase
from wowbot.navigation.stuck_resolver import StuckResolutionState, StuckResolver
from wowbot.agent.bindings import BindingsCache
from test_agent_core import Backend, binding_file, state

DESTINATION = {"x": 0., "y": 100., "instance_id": 2175, "coordinate_space": "WORLD_YARDS",
               "stop_distance": 4.}


def _wall_state(at, *, moving=True, x=0., y=0.):
    return state(at, orientation=math.pi/2, movement={"speed": 7. if moving else 0., "moving": moving},
                 player_world_position={"x": x, "y": y, "instance_id": 2175,
                                        "coordinate_space": "WORLD_YARDS", "sample_time": at})


def test_running_into_a_wall_tries_one_running_jump_before_stuck():
    controller = ReachMovementController()
    controller.start(DESTINATION, _wall_state(1.), "o0", 1.)
    controller.command(_wall_state(1.), "o0", 1.)
    jumps, result = [], None
    for index in range(1, 200):
        at = 1. + index/30.
        result = controller.observe(_wall_state(at), f"o{index}", at)
        if result.terminal:
            break
        jumps += [c for c in controller.command(_wall_state(at), f"o{index}", at)
                  if "JUMP" in c.simultaneous]
    assert len(jumps) == 1
    assert jumps[0].binding == "MOVEFORWARD" and jumps[0].duration <= .35
    # The jump did not help: the ordinary supported-stuck recovery follows.
    assert result.phase == MovementPhase.SUPPORTED_STUCK


def test_small_position_jitter_cannot_hide_a_four_second_wall_contact():
    controller = ReachMovementController()
    controller.start(DESTINATION, _wall_state(1.), "o0", 1.)
    controller.command(_wall_state(1.), "o0", 1.)
    result = None
    # Alternating 0.08 yd jitter periodically looks like per-frame target
    # progress, but no actual movement has occurred over the full window.
    for index in range(1, 220):
        at = 1. + index/30.
        sample = _wall_state(at, y=.08 if index % 2 else 0.)
        result = controller.observe(sample, f"o{index}", at)
        if result.terminal:
            break
        controller.command(sample, f"o{index}", at)
    assert result is not None and result.phase == MovementPhase.SUPPORTED_STUCK
    assert result.reason == "supported_stuck"
    assert at < 6.
    assert "POSITION_PLATEAU" in controller.snapshot()["stuck_evidence_sources"]
    # The FAST lane may receive another fresh, jittering position before the
    # medium skill tick consumes the terminal result. It must not re-arm W.
    fresh = _wall_state(at + .1, y=.16)
    repeated = controller.observe(fresh, "after-stuck", at + .1)
    assert repeated.terminal and repeated.reason == "supported_stuck"
    assert controller.command(fresh, "after-stuck", at + .1) == ()


def test_real_translation_and_turn_only_do_not_confirm_wall_contact():
    moving = ReachMovementController()
    moving.start(DESTINATION, _wall_state(1.), "o0", 1.)
    moving.command(_wall_state(1.), "o0", 1.)
    for index in range(1, 180):
        at = 1. + index/30.
        sample = _wall_state(at, y=.45 * (at-1.))
        result = moving.observe(sample, f"o{index}", at)
        assert result.phase != MovementPhase.SUPPORTED_STUCK
        moving.command(sample, f"o{index}", at)

    turning = ReachMovementController()
    destination = {**DESTINATION, "x": 100., "y": 0.}
    initial = _wall_state(1.)
    turning.start(destination, initial, "t0", 1.)
    # A turn-only command clears the uninterrupted forward window.
    turning.forward_started_at = 1.
    turn = turning.command(initial, "t0", 1.)[0]
    assert turn.binding in {"TURNLEFT", "TURNRIGHT"}
    assert turning.forward_started_at is None


def test_a_fresh_unsampled_step_cancels_the_wall_plateau():
    controller = ReachMovementController()
    controller.start(DESTINATION, _wall_state(1.), "o0", 1.)
    controller.command(_wall_state(1.), "o0", 1.)
    for index in range(1, 120):
        at = 1. + index/30.
        sample = _wall_state(at, y=.08 if index % 2 else 0.)
        result = controller.observe(sample, f"o{index}", at)
        assert not result.terminal
        controller.command(sample, f"o{index}", at)
    # The next fresh point arrives before the downsampled evidence window is
    # due to append, but it proves the character has broken free.
    freed = _wall_state(5., y=1.)
    assert controller.observe(freed, "freed", 5.).phase != MovementPhase.SUPPORTED_STUCK


def test_jump_rides_a_forward_lease_as_a_transient_key(tmp_path):
    backend = Backend()
    executor = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    executor.execute_movement((Command("BIND", "MOVEFORWARD", .08, simultaneous=("JUMP",)),))
    assert ("W", True) in backend.calls and ("SPACE", True) in backend.calls
    executor.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
    assert ("SPACE", False) in backend.calls and ("W", False) not in backend.calls
    executor.stop_movement()
    for invalid in (Command("BIND", "TURNLEFT", .08, simultaneous=("JUMP",)),
                    Command("BIND", "MOVEFORWARD", .5, simultaneous=("JUMP",))):
        try:
            executor.execute_movement((invalid,))
        except Exception as error:  # noqa: BLE001 -- ExecutionError
            assert "movement lease" in str(error)
        else:
            raise AssertionError(f"accepted {invalid}")


def test_recover_backs_off_about_a_second_in_capped_steps():
    registry = SkillRegistry()
    world = type("World", (), {"state": {}})()
    backward = registry.commands(Proposal.make("RECOVER", "r", {"recovery_step": "BACKWARD"}), world)
    assert [c.binding for c in backward] == ["MOVEBACKWARD"] * 3
    assert all(c.duration <= .35 for c in backward) and sum(c.duration for c in backward) >= .85
    jump = registry.commands(Proposal.make("RECOVER", "r", {"recovery_step": "JUMP_FORWARD"}), world)
    assert jump[0].simultaneous == ("JUMP",) and jump[1].binding == "MOVEFORWARD"


def _stuck_again(resolver, at, position):
    resolver.begin(f"move:{at}", at, position=position)
    return resolver.observe_progress(ProgressPhase.HARD_STUCK, at + .5)


def test_repeated_stuck_at_the_same_spot_continues_the_ladder():
    resolver = StuckResolver()
    first = _stuck_again(resolver, 1., (0., 0.))
    assert first.action == "BACKWARD"
    # Backing off always moves the character: that is reported as success...
    assert resolver.report_step_result(success=True, now=3.).reason == "STUCK_RECOVERED"
    # ...but running the same route into the same wreck must not restart it.
    second = _stuck_again(resolver, 10., (1.5, 1.))
    assert second.state is StuckResolutionState.MARK_DANGER
    # Elsewhere, or much later, a stuck is a new episode.
    assert _stuck_again(StuckResolver(), 20., (0., 0.)).action == "BACKWARD"
    resolver.report_step_result(success=True, now=11.)
    assert _stuck_again(resolver, 12., (30., 0.)).action == "BACKWARD"
    resolver.report_step_result(success=True, now=13.)
    late = 13. + StuckResolver.MEMORY_SECONDS + 1.
    assert _stuck_again(resolver, late, (30., 0.)).action == "BACKWARD"


def _service_request():
    return NavigationRequest(
        "route:wreck", "obs:wreck", "MOVE_TO_LOCATION",
        {"x": 20., "y": 0., "coordinate_space": "WORLD_YARDS", "instance_id": 1},
        arrival=ArrivalEnvelope(radius=1.))


def test_learned_obstacle_sits_ahead_of_the_character():
    service = NavigationService()
    service.start_request(_service_request(), {"player_world_position": {"x": 0., "y": 0., "instance_id": 1},
                                               "orientation": 0.}, 1.)
    blocked = {"player_world_position": {"x": 8., "y": 0., "instance_id": 1}, "orientation": 0.}
    assert service.mark_current_route_danger(blocked, 2., correlation_id="wreck")
    entry = service._danger.active_entries(2.)[0]
    assert (entry.x, entry.y, entry.radius) == (10., 0., 3.)


def test_detour_points_must_land_on_the_navmesh():
    danger = DangerMap()
    danger.add(danger_id="wreck", kind="NAVIGATION_FAILURE", x=10., y=0., radius=3.,
               cost=12., confidence=.9, now=1., ttl=90., source="SUPPORTED_STUCK")
    route = ({"x": 0., "y": 0.}, {"x": 20., "y": 0.})
    # Left side is water (y > 0): only the right side is walkable.
    right_only = danger.avoidance_anchors(route, 1., walkable=lambda p: p["y"] < 0)
    assert [p.get("detour_side") for p in right_only] == [None, "RIGHT", None]
    # Nothing walkable within 5 yd: the detour widens before giving up.
    wide = danger.avoidance_anchors(route, 1., walkable=lambda p: abs(p["y"]) > 6)
    assert abs(wide[1]["y"]) > 6
    # Never walkable: no detour into a wall.
    assert danger.avoidance_anchors(route, 1., walkable=lambda p: False) == route


class _FlatNavmesh:
    """Everything walkable; projection returns a new dict like the real mmap."""

    last_surface_projection = {"contained_candidates": 1}

    def project_position(self, instance_id, point, *, z_hint=None):
        return {"x": float(point["x"]), "y": float(point["y"]), "z": 5., "instance_id": instance_id,
                "coordinate_space": "WORLD_YARDS", "source": "TRINITYCORE_MMAP_SURFACE",
                "z_source": "NAVMESH_SURFACE"}

    def find_path(self, instance_id, start, end):
        from wowbot.navigation.mmap_navmesh import NavMeshPath
        return NavMeshPath(anchors=({"x": start["x"], "y": start["y"], "z": 5.},
                                    {"x": end["x"], "y": end["y"], "z": 5.}),
                           polygon_count=1, tile_count=1, cost=1.)

    def close(self):
        pass


def test_navmesh_surface_projection_keeps_the_measurement_time():
    service = NavigationService(navmesh=_FlatNavmesh())
    player = {"x": 0., "y": 0., "instance_id": 1, "coordinate_space": "WORLD_YARDS", "sample_time": 7.5}
    service.start_request(_service_request(), {"player_world_position": player, "orientation": 0.}, 1.)
    for _ in range(2):   # fresh projection, then the cached one
        projected = service._state_with_navmesh_surface({"player_world_position": dict(player)})
        assert projected["player_world_position"]["sample_time"] == 7.5
        assert projected["player_world_position"]["source"] == "TRINITYCORE_MMAP_SURFACE"
