"""Skyriding steering on fresh feedback, abilities and general flight travel.

Live 2026-10-25 17:26-17:30 (quest 77345, the agent's own flight): the drake
circled rings and overshot every heading by ~1.3 rad.  Causes found in the
decoded packets and the runtime profile:

* the packet inbox was drained only by the medium tick (1-3 Hz, seconds
  under SQLite load), so the 20 Hz flight loop steered on a facing/pitch
  0.3-0.6 s old; the medium tick also held the engine lock ~half the time;
* turn keys rotate 2.35 rad/s and pitch keys ~1.4 rad/s, not pi;
* a ring inside the turn circle was orbited; Surge Forward was never used.

User 2026-10-25: "ne csak erre a küldetésre csináld, hanem a magára a
repülésre, hogy igy is tudjon az agent repülni egyik questről a másikra".
"""
import math
from types import SimpleNamespace

import pytest

from skyriding_sim import SkyridingSim
from test_flight_plan_20261025 import Geometry
from test_packet_agent_bridge import bridge, addon  # noqa: F401  (fixture)
from test_packet_codecs import decoded
from test_skyriding_live_feedback_20261025 import flying_event
from wowbot.agent.flight_capability import skyriding_blockers
from wowbot.agent.models import Command, Goal, Mode, Proposal
from wowbot.agent.runtime_control import next_medium_interval
from wowbot.agent.skyriding_control import SkyridingControl, TURN_RATE, PASS_GRACE
from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.execution.command_dispatch import flight_ability_tap
from wowbot.navigation.flight_path import FlightPath
from wowbot.navigation.flight_route import plan_flight, skyriding_path
from wowbot.packetio.ipc import canonical, envelope

import json


# -- fresh packet feedback for the fast lane ------------------------------
def test_the_fast_lane_peeks_the_newest_own_movement_without_consuming_it(bridge):
    descriptor = json.loads(bridge.path.read_text())
    assert bridge.inbox.ingest_datagram(canonical(envelope(flying_event().to_dict(), descriptor)))
    assert bridge.adapter.peek_own_movement(bridge.world, 10.) is True
    flight = bridge.world.__dict__["_packet_last_own"]["flight"]
    assert flight["pitch"] == -.3 and flight["forward_velocity"] == 45.
    # Not consumed: the medium tick still applies the same event in full.
    observations = bridge.adapter.observations(None, bridge.world, 10.)
    assert len(observations) == 1 and bridge.world.ingest(observations[0])
    assert bridge.world.state["packet_flight"]["pitch"] == -.3
    assert bridge.adapter.peek_own_movement(bridge.world, 10.) is False      # nothing newer


def test_a_peek_from_another_ipc_context_is_ignored(bridge):
    descriptor = json.loads(bridge.path.read_text())
    assert bridge.inbox.ingest_datagram(canonical(envelope(flying_event().to_dict(), descriptor)))
    bridge.adapter.context = {**bridge.adapter.context, "context_id": "another"}
    assert bridge.adapter.peek_own_movement(bridge.world, 10.) is False
    assert "_packet_last_own" not in bridge.world.__dict__


def test_a_flight_move_gets_a_one_second_medium_tick_beside_the_parallel_lane():
    airborne = {"value": True}
    agent = SimpleNamespace(mode=Mode.FULL_AI, pending=SimpleNamespace(proposal=SimpleNamespace(skill="MOVE")),
                            parallel_control=SimpleNamespace(enabled=True),
                            navigation=SimpleNamespace(airborne_route_active=lambda: airborne["value"]))
    assert next_medium_interval(agent, 3.) == 1.
    airborne["value"] = False
    assert next_medium_interval(agent, 3.) == pytest.approx(1/3)


# -- the controller -----------------------------------------------------
def course(points, *, conditions=None, landing=None):
    return FlightPath.from_dict({
        "instance_id": 2444, "mode": "SKYRIDING",
        "waypoints": [dict(zip("xyz", p)) for p in points],
        "landing": dict(zip("xyz", landing or (points[-1][0]+200, points[-1][1], points[-1][2]-50))),
        "checkpoint_conditions": conditions or [None]*len(points), "radius": 10.})


def flight_state(at, *, x=0., y=0., z=200., facing=0., pitch=0., speed=50., sample_at=None, bar=True, usable=True):
    sample_at = at if sample_at is None else sample_at
    position = {"x": x, "y": y, "z": z, "sample_time": sample_at, "instance_id": 2444}
    state = {"is_mounted": True, "movement": {"flying": True}, "player_world_position": position,
             "packet_flight": {"sample_time": sample_at, "pitch": pitch, "facing": facing, "adv_flying": True,
                               "forward_velocity": speed, "up_velocity": 0., "position": position},
             "skyriding_controls": True}
    if bar:
        state["skyriding_bar"] = {"kind": "SKYRIDING", "actions": [
            {"id": 372608, "name": "Surge Forward", "action": "ACTIONBUTTON1", "is_usable": usable,
             "lacks_resource": not usable, "cooldown_remaining": 0}]}
    return state


