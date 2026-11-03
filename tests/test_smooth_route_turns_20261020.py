"""Running turns at route waypoints (user 2026-10-20).

"The MOVE is very choppy: it reaches a point, turns to where it wants to go,
then starts again."  Each route waypoint restarted the controller, and any
bearing to the next leg beyond 0.58 rad (33 deg) stopped the run for a turn in
place.  While running, bends up to ~77 deg are now taken with W and the turn
key held together; a fresh start, a hairpin or a point right beside a final
destination still turn in place.  No corner is cut early.
"""
import math

from wowbot.agent.movement_controller import ReachMovementController


def pose(x=0., y=0., facing=0., at=1.):
    return {"player_world_position": {"x": x, "y": y, "coordinate_space": "WORLD_YARDS",
                                      "sample_time": at}, "orientation": facing, "monotonic_time": at}


def waypoint(angle, distance=10., final=False):
    return {"coordinate_space": "WORLD_YARDS", "x": distance*math.cos(angle), "y": distance*math.sin(angle),
            "route_waypoint_final": final, "route_id": "r", "instance_id": 2175}


def first_command(controller, destination, at=1., *, running=False):
    if running:
        controller.last_forward_at = at-.2
        controller.start(destination, pose(at=at), f"start:{at}", at, continuing=True)
    else:
        controller.start(destination, pose(at=at), f"start:{at}", at)
    return controller.command(pose(at=at+.05), f"cmd:{at}", at+.05)


def test_a_running_character_takes_a_57_degree_bend_without_stopping():
    (command,) = first_command(ReachMovementController(), waypoint(1.0), running=True)
    assert command.binding == "MOVEFORWARD" and command.simultaneous == ("TURNLEFT",)
    assert .06 <= command.duration <= .16


def test_standing_still_hairpins_and_final_points_still_turn_in_place():
    (still,) = first_command(ReachMovementController(), waypoint(1.0))
    assert still.binding == "TURNLEFT" and not still.simultaneous
    (hairpin,) = first_command(ReachMovementController(), waypoint(1.6), running=True)
    assert hairpin.binding == "TURNLEFT"
    beside = {**waypoint(1.0, distance=3.5, final=True), "stop_distance": 1.}
    (beside_final,) = first_command(ReachMovementController(), beside, running=True)
    assert beside_final.binding == "TURNLEFT"


def test_only_the_next_leg_of_the_same_walk_carries_the_run():
    controller = ReachMovementController()
    controller.start(waypoint(0.), pose(), "a", 1.)
    controller.command(pose(at=1.05), "a1", 1.05)            # straight: running now
    assert controller.last_forward_at == 1.05
    controller.start(waypoint(1.0), pose(at=1.2), "b", 1.2, continuing=True)
    assert controller.last_forward_at == 1.05
    fresh = ReachMovementController()
    fresh.start(waypoint(0.), pose(), "a", 1.)
    fresh.command(pose(at=1.05), "a1", 1.05)
    fresh.start(waypoint(1.0), pose(at=1.2), "b", 1.2)       # a new MOVE: no carry
    assert fresh.last_forward_at is None
