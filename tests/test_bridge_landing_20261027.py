"""Live 2026-10-27 16:41-16:42 (Taking the Walls, East Siege Arbalest on a
bridge, z 245.6): the flight touched down under the bridge (z 200), 1.6 yd
from it flat.  The MOVE counted as arrived, a facing turn toward a point
straight above failed, the agent WAITed, flew up and landed under it again
(user: "mindig az arbalest alá száll, és WAIT-el")."""
from types import SimpleNamespace

from wowbot.agent.destination_distance import arrived
from wowbot.agent.movement_controller import MovementPhase, ReachMovementController
from wowbot.navigation.flight_route import FlightPlan

ARBALEST = {"x": 2131.49, "y": 2301.36, "z": 245.64, "z_known": True, "coordinate_space": "WORLD_YARDS",
            "instance_id": 2444, "stop_distance": 1.2, "face_on_arrival": True}


def under_the_bridge(z=200.7):
    return {"monotonic_time": 10., "orientation": 0.,
            "player_world_position": {"x": 2132.2, "y": 2301.0, "z": z, "z_observed": True,
                                      "instance_id": 2444, "coordinate_space": "WORLD_YARDS"}}


def test_under_the_bridge_is_not_arrival():
    assert not arrived(under_the_bridge(), ARBALEST)
    assert arrived(under_the_bridge(z=246.9), ARBALEST)                 # on the deck
    unknown = under_the_bridge()
    unknown["player_world_position"]["z_observed"] = False
    assert arrived(unknown, ARBALEST)                                   # no server height: flat as before


def test_no_facing_turn_toward_a_point_straight_above():
    controller = ReachMovementController.__new__(ReachMovementController)
    controller.destination = dict(ARBALEST)
    controller.face_started_at = None
    result = controller._facing_after_arrival(under_the_bridge(), 10.)
    assert result.terminal and result.reason == "arrived_on_other_level"
    assert controller.phase is MovementPhase.FAILED


def test_the_approach_stays_above_a_raised_landing():
    # The 16:41 profile: gorge under the bridge (155-204), deck at 248.
    profile = tuple([(0., 260.8), (8., 214.4), *((8.*i, 156.) for i in range(7, 27)),
                     (216., 155.3), (224., 204.4), (232., 248.1), (239.6, 247.3)])
    plan = FlightPlan(2444, {"x": 2215.1, "y": 2525.9, "z": 260.7},
                      {"x": 2131.49, "y": 2301.36, "z": 247.35}, 239.6, profile)
    assert all(plan.target_z(along) >= 247.35 for along in (150., 170., 190., 210., 230., 239.))
    low = FlightPlan(2444, {"x": 0., "y": 0., "z": 100.}, {"x": 300., "y": 0., "z": 50.}, 300.,
                     tuple((8.*i, 60.) for i in range(39)))
    assert low.target_z(100.) == 72.                                    # far out: terrain clearance only


def _probe_controller():
    controller = ReachMovementController.__new__(ReachMovementController)
    controller.destination = {**ARBALEST, "require_navmesh": True}
    controller.bindings = None
    controller.control_updates, controller.command_history = 0, []
    controller.last_command_observation_id, controller.last_command_at = None, None
    return controller


def test_a_standing_start_without_server_height_taps_a_turn_once():
    """Live 16:39:18-16:39:28: started standing, no own packet, no height.
    Live 2026-10-28 10:53: mounted too (a turn tap, not a jump)."""
    controller = _probe_controller()
    standing = under_the_bridge()
    standing["player_world_position"].update(z=None, z_observed=False)
    standing["packet_telemetry"] = {"last_event": "ENTITY_POSITION"}
    standing["is_mounted"] = True
    (tap,) = controller._height_probe(standing, "o1", 10., -.4)
    assert tap.binding == "TURNRIGHT" and tap.duration <= .06
    assert controller._height_probe(standing, "o2", 20.) == ()          # once per 30 s
    assert controller._height_probe(standing, "o3", 41.)                # later again
    known = under_the_bridge()
    known["packet_telemetry"] = {"last_event": "ENTITY_POSITION"}
    assert _probe_controller()._height_probe(known, "o4", 10.) == ()     # server height known
    no_lane = dict(standing, packet_telemetry=None)
    assert _probe_controller()._height_probe(no_lane, "o5", 10.) == ()   # no packets: never


def test_the_server_height_survives_the_navmesh_surface_projection():
    """Live 17:03: the walk's state was projected onto the navmesh surface,
    z_observed was lost and the 44 yd to the deck went unseen."""
    projected = under_the_bridge()
    position = projected["player_world_position"]
    position.update(z=200.9, z_observed=None, z_source="NAVMESH_SURFACE", observed_z=200.7)
    assert not arrived(projected, ARBALEST)
    controller = ReachMovementController.__new__(ReachMovementController)
    controller.destination = dict(ARBALEST)
    assert controller._level_distance(projected, 1.) > 40.
