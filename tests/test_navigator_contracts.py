import math

from wowbot.navigation.contracts import ArrivalEnvelope, GlobalRoute, NavigationRequest
from wowbot.navigation.global_planner import GlobalNavigator, GlobalPlanner
from wowbot.navigation.local_planner import LocalNavigator, LocalPlanner


def _request():
    return NavigationRequest("r", "c", "MOVE_TO_LOCATION", {"x": 10., "y": 0., "map_id": 1},
                             arrival=ArrivalEnvelope(radius=1.0))


def test_global_navigator_is_the_compatible_planner_authority():
    assert GlobalPlanner is GlobalNavigator
    navigator = GlobalNavigator()
    route = navigator.resolve_global_route(
        _request(), {"position": {"x": 0., "y": 0.}, "map_id": 1}, 1.0)
    assert navigator.choose_waypoint(route, 99) == {"x": 10., "y": 0.}
    assert navigator.advance_waypoint(route, 0, {"x": 0., "y": 0.}) == 1
    assert not navigator.detect_map_context_change(route, {"map_id": 1})
    assert navigator.detect_map_context_change(route, {"map_id": 2})
    assert not navigator.replan_if_required(route, _request(), {"map_id": 1}, 2.0)


def test_local_navigator_is_the_compatible_local_planner_authority():
    assert LocalPlanner is LocalNavigator
    navigator = LocalNavigator()
    plan = navigator.compute_local_intent(
        {"position": {"x": 0., "y": 0.}}, None,
        destination={"x": 3., "y": 4.})
    assert plan.expected_progress_vector == {"x": .6, "y": .8}
    assert math.isclose(navigator.correct_heading(0., math.pi/2), math.pi/2)
    assert navigator.correct_heading(0., .01, deadzone=.04) == 0.
    assert navigator.stop_at_range(2., 3.) is True
    assert navigator.stop_at_range(None, 3.) is False


def test_local_obstacle_avoidance_only_uses_confirmed_traversability():
    navigator = LocalNavigator()
    state = {"local_traversability": {
        "schema": "WORLD3D_TRAVERSABILITY_V5",
        "sectors": [
            {"sector": "CENTER", "state": "BLOCKED", "obstacle_lifecycle": "CONFIRMED",
             "obstacle_confidence": .9, "traversability_score": .0},
            {"sector": "CENTER_LEFT", "state": "OPEN", "obstacle_lifecycle": "TENTATIVE",
             "obstacle_confidence": .1, "traversability_score": .8},
            {"sector": "CENTER_RIGHT", "state": "OPEN", "obstacle_lifecycle": "TENTATIVE",
             "obstacle_confidence": .1, "traversability_score": .4},
        ]}}
    assert navigator.avoid_immediate_obstacle(state) == "LEFT"