def test_held_turn_keys_since_the_sample_are_predicted():
    control = SkyridingControl(course([(500., 0., 200.)]))
    control._send(0., .15, 1, 0)                                   # TURNLEFT held 0.00-0.15
    _point, facing, _pitch = control._predict((0., 0., 200.), {"pitch": 0., "forward_velocity": 50.}, 0., 0., .1)
    assert facing == pytest.approx(TURN_RATE * .1)
    control._send(.1, .1, -1, 0)                                   # replaced at 0.10 by TURNRIGHT
    _point, facing, _pitch = control._predict((0., 0., 200.), {"pitch": 0., "forward_velocity": 50.}, 0., 0., .15)
    assert facing == pytest.approx(TURN_RATE * (.1 - .05))


def test_a_ring_inside_the_turn_circle_is_not_orbited():
    """At 55 yd/s the turn radius is 23 yd: a ring 12 yd abeam is unreachable."""
    counter = {"kind": "COUNTER_AT_LEAST", "minimum": 1, "paths": [{"path": ["route_counters", "rings"]}]}
    control = SkyridingControl(course([(0., 14., 200.), (300., 0., 200.)],
                                      conditions=[counter, {**counter, "minimum": 2}]))
    control.assess(flight_state(1., speed=55.), 1.)
    commands = control.commands(flight_state(1., speed=55.), 1.)
    assert not any("TURNLEFT" in (command.binding, *command.simultaneous) for command in commands)
    assert control.last_reason == "extend_out_of_turn_circle"
    # Farther away it is reachable again: turn in.
    later = flight_state(2., x=40., speed=55.)
    control.assess(later, 2.)
    (command,) = control.commands(later, 2.)
    assert command.binding == "TURNLEFT" or "TURNLEFT" in command.simultaneous


def test_a_ring_flown_through_steers_on_before_the_server_credit():
    counter = {"kind": "COUNTER_AT_LEAST", "minimum": 1, "paths": [{"path": ["route_counters", "rings"]}]}
    control = SkyridingControl(course([(100., 0., 200.), (100., 300., 200.)],
                                      conditions=[counter, {**counter, "minimum": 2}]))
    for at, x in ((0., 60.), (.2, 96.), (.4, 120.)):
        state = flight_state(at, x=x)
        control.assess(state, at)
        control.commands(state, at)
    assert control.index == 0 and control.last_reason == "provisional_ring_2"
    late = flight_state(.4 + PASS_GRACE + .1, x=200.)
    control.assess(late, late["packet_flight"]["sample_time"])
    control.commands(late, late["packet_flight"]["sample_time"])
    assert control.last_reason == "ring_1"                        # no credit: it was missed
    credited = {**flight_state(3., x=120.), "route_counters": {"rings": 1}}
    control.assess(credited, 3.)
    assert control.index == 1


def test_surge_forward_is_tapped_from_the_skyriding_bar_when_slow_aligned_and_far():
    control = SkyridingControl(course([(400., 0., 200.)]))
    state = flight_state(1., speed=30.)
    control.assess(state, 1.)
    assert control.commands(state, 1.) == (Command("BIND", "ACTIONBUTTON1", .05),)
    assert flight_ability_tap(control.commands(state, 1.05)) is False       # not again within 1.5 s
    for blocked in (flight_state(5., speed=30., usable=False), flight_state(5., speed=30., bar=False),
                    {**flight_state(5., speed=30.), "skyriding_controls": False}):
        control.last_boost_at = None
        assert not flight_ability_tap(control.commands(blocked, 5.))


def test_only_a_bare_action_button_tap_leaves_the_movement_lease():
    assert flight_ability_tap((Command("BIND", "ACTIONBUTTON1", .05),))
    assert not flight_ability_tap((Command("BIND", "ACTIONBUTTON1", .05, simultaneous=("TURNLEFT",)),))
    assert not flight_ability_tap((Command("BIND", "TURNLEFT", .1),))
    assert not flight_ability_tap((Command("BIND", "ACTIONBUTTON1", .05), Command("BIND", "JUMP", .08)))


