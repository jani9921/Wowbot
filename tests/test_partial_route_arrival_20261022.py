"""A localization leg is progress, never arrival at the original quest POI."""
from types import SimpleNamespace
from dataclasses import replace
import math

import pytest

from wowbot.navigation.contracts import ArrivalEnvelope, GlobalRoute, NavigationRequest
from wowbot.navigation.mmap_navmesh import NavMeshPath
from wowbot.navigation.service import NavigationService


class FlatMesh:
    def walkable_heights_at(self, instance, point, radius=2.5):
        return [10.]

    def find_path(self, instance, start, end):
        anchors = tuple({**p, "z": 10., "source": "TRINITYCORE_MMAP",
                         "instance_id": instance} for p in (start, end))
        return NavMeshPath(anchors, 2, 1, math.hypot(end["x"]-start["x"], end["y"]-start["y"]))


def state(x, t, *, y=0.):
    return {"session_id": "partial-route", "map_id": 2022, "monotonic_time": t,
            "orientation": 0., "movement": {"falling": False, "moving": True, "speed": 7.},
            "player_world_position": {"coordinate_space": "WORLD_YARDS", "instance_id": 2444,
                                      "x": x, "y": y, "z": 10., "z_known": True,
                                      "z_observed": True, "sample_time": t}}


def request(x=100., **params):
    return NavigationRequest("request:quest", "move:quest", "MOVE_TO_LOCATION",
        {"coordinate_space": "WORLD_YARDS", "instance_id": 2444, "x": x, "y": 0.,
         "require_navmesh": True, "quest_id": 65760, "purpose": "LOCATE_QUEST_OBJECTIVE_REGION",
         **params}, arrival=ArrivalEnvelope(desired_range=8.))


def uncertain_navigation(mesh=None):
    nav = NavigationService(navmesh=mesh or FlatMesh())
    nav._z.resolve_target = lambda instance, x, y, **kw: SimpleNamespace(
        x=x, y=y, z=10., confidence=.3, source="MMAP", alternatives=())
    return nav


def test_short_leg_is_strictly_bounded_even_after_collinear_anchors_were_simplified():
    nav = uncertain_navigation()
    nav.start_request(request(), state(0., 1.), 1.)
    assert nav._active_route.anchors[-1]["x"] <= nav.LOW_CONFIDENCE_LEG_YARDS
    assert nav._active_request.destination["x"] == 100.


def test_reaching_a_partial_leg_keeps_the_original_move_active_until_the_real_goal():
    nav = uncertain_navigation()
    nav.start_request(request(), state(0., 1.), 1.)
    leg_end = nav._active_route.anchors[-1]["x"]
    assessment = nav.observe(state(leg_end, 2.), "sample:2", 2.)
    assert not assessment.terminal, assessment
    assert not assessment.success
    assert assessment.reason == "route_localization_leg_advanced"
    assert nav._active_request.request_id == "request:quest"
    assert nav._active_request.destination["x"] == 100.
    assert nav._active_route.anchors[-1]["x"] > leg_end
    for t in range(3, 10):
        end = nav._active_route.anchors[-1]["x"]
        assessment = nav.observe(state(end, float(t)), f"sample:{t}", float(t))
        if assessment.terminal:
            assert assessment.success
            assert end >= 92.
            break
    else:
        pytest.fail("bounded legs did not finish at the true destination")


def test_partial_leg_does_not_face_the_distant_npc_or_inherit_its_stop_radius():
    nav = uncertain_navigation()
    nav.start_request(request(face_on_arrival=True), state(0., 1.), 1.)
    destination = nav.movement_snapshot()["destination"]
    assert destination["route_waypoint_final"] is False
    assert destination["purpose"] == "ROUTE_WAYPOINT"
    assert destination.get("stop_distance") is None


@pytest.mark.parametrize("trigger", ["ttl", "danger", "fall"])
def test_replans_cannot_bypass_low_confidence_leg_limit(trigger):
    nav = uncertain_navigation()
    nav.start_request(request(), state(0., 1.), 1.)
    if trigger == "ttl":
        nav._active_route = replace(nav._active_route, valid_until=1.5)
        nav.local_plan(state(5., 2.), now=2., observation_id="replan:2")
    elif trigger == "danger":
        nav._route_danger_revision = -1
        nav.local_plan(state(5., 2.), now=2., observation_id="replan:2")
    else:
        nav._replan_from_tracked_layer(state(5., 2.), "fall:2", 2.)
    assert nav._active_route.anchors[-1]["x"] <= 35.01
    end = nav._active_route.anchors[-1]["x"]
    assert not nav.observe(state(end, 3.), "sample:3", 3.).success


