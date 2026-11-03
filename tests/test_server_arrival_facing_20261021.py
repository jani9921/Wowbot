"""Shared final-facing proof for NPC, combat and object approach; no client input."""
import math
from types import SimpleNamespace

from wowbot.agent.movement_controller import MovementPhase, ReachMovementController
from wowbot.navigation.contracts import GlobalRoute, NavigationRequest
from wowbot.navigation.service import NavigationService


def seen(facing, at, *, position_time=None):
    return {"monotonic_time": at, "orientation": facing,
        "player_world_position": {"x": 7.5, "y": 0., "instance_id": 2444,
                                 **({"sample_time": position_time} if position_time is not None else {})}}


def ready_controller(**extra):
    controller = ReachMovementController()
    controller.start({"coordinate_space": "WORLD_YARDS", "x": 10., "y": 0.,
        "stop_distance": 4., "face_on_arrival": True, "instance_id": 2444, **extra},
        seen(math.pi/2, 0.), "s0", 0.)
    return controller


def enter_facing(controller, *, position_time=None):
    for index in range(1, 5):
        at = index*.1
        assessment = controller.observe(seen(math.pi/2, at, position_time=position_time), f"s{index}", at)
        if controller.steering_mode == "FACE_ON_ARRIVAL":
            return assessment
    raise AssertionError("controller did not enter final facing")


def test_expired_facing_is_a_failure_never_an_arrival_success():
    controller = ready_controller()
    assert not enter_facing(controller).terminal
    result = controller.observe(seen(math.pi/2, 4.), "timeout", 4.)
    assert result.phase is MovementPhase.FAILED and result.terminal and not result.success
    assert result.reason == "facing_failed" and not controller.command(seen(math.pi/2, 4.), "timeout", 4.)
    later = controller.observe(seen(0., 4.1), "late-after-terminal", 4.1)
    assert later.terminal and not later.success


def test_final_facing_ignores_the_travel_heading_smoother():
    controller = ready_controller()
    enter_facing(controller)
    controller.smoothed_heading = math.pi
    result = controller.observe(seen(.1, .8), "aligned", .8)
    assert result.terminal and result.success
    # The opposite case must not accept a smoothed heading that is aligned
    # while the actual actor is off to the side.
    controller = ready_controller(face_towards={"x": 7.5, "y": 3., "instance_id": 2444})
    for i in range(1, 5):
        result = controller.observe(seen(0., i*.1), str(i), i*.1)
    assert not result.terminal
    assert controller.command(seen(0., .5), "turn", .5)[0].binding == "TURNLEFT"


def test_orientation_can_finish_an_in_place_turn_without_a_new_position_sample():
    controller = ready_controller()
    # Enter final-facing with ordinary fresh position samples, then retain
    # the exact same position clock while only the heading changes.
    enter_facing(controller)
    last = controller.last_position_time
    controller.last_position_time = 10.
    controller.observe(seen(math.pi/2, .7, position_time=10.), "held-pos", .7)
    result = controller.observe(seen(.1, .8, position_time=10.), "fresh-heading", .8)
    assert result.terminal and result.success


def test_final_route_keeps_actor_facing_point_separate_from_navmesh_anchor():
    service = NavigationService()
    original = {"x": 10., "y": 0., "instance_id": 2444,
        "coordinate_space": "WORLD_YARDS", "face_on_arrival": True}
    service._active_request = NavigationRequest("n", "c", "MOVE_TO_LOCATION", original)
    service._active_route = GlobalRoute("r", ({"x": 8., "y": 1., "z": 2.},), (), 1., 1., 0., 100.)
    service._route_waypoint_index = 0
    destination = service._current_route_destination()
    assert (destination["x"], destination["y"]) == (8., 1.)
    assert destination["face_towards"] == {"x": 10., "y": 0., "instance_id": 2444}


def test_live_server_actor_position_controls_final_bearing_and_removal_stops_input():
    guid = "Creature-0-3769-2444-47-193393-00005824CA"
    live = seen(0., .1)
    actor = {"guid": guid, "kind": "CREATURE", "entry_id": 193393, "map_id": 2444,
        "position": {"x": 7.5, "y": 3., "z": 2., "source": "PACKET_CREATE_MOVEMENT", "age": 0.}}
    live["packet_entities"] = {guid: actor}
    controller=ReachMovementController()
    # The positive scenario starts with its verified own-world actor present.
    # A start without that identity now correctly latches a typed terminal
    # loss, rather than letting a later control frame silently re-arm it.
    controller.start({"coordinate_space":"WORLD_YARDS","x":10.,"y":0.,
        "stop_distance":4.,"face_on_arrival":True,"instance_id":2444,
        "server_entity_guid":guid},live,'s0',0.)
    for index in range(1, 5):
        controller.observe(live, str(index), index*.1)
    assert controller.command(live, "turn-live", .5)[0].binding == "TURNLEFT"
    actor["removed"] = True
    assert not controller.command(live, "no-blind-turn", .6)


def test_selected_entity_faces_its_current_position_not_the_old_request_point():
    controller = ready_controller(target_guid="selected-actor",
        face_towards={"x": 10., "y": 0., "instance_id": 2444})
    live = seen(0., .1)
    live["target"] = {"guid": "selected-actor", "world_position": {
        "x": 7.5, "y": 3., "instance_id": 2444}}
    distance, error = controller._arrival_facing_error(live)
    assert distance == 3. and abs(error-math.pi/2) < 1e-9
    live["target"]["guid"] = "someone-else"
    assert controller._arrival_facing_error(live) is None
