"""M5-D cost-aware danger avoidance and route-waypoint execution."""

from wowbot.navigation import ArrivalEnvelope, NavigationRequest, NavigationService
from wowbot.navigation.danger import DangerMap
from wowbot.navigation.global_planner import GlobalPlanner


def _request(*, avoid=True, allow=False):
    return NavigationRequest(
        "route:danger", "obs:danger", "MOVE_TO_LOCATION",
        {"x": 20., "y": 0., "coordinate_space": "WORLD_YARDS", "instance_id": 1},
        arrival=ArrivalEnvelope(radius=1.), avoid_combat=avoid, allow_combat=allow,
    )


def _state(x=0., y=0., *, hostile=True):
    return {
        "map_id": 1,
        "player_world_position": {"x": x, "y": y, "instance_id": 1},
        "orientation": 0.,
        "movement": {"moving": False, "speed": 0.},
        "nearby_attackable_entities": ([{
            "guid": "hostile-1", "attackable": True,
            "world_position": {"x": 10., "y": 0., "instance_id": 1},
            "aggro_radius": 4., "confidence": 1.,
        }] if hostile else []),
    }


def test_global_planner_selects_a_lower_danger_detour_when_combat_is_avoided():
    danger = DangerMap()
    danger.add(
        danger_id="hostile-1", kind="HOSTILE_AGGRO", x=10., y=0., radius=4.,
        cost=12., confidence=1., now=1., ttl=10., source="TEST",
        entity_id="hostile-1",
    )
    planner = GlobalPlanner()

    safe = planner.plan(_request(), _state(hostile=False), 1., danger_map=danger)
    direct = planner.plan(_request(avoid=False), _state(hostile=False), 1., danger_map=danger)

    assert len(direct.anchors) == 2
    assert len(safe.anchors) == 3
    assert safe.anchors[1]["danger_detour"] == "hostile-1"
    assert safe.regions[0]["danger_adapted"] is True
    assert danger.route_cost(safe.anchors, 1.) < danger.route_cost(direct.anchors, 1.)


def test_navigation_service_executes_detour_waypoint_before_final_arrival():
    service = NavigationService()
    service.start_request(_request(), _state(), 1.)
    snapshot = service.snapshot(1.)
    anchors = snapshot["global_route"]["anchors"]

    assert len(anchors) == 3
    assert snapshot["route_waypoint_index"] == 1
    assert snapshot["movement"]["destination"]["route_waypoint_final"] is False
    detour = anchors[1]

    assessment = service.observe(_state(detour["x"], detour["y"]), "at-detour", 2.)

    assert not assessment.terminal
    assert assessment.reason == "route_waypoint_advanced"
    advanced = service.snapshot(2.)
    assert advanced["route_waypoint_index"] == 2
    assert advanced["movement"]["destination"]["route_waypoint_final"] is True
    assert advanced["movement"]["destination"]["x"] == 20.
    assert advanced["movement"]["destination"]["arrival_radius"] == 1.


def test_allow_combat_keeps_direct_route_even_when_danger_exists():
    danger = DangerMap()
    danger.add(
        danger_id="hostile-1", kind="HOSTILE_AGGRO", x=10., y=0., radius=4.,
        cost=12., confidence=1., now=1., ttl=10., source="TEST",
        entity_id="hostile-1",
    )
    route = GlobalPlanner().plan(
        _request(avoid=False, allow=True), _state(hostile=False), 1., danger_map=danger)
    assert len(route.anchors) == 2
    assert route.regions[0]["danger_adapted"] is False


def test_unchanged_hostile_refresh_does_not_churn_danger_revision():
    danger = DangerMap()
    danger.observe_hostiles(_state(), 1.)
    revision = danger.revision
    danger.observe_hostiles(_state(), 2.)
    assert danger.revision == revision


def test_supported_route_failure_memory_rebuilds_an_alternate_corridor():
    service = NavigationService()
    request = _request(avoid=False)
    service.start_request(request, _state(hostile=False), 1.)
    original = service.snapshot(1.)["global_route"]
    blocked = _state(8., 0., hostile=False)

    assert service.mark_current_route_danger(
        blocked, 2., correlation_id="path-loop:1")
    assert service.rebuild_current_corridor(blocked, "rebuild:1", 2.)
    rebuilt = service.snapshot(2.)

    assert rebuilt["global_route"]["route_id"] != original["route_id"]
    assert len(rebuilt["global_route"]["anchors"]) == 3
    assert rebuilt["global_route"]["anchors"][1]["danger_detour"] == "navigation-failure:path-loop:1"
    assert rebuilt["path_corridor"]["route_id"] == rebuilt["global_route"]["route_id"]
