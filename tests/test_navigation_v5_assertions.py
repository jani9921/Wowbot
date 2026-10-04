"""Regression assertions for the V5 navigation ownership and recovery rules."""
from wowbot.navigation.contracts import NavigationRequest
from wowbot.navigation.global_planner import GlobalPlanner
from wowbot.navigation.progress import ProgressPhase
from wowbot.navigation.stuck_resolver import StuckResolutionState, StuckResolver


def test_one_transient_local_obstacle_does_not_force_a_global_replan():
    planner = GlobalPlanner()
    request = NavigationRequest("r", "c", "MOVE_TO_LOCATION", {"x": 8., "y": 0.})
    state = {"position": {"x": 0., "y": 0.}, "map_id": 1,
             "local_traversability": {"schema": "WORLD3D_TRAVERSABILITY_V5", "sectors": [
                 {"sector": "CENTER", "state": "UNCERTAIN", "obstacle_lifecycle": "SUSPECTED"},
             ]}}
    route = planner.plan(request, state, 1.)
    assert not planner.needs_replan(route, request, state, 1.1)


def test_dynamic_block_uses_wait_then_bypass_without_global_replan():
    resolver = StuckResolver()
    first = resolver.begin("dynamic:1", 1., stuck_kind="DYNAMIC_BLOCK")
    assert first.state is StuckResolutionState.STOP_AND_OBSERVE
    next_step = resolver.observe_progress(ProgressPhase.HARD_STUCK, 2.)
    assert next_step.state is StuckResolutionState.STRAFE
    assert next_step.replan_scope is None


def test_path_loop_is_the_only_typed_ladder_that_escalates_to_global_replan():
    resolver = StuckResolver()
    resolver.begin("loop:1", 1., stuck_kind="PATH_LOOP")
    assert resolver.observe_progress(ProgressPhase.HARD_STUCK, 2.).action == "MARK_DANGER"
    assert resolver.report_step_result(success=False, now=3.).action == "REBUILD_CORRIDOR"
    assert resolver.report_step_result(success=False, now=4.).replan_scope == "GLOBAL"