# -- general Skyriding travel -------------------------------------------
def test_a_terrain_plan_becomes_skyriding_waypoints_above_its_cruise_height():
    plan, _ = plan_flight(Geometry(), 2444, {"x": 0., "y": 0., "z": 10.}, {"x": 800., "y": 0.})
    path = FlightPath.from_dict(skyriding_path(plan))
    xs = [point["x"] for point in path.waypoints]
    assert xs == pytest.approx([160., 320., 480., 640., 710.])
    assert path.waypoints[0]["z"] >= 50. + 12. + 20.               # over the ridge with dive room
    assert path.landing == {"x": 800., "y": 0., "z": 10.} and not path.end_in_air
    assert path.checkpoint_conditions == (None,)*5 and path.radius == 15.


def test_a_truncated_plan_ends_in_the_air_and_completes_the_leg_there():
    plan, _ = plan_flight(Geometry(), 2444, {"x": 0., "y": 0., "z": 10.}, {"x": 880., "y": 0.})
    from dataclasses import replace
    plan = replace(plan, truncated=True)
    value = skyriding_path(plan)
    assert value["end_in_air"] is True and value["landing"]["z"] > 30.
    control = SkyridingControl(FlightPath.from_dict(value))
    control.index = len(control.waypoints)
    assert control.assess(flight_state(1.), 1.) == ("ARRIVED", "skyriding_air_leg_complete")


class Hill(SkyridingSim):
    def ground(self, x, y):
        return 50. if 100 <= x <= 140 else 10.


def test_a_quest_to_quest_trip_is_flown_over_the_ridge_and_lands_at_the_destination():
    plan, _ = plan_flight(Geometry(), 2444, {"x": 0., "y": 0., "z": 10.}, {"x": 800., "y": 0.})
    path = FlightPath.from_dict(skyriding_path(plan))
    control = SkyridingControl(path)
    sim = Hill((0., 0., 10.), 0., [(p["x"], p["y"], p["z"]) for p in (*path.waypoints, path.landing)],
               ground_z=10., vigor_regen=8., ring_radius=15.)
    lowest = math.inf
    while sim.t < 90.:
        state = sim.state("travel", 0)
        state["player_world_position"]["instance_id"] = 2444
        verdict, reason = control.assess(state, sim.t)
        if reason == "skyriding_ground_approach_required" and not sim.adv:
            break
        assert verdict == "MOVING", reason
        for command in control.commands(state, sim.t):
            sim.apply(command)
        sim.run_tick()
        if sim.adv and 90 <= sim.x <= 150:
            lowest = min(lowest, sim.z - 50.)
    assert not sim.adv and math.hypot(sim.x-800., sim.y) <= 100., (sim.x, sim.y, sim.t, reason)
    assert lowest > 5., lowest                                     # cleared the ridge


def skyriding_world(*, mounted=False, flying=False, indoors=False, advanced=True, yards=600.):
    state = {"is_mounted": mounted, "movement": {"flying": flying, "indoors": indoors},
             "flight": {"advanced_flyable_area": advanced, "flyable_area": True, "can_glide": mounted},
             "mount_capability": {"has_collected_mount": True, "riding_capability_confirmed": True},
             "player_world_position": {"x": 0., "y": 0., "z": 10., "instance_id": 2444,
                                       "coordinate_space": "WORLD_YARDS"},
             "actionbar": [{"slot": 13, "action": "MULTIACTIONBAR1BUTTON1", "binding_primary": "SHIFT-1",
                            "kind": "summonmount", "id": 1589, "is_usable": True, "cooldown_remaining": 0,
                            "mount": {"mount_id": 1589, "mount_type_id": 402, "mount_usable": True,
                                      "mount_steady_flight": False}}]}
    move = Proposal.make("MOVE", "Quest objective", {"coordinate_space": "WORLD_YARDS", "x": yards, "y": 0.,
                                                     "world_map_id": 2444}, priority=80.)
    return SimpleNamespace(state=state), move


def test_a_long_trip_mounts_the_drake_and_flies_with_skyriding():
    world, move = skyriding_world()
    proposals = TravelModePolicy().apply([move], Goal.parse("Questelj", 100.), world, 100.)
    flight = next(p for p in proposals if p.skill == "MOVE")
    assert flight.parameters["flight"] is True and flight.parameters["flight_style"] == "SKYRIDING"
    mount = next(p for p in proposals if p.skill == "MOUNT")
    assert mount.parameters == {"binding": "MULTIACTIONBAR1BUTTON1", "purpose": "MOVEMENT_FLIGHT"}


def test_short_trips_indoors_or_outside_a_skyriding_zone_travel_as_before():
    for options in ({"yards": 150.}, {"indoors": True}, {"advanced": False}):
        world, move = skyriding_world(**options)
        proposals = TravelModePolicy().apply([move], Goal.parse("Questelj", 100.), world, 100.)
        assert not any(p.parameters.get("flight") for p in proposals if p.skill == "MOVE"), options


