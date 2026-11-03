"""A known destination height far above/below is not arrival (live 2026-10-26
17:22-17:23: the turn-in point at z 95, the agent on a ledge at z 185.6
straight above it "arrived" ~20 times)."""
from wowbot.navigation.service import NavigationService


def ledge(z):
    return {"monotonic_time": 10., "orientation": 0., "movement": {}, "is_mounted": False,
            "player_world_position": {"x": 1108.3, "y": 375.8, "z": z, "z_observed": True, "instance_id": 2444,
                                      "coordinate_space": "WORLD_YARDS", "sample_time": 10.}}


def destination():
    return {"x": 1107., "y": 372., "z": 95., "z_known": True, "coordinate_space": "WORLD_YARDS",
            "instance_id": 2444, "stop_distance": 6., "require_navmesh": False}


def test_straight_above_the_destination_is_not_arrival():
    nav = NavigationService()
    nav.start_skill_request("MOVE", destination(), ledge(185.6), "o1", 10.)
    result = nav.observe({**ledge(185.6), "monotonic_time": 10.3}, "o2", 10.3)
    assert not (result.terminal and getattr(result, "success", False)), result


def test_on_the_destination_level_it_arrives():
    from wowbot.agent.movement_controller import ReachMovementController
    controller = ReachMovementController.__new__(ReachMovementController)
    controller.destination = destination()
    assert controller._level_distance(ledge(185.6), 4.) == 185.6 - 95.
    assert controller._level_distance(ledge(98.), 4.) == 4.


def test_a_flight_that_lands_on_another_level_is_not_arrival():
    """Live 2026-10-26 18:05:15: Skyriding to z 188 "arrived" at z 259."""
    from wowbot.agent.movement_controller import ReachMovementController, MovementPhase

    class Landed:
        phase = "LANDED"
        path = None
        def assess(self, state, distance, tolerance, now):
            return "ARRIVED", "flight_landed"

    controller = ReachMovementController.__new__(ReachMovementController)
    controller.destination = {**destination(), "z": 188.}
    controller.flight = Landed()
    controller.started_at = 0.
    controller.max_flight_seconds = 600.
    controller._tolerance = lambda: 6.
    high = controller._observe_flight(ledge(259.), "o", 10., 5.8)
    assert high.terminal and not high.success and high.reason == "arrived_on_other_level"
    level = controller._observe_flight(ledge(190.), "o", 10., 5.8)
    assert level.success
