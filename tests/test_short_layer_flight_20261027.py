"""A flight 46 yd up must not become a 10 yd walk under its landing."""
from copy import deepcopy

import pytest

from wowbot.navigation.contracts import NavigationRequest
from wowbot.navigation.flight_route import FlightPlan
from wowbot.navigation.global_planner import GlobalNavigator
from wowbot.navigation.mmap_navmesh import NavMeshPath
from wowbot.navigation.service import NavigationService


class BridgeGeometry:
    """Two disconnected surfaces, like the recorded East Arbalest approach."""

    def __init__(self, *, covered=False):
        self.covered = covered
        self.walks = 0

    def supports(self, instance_id):
        return instance_id == 2444

    def terrain_height(self, instance_id, x, y):
        return 200., False

    def vmap_surfaces_at(self, instance_id, point):
        return [280.] if self.covered else [247.35]

    def project_position(self, instance_id, point, z_hint=None):
        z = point.get("z", z_hint)
        return {**point, "z": 247.35 if z is not None and z > 230. else 200.}

    def walkable_points_near(self, instance_id, point, radius):
        return []

    def find_path(self, instance_id, start, end):
        self.walks += 1
        # Detour can offer a route below the disconnected destination layer.
        anchors = ({**start, "z": 200.}, {**end, "z": 201.08})
        return NavMeshPath(anchors, 3, 1, 17.94)


def state(*, z=199.90, observed=True):
    return {"session_id": "test:short-flight", "monotonic_time": 10., "orientation": 0.,
            "is_mounted": True, "is_in_combat": False,
            "movement": {"flying": False, "falling": False, "indoors": False},
            "player_world_position": {"x": 2127.78, "y": 2311.54, "z": z, "z_known": True,
                "z_observed": observed, "sample_time": 10., "instance_id": 2444,
                "coordinate_space": "WORLD_YARDS"}}


def target(**changes):
    return {"x": 2131.49, "y": 2301.36, "z": 245.64, "z_known": True,
            "instance_id": 2444, "coordinate_space": "WORLD_YARDS",
            "flight": True, "flight_style": "SKYRIDING", "require_navmesh": True,
            "stop_distance": 1.2, "face_on_arrival": True, **changes}


def request(**changes):
    return NavigationRequest("short-flight", "same-action", "MOVE_TO_LOCATION", target(**changes))


def test_global_planner_retains_the_short_vertical_flight_and_upper_landing():
    geometry = BridgeGeometry()
    route = GlobalNavigator(navmesh=geometry).plan(request(), state(), 10.)
    assert route.regions[0]["route_source"] == "FLIGHT_PLAN"
    assert route.regions[0]["flight_plan_status"] == "planned"
    plan = FlightPlan.from_dict(route.anchors[-1]["flight_plan"])
    assert plan.distance < 40. and plan.landing["z"] == pytest.approx(247.35)
    assert geometry.walks == 0


def test_projected_surface_does_not_hide_the_preserved_server_height():
    payload = state(z=240., observed=False)
    payload["player_world_position"]["observed_z"] = 199.90
    route = GlobalNavigator(navmesh=BridgeGeometry()).plan(request(), payload, 10.)
    plan = FlightPlan.from_dict(route.anchors[-1]["flight_plan"])
    assert plan.start["z"] == 199.90


@pytest.mark.parametrize("z,known,estimated", [(201., True, False), (245.64, False, False),
                                              (245.64, True, True)])
def test_same_level_unknown_and_estimated_height_keep_ordinary_short_walks(z, known, estimated):
    geometry = BridgeGeometry()
    route = GlobalNavigator(navmesh=geometry).plan(
        request(z=z, z_known=known, z_estimated=estimated), state(), 10.)
    assert route.regions[0]["route_source"] == "TRINITYCORE_MMAP"
    assert geometry.walks == 1 and not route.anchors[-1].get("flight_plan")


def test_a_requested_descent_to_another_level_also_ignores_the_flat_minimum():
    geometry = BridgeGeometry()
    geometry.vmap_surfaces_at = lambda instance_id, point: []  # lower landing is open sky
    route = GlobalNavigator(navmesh=geometry).plan(request(z=200.), state(z=245.), 10.)
    assert route.regions[0]["route_source"] == "FLIGHT_PLAN"
    assert route.anchors[-1]["z"] == 200.