def test_missing_corridor_after_a_probe_fails_instead_of_claiming_arrival():
    nav = uncertain_navigation()
    nav.start_request(request(), state(0., 1.), 1.)
    end = nav._active_route.anchors[-1]["x"]
    nav._navmesh.find_path = lambda *args, **kwargs: None
    assessment = nav.observe(state(end, 2.), "sample:2", 2.)
    assert assessment.terminal and not assessment.success
    assert assessment.reason == "required_navmesh_route_unavailable"


def test_an_incomplete_mesh_endpoint_outside_the_goal_radius_is_not_success():
    class Incomplete(FlatMesh):
        def find_path(self, instance, start, end):
            return super().find_path(instance, start, {**end, "x": 30.})
    nav = NavigationService(navmesh=Incomplete())
    nav.start_request(request(z=10., z_known=True), state(0., 1.), 1.)
    assessment = nav.observe(state(30., 2.), "sample:2", 2.)
    assert assessment.terminal and not assessment.success
    assert assessment.reason == "route_endpoint_outside_arrival_envelope"
    from wowbot.runtime import failure_reason_from_legacy, FailureReason
    assert failure_reason_from_legacy(assessment.reason) is FailureReason.PATH_BLOCKED


def test_short_leg_length_is_3d_and_does_not_invent_a_straight_shortcut():
    route = GlobalRoute("r", ({"x": 0., "y": 0., "z": 0.},
                             {"x": 3., "y": 4., "z": 12.},
                             {"x": 20., "y": 4., "z": 12.}), (), 30., .9, 1., 100.)
    nav = NavigationService(navmesh=FlatMesh())
    short = nav._short_leg_route(route, 6.5)
    assert short.anchors[-1]["x"] == pytest.approx(1.5)
    assert short.anchors[-1]["y"] == pytest.approx(2.)
    assert short.anchors[-1]["z"] == pytest.approx(6.)
    assert route.anchors[-1]["x"] == 20.


def test_final_arrival_radius_is_preserved_for_a_genuine_complete_route():
    nav = NavigationService(navmesh=FlatMesh())
    nav.start_request(request(x=20., z=10., z_known=True), state(0., 1.), 1.)
    assessment = nav.observe(state(13., 2.), "sample:2", 2.)
    assert assessment.terminal and assessment.success


def test_repeated_probes_keep_one_request_deadline_instead_of_resetting_it():
    nav = uncertain_navigation()
    nav.start_request(replace(request(), timeout=4.), state(0., 1.), 1.)
    end = nav._active_route.anchors[-1]["x"]
    assert not nav.observe(state(end, 2.), "p2", 2.).terminal
    end = nav._active_route.anchors[-1]["x"]
    assessment = nav.observe(state(end, 6.), "p6", 6.)
    assert assessment.terminal and not assessment.success
    assert assessment.reason == "movement_safety_deadline"


def test_an_empty_replan_cannot_be_accepted_with_the_old_probe_arrival_fact():
    nav = uncertain_navigation()
    nav.start_request(request(), state(0., 1.), 1.)
    end = nav._active_route.anchors[-1]["x"]
    nav._navmesh.find_path = lambda *args, **kwargs: None
    first = nav.observe(state(end, 2.), "p2", 2.)
    again = nav.observe(state(end, 3.), "p3", 3.)
    assert not first.success and not again.success
    assert first.reason == again.reason == "required_navmesh_route_unavailable"


def test_bent_route_probe_arrival_cannot_complete_a_quest_goal_still_far_away():
    class BentMesh(FlatMesh):
        def find_path(self, instance, start, end):
            corner = {**start, "x": start["x"]+30., "y": 20.}
            anchors = tuple({**p, "z": 10., "source": "TRINITYCORE_MMAP",
                             "instance_id": instance} for p in (start, corner, end))
            return NavMeshPath(anchors, 3, 1, 110.)
    nav = uncertain_navigation(BentMesh())
    nav.start_request(request(), state(0., 1.), 1.)
    end = nav._active_route.anchors[-1]
    assert math.hypot(end["x"]-100., end["y"]) > 50.
    result = nav.observe(state(end["x"], 2., y=end["y"]), "bent:2", 2.)
    assert not result.terminal and not result.success
    assert nav._active_request.destination["x"] == 100.
