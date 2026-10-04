import pytest

from wowbot.navigation.contracts import ArrivalEnvelope, NavigationRequest
from wowbot.navigation.corridor import PathCorridorBuilder
from wowbot.navigation.global_planner import GlobalPlanner
from wowbot.navigation.local_planner import LocalPlanner
from wowbot.navigation.service import NavigationService


def test_navigation_request_validates_mode_safety_and_timeout():
    request = NavigationRequest("request:1", "obs:1", "MOVE_TO_LOCATION", {"x": 1., "y": 2.},
                                arrival=ArrivalEnvelope(radius=2.), avoid_combat=True, timeout=10.)
    assert request.mode == "MOVE_TO_LOCATION"
    with pytest.raises(ValueError, match="unsupported"):
        NavigationRequest("r", "o", "TELEPORT", {})
    with pytest.raises(ValueError, match="cannot both"):
        NavigationRequest("r", "o", "MOVE_TO_LOCATION", {}, avoid_combat=True, allow_combat=True)


def test_navigation_service_keeps_typed_request_without_creating_another_input_owner():
    service = NavigationService()
    request = NavigationRequest("request:1", "obs:1", "MOVE_TO_LOCATION", {"x": 1., "y": 2.},
                                arrival=ArrivalEnvelope(radius=2.))
    service.start_request(request, {"position": {"x": 0., "y": 0.}}, 1.)
    snapshot = service.snapshot(1.)
    assert snapshot["authority"] == "NavigationService"
    assert snapshot["active_request"] == {"request_id": "request:1", "mode": "MOVE_TO_LOCATION",
                                          "correlation_id": "obs:1"}
    assert snapshot["global_route"]["anchors"][-1] == {"x": 1.0, "y": 2.0}
    assert snapshot["path_corridor"]["route_id"] == snapshot["global_route"]["route_id"]
    assert snapshot["local_motion_plan"]["motion_mode"] == "FOLLOW_CORRIDOR"


def test_canonical_move_skill_enters_the_typed_navigation_boundary_once():
    service = NavigationService()
    service.start_skill_request("MOVE", {"x": 1., "y": 2., "map_id": 7},
                                {"position": {"x": 0., "y": 0.}, "map_id": 7}, "obs:move", 1.)
    assert service.snapshot(1.)["active_request"] == {
        "request_id": "navigation:MOVE:obs:move", "mode": "MOVE_TO_LOCATION", "correlation_id": "obs:move",
    }


def test_global_route_replans_only_on_bounded_replan_events():
    planner = GlobalPlanner()
    request = NavigationRequest("request:route", "obs:route", "MOVE_TO_LOCATION", {"x": 10., "y": 4.})
    state = {"position": {"x": 0., "y": 0.}, "map_id": 1}
    route = planner.plan(request, state, 1.)
    assert len(route.anchors) == 2
    assert not planner.needs_replan(route, request, state, 2.)
    assert planner.needs_replan(route, request, state, 2., corridor_invalid=True)
    assert planner.needs_replan(route, request, state, 2., local_failures=3)
    assert planner.needs_replan(route, request, {**state, "map_id": 2}, 2.)


def test_local_planner_consumes_confirmed_traversability_without_semantic_labels():
    request = NavigationRequest("request:local", "obs:local", "MOVE_TO_LOCATION", {"x": 10., "y": 0.})
    state = {"position": {"x": 0., "y": 0.}}
    route = GlobalPlanner().plan(request, state, 1.)
    corridor = PathCorridorBuilder().build(route)
    local = {"schema": "WORLD3D_TRAVERSABILITY_V5", "sectors": [
        {"sector": "CENTER", "state": "BLOCKED", "obstacle_lifecycle": "CONFIRMED",
         "obstacle_confidence": .8, "traversability_score": .1, "evidence": ["frame:7"]},
        {"sector": "CENTER_LEFT", "state": "TRAVERSABLE", "obstacle_lifecycle": "CONFIRMED",
         "obstacle_confidence": .1, "traversability_score": .8},
        {"sector": "CENTER_RIGHT", "state": "TRAVERSABLE", "obstacle_lifecycle": "CONFIRMED",
         "obstacle_confidence": .1, "traversability_score": .3},
    ]}
    plan = LocalPlanner().plan({**state, "local_traversability": local}, corridor, destination=request.destination)
    assert plan.motion_mode == "FOLLOW_CORRIDOR"
    assert plan.local_waypoint["local_bypass_preference"] == "LEFT"
    assert plan.local_waypoint["traversability_evidence"] == ("frame:7",)