def test_no_observed_height_does_not_invent_a_vertical_flight():
    route = GlobalNavigator(navmesh=BridgeGeometry()).plan(request(), state(observed=False), 10.)
    assert not route.anchors     # also refuses the known-wrong ground endpoint


@pytest.mark.parametrize("geometry,reason", [(None, "no_world_geometry"),
                                             (BridgeGeometry(covered=True), "landing_under_cover")])
def test_a_required_flight_failure_cannot_silently_walk_under_the_target(geometry, reason):
    route = GlobalNavigator(navmesh=geometry).plan(request(), state(), 10.)
    assert not route.anchors and route.confidence == 0.
    assert route.regions[0]["flight_plan_status"] == reason
    if geometry:
        assert geometry.walks == 0


@pytest.mark.parametrize("require_navmesh", [True, False])
def test_ground_fallback_rejects_a_path_ending_44_yards_below_the_known_target(require_navmesh):
    route = GlobalNavigator(navmesh=BridgeGeometry()).plan(
        request(flight=False, require_navmesh=require_navmesh), state(), 10.)
    assert not route.anchors and route.confidence == 0.


def test_a_plain_move_never_acquires_a_flight_implicitly():
    route = GlobalNavigator(navmesh=BridgeGeometry()).plan(request(flight=False, z=201.), state(), 10.)
    assert route.regions[0]["route_source"] == "TRINITYCORE_MMAP"


def test_canonical_move_installs_the_flight_controller_and_requests_takeoff():
    payload = state()
    before = deepcopy(payload)
    nav = NavigationService(navmesh=BridgeGeometry())
    nav.start_skill_request("MOVE", target(), payload, "same-action", 10.)
    assert nav._movement.flight is not None
    assert nav._active_request.correlation_id == "same-action"
    assert any(command.binding == "JUMP" for command in nav.command(payload, "takeoff", 10.1))
    assert payload == before


def test_airborne_short_approach_climbs_toward_the_upper_landing():
    payload = state()
    nav = NavigationService(navmesh=BridgeGeometry())
    nav.start_skill_request("MOVE", target(), payload, "same-action", 10.)
    air = state(z=205.)
    air.update(monotonic_time=11., movement={"flying": True, "falling": False, "indoors": False})
    point = {**air["player_world_position"], "sample_time": 11.}
    air["packet_flight"] = {"sample_time": 11., "position": point, "adv_flying": True,
                            "pitch": 0., "facing": 0., "forward_velocity": 18., "up_velocity": 0.}
    commands = nav.command(air, "climb", 11.)
    assert any(c.binding == "PITCHUP" or "PITCHUP" in c.simultaneous for c in commands)
    assert any(c.binding == "JUMP" for c in commands)


def test_touchdown_below_the_deck_relaunches_without_a_ground_walk_under_it():
    payload = state()
    nav = NavigationService(navmesh=BridgeGeometry())
    nav.start_skill_request("MOVE", target(), payload, "same-action", 10.)
    nav._movement.flight.was_airborne = True
    nav._start_ground_approach(payload, 11.)
    assert nav._active_request.correlation_id == "same-action"
    assert nav._active_request.destination.get("flight_relaunch") is True
    assert nav._movement.flight is not None
    assert nav._active_route.regions[0]["route_source"] == "FLIGHT_PLAN"


def test_arrival_shortcuts_cannot_accept_a_known_different_level():
    payload = state()
    payload["player_world_position"].update(x=target()["x"], y=target()["y"])
    wanted = request(flight=False)
    assert not NavigationService._already_arrived(wanted, payload)
    nav = NavigationService(navmesh=BridgeGeometry())
    nav._active_request = wanted
    assert not nav._original_goal_within_arrival(payload)
    payload["player_world_position"]["z"] = 247.35
    assert NavigationService._already_arrived(wanted, payload)
    assert nav._original_goal_within_arrival(payload)