def test_in_the_air_every_move_flies_and_a_failed_flight_walks_for_a_while():
    world, move = skyriding_world(mounted=True, flying=True, yards=60.)
    proposals = TravelModePolicy().apply([move], Goal.parse("Questelj", 100.), world, 100.)
    assert [p.skill for p in proposals] == ["MOVE"] and proposals[0].parameters["flight"] is True
    policy = TravelModePolicy()
    world, move = skyriding_world(mounted=True)
    world.runtime_context = {"last_result": {"skill": "MOVE", "action_id": "a1", "outcome": "FAILURE",
                                             "reason": "skyriding_takeoff_failed"}}
    proposals = policy.apply([move], Goal.parse("Questelj", 100.), world, 100.)
    assert not proposals[0].parameters.get("flight")
    assert policy.apply([move], Goal.parse("Questelj", 100.), world, 170.)[0].parameters.get("flight") is True


def test_skyriding_needs_no_flying_riding_skill_but_a_gliding_mount():
    world, _ = skyriding_world()
    assert skyriding_blockers(world.state) == []
    world.state["mount_capability"]["flying_riding_known"] = False             # live: Journeyman only
    assert skyriding_blockers(world.state) == []
    world.state["actionbar"][0]["mount"]["mount_steady_flight"] = True
    assert skyriding_blockers(world.state) == ["mount_set_to_steady_flight"]
    mounted, _ = skyriding_world(mounted=True)
    mounted.state["flight"]["can_glide"] = False
    assert skyriding_blockers(mounted.state) == ["mounted_on_a_non_skyriding_mount"]


def test_the_movement_controller_flies_a_skyriding_style_plan_with_the_skyriding_loop():
    from wowbot.agent.movement_controller import ReachMovementController
    plan, _ = plan_flight(Geometry(), 2444, {"x": 0., "y": 0., "z": 10.}, {"x": 800., "y": 0.})
    controller = ReachMovementController()
    state = flight_state(1., x=0., z=10.)
    controller.start({"coordinate_space": "WORLD_YARDS", "x": 800., "y": 0., "z": 10., "instance_id": 2444,
                      "flight_plan": plan.to_dict(), "flight_style": "SKYRIDING"}, state, "obs", 1.)
    assert isinstance(controller.flight, SkyridingControl) and len(controller.flight.waypoints) == 6
    assert controller.snapshot()["flight_mode"] == "SKYRIDING"


class Island(Geometry):
    """Flight geometry; the landing cannot be walked to (find_path fails)."""

    def __init__(self, walkable=False):
        self.walkable = walkable

    def find_path(self, instance_id, start, end):
        if not self.walkable:
            return None
        from wowbot.navigation.mmap_navmesh import NavMeshPath
        anchor = lambda point: {**point, "instance_id": instance_id, "coordinate_space": "WORLD_YARDS",
                                "source": "TRINITYCORE_MMAP"}
        return NavMeshPath((anchor(start), anchor(end)), 2, 1, 12.)


def travel_state(at, *, x, airborne):
    state = flight_state(at, x=x, z=40. if airborne else 10.)
    state["packet_flight"]["adv_flying"] = airborne
    state["movement"] = {"flying": airborne, "falling": False}
    state["player_world_position"].update(coordinate_space="WORLD_YARDS", z_observed=True,
                                          z_source="PACKET_CLIENT_MOVEMENT")
    state.update(map_id=2022, monotonic_time=at)
    return state


@pytest.mark.parametrize("walkable", [True, False])
def test_a_landing_not_reachable_on_foot_takes_off_again_else_it_walks(walkable):
    """User 2026-10-25: "ha elérhető gyalog, akkor gyalog, ha nem, akkor repül"."""
    from wowbot.navigation.service import NavigationService
    nav = NavigationService(navmesh=Island(walkable))
    move = {"coordinate_space": "WORLD_YARDS", "x": 800., "y": 0., "instance_id": 2444, "world_map_id": 2444,
            "flight": True, "flight_style": "SKYRIDING", "require_navmesh": True}
    nav.start_skill_request("MOVE", move, travel_state(1., x=0., airborne=False), "trip", 1.)
    assert isinstance(nav._movement.flight, SkyridingControl)
    nav.observe(travel_state(2., x=400., airborne=True), "air", 2.)
    landed = travel_state(30., x=760., airborne=False)
    assert nav.observe(landed, "landed", 30.).reason == "skyriding_ground_approach_required"
    result = nav.observe(landed, "handoff", 30.1)               # the next (medium) observation
    assert not result.terminal, result
    if walkable:
        assert nav._movement.flight is None                       # walks the last stretch
    else:
        assert isinstance(nav._movement.flight, SkyridingControl)  # flies on to the landing
        assert [c.binding for c in nav.command(landed, "handoff", 30.1)] == ["JUMP"]
