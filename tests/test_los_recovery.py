from dataclasses import dataclass

from wowbot.navigation import (LosRecoveryPhase, LosRecoveryPlanner,
                               NavigationService)


def traversability(left: float, right: float) -> dict:
    return {
        "schema": "WORLD3D_TRAVERSABILITY_V5",
        "sectors": [
            {"sector": "CENTER_LEFT", "traversability_score": left,
             "state": "CLEAR", "obstacle_lifecycle": "ABSENT",
             "obstacle_confidence": 0.},
            {"sector": "CENTER_RIGHT", "traversability_score": right,
             "state": "CLEAR", "obstacle_lifecycle": "ABSENT",
             "obstacle_confidence": 0.},
        ],
    }


def test_los_lateral_probes_use_free_space_then_try_the_other_side():
    planner = LosRecoveryPlanner()
    state = {"local_traversability": traversability(.25, .9)}
    first = planner.plan(state, {"attempt": 0, "target_screen_x": .3})
    second = planner.plan(state, {"attempt": 1, "target_screen_x": .3})

    assert first.phase is LosRecoveryPhase.TRY_LATERAL_A
    assert first.action == "STRAFERIGHT"
    assert .30 <= first.duration <= .35
    assert second.phase is LosRecoveryPhase.TRY_LATERAL_B
    assert second.action == "STRAFELEFT"


def test_los_bearing_breaks_missing_geometry_tie_without_fixed_left_first():
    planner = LosRecoveryPlanner()
    assert planner.plan({}, {"attempt": 0, "target_screen_x": .8}).action == "STRAFERIGHT"
    assert planner.plan({}, {"attempt": 0, "target_screen_x": .2}).action == "STRAFELEFT"


def test_los_third_attempt_requires_geometry_backed_local_replan_and_terminates():
    planner = LosRecoveryPlanner()
    replan = planner.plan({}, {"attempt": 2, "target_screen_x": .5})
    exhausted = planner.plan({}, {"attempt": 3, "target_screen_x": .5})
    assert replan.phase is LosRecoveryPhase.LOCAL_REPLAN and replan.action is None
    assert exhausted.phase is LosRecoveryPhase.TARGET_UNREACHABLE and exhausted.action is None


@dataclass(frozen=True)
class Path:
    anchors: tuple
    tile_count: int = 2
    polygon_count: int = 7
    total_cost: float = 4.


class NavMesh:
    last_diagnostics = {"source": "test"}

    def __init__(self):
        self.calls = []

    def find_path(self, instance_id, start, destination):
        self.calls.append((instance_id, start, destination))
        return Path((
            {"x": start["x"], "y": start["y"], "z": start.get("z", 0.),
             "source": "TRINITYCORE_MMAP"},
            {"x": 4., "y": 3., "z": 0., "source": "TRINITYCORE_MMAP"},
            {"x": destination["x"], "y": destination["y"],
             "z": destination.get("z", 0.), "source": "TRINITYCORE_MMAP"},
        ))

    def close(self):
        pass


def live_target() -> dict:
    return {
        "monotonic_time": 2.,
        "player_world_position": {"x": 1., "y": 2., "z": 0.,
                                  "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS"},
        "target": {"guid": "mob-1", "attackable": True, "sample_time": 2.,
                   "screen_position": {"x": .7, "y": .5, "sample_time": 2.},
                   "world_position": {"x": 8., "y": 5., "z": 0.,
                                      "instance_id": 2175}},
    }


def test_navigation_service_uses_mmap_for_final_los_replan_without_second_authority():
    navmesh = NavMesh()
    service = NavigationService(navmesh=navmesh)
    destination = service.reposition_for_los(
        live_target(), "mob-1", "combat:los:3", 2., desired_range=4.5)
    snapshot = service.snapshot(2.)

    assert destination and destination["purpose"] == "LOS_REPOSITION"
    assert len(navmesh.calls) == 1 and navmesh.calls[0][0] == 2175
    assert snapshot["active_request"]["mode"] == "REPOSITION_FOR_LOS"
    assert snapshot["global_route"]["anchors"][1]["source"] == "TRINITYCORE_MMAP"
    assert snapshot["authority"] == "NavigationService"


def test_los_exhaustion_creates_temporary_danger_not_permanent_fact():
    service = NavigationService(navmesh=NavMesh())
    state = live_target()
    assert service.record_los_exhaustion("mob-1", state, 2.) is True
    current = service.snapshot(2.)["danger_map"]
    assert current[0]["kind"] == "LOS_OBSTACLE"
    assert current[0]["expires_at"] == 32.
    assert service.snapshot(33.)["danger_map"] == []
