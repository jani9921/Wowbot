"""A flying quest vehicle by its own packets (live 2026-10-26 11:05-11:06).

Training Wings (70061), the Ruby Whelpling: the whelp hovered at z 284.3
(its own client movement, mover = the vehicle GUID) while the weedlings were
at z 161-278.  The vehicle's packets were dropped (not the player's mover),
the passenger's root failed the MOVE at once ("player_rooted"), the flat
approach "arrived" 9 yd away horizontally, Tab never qualified and the agent
waited.
"""
import math
from dataclasses import replace

import pytest

from test_packet_agent_bridge import bridge, deliver  # noqa: F401  (fixture)
from test_packet_codecs import decoded, movement_body
from wowbot.agent.hover_control import HoverControl
from wowbot.agent.models import Command
from wowbot.agent.packet_entity_facts import tab_target_check
from wowbot.agent.vehicle_combat_planning import ServerVehicleCombatPolicy

VEHICLE_HIGH = (9 << 58) | (2444 << 29)


@pytest.fixture(autouse=True)
def fresh_couplings():
    import wowbot.agent.hover_control as hover
    saved = dict(hover.COUPLED)
    hover.COUPLED.clear()
    yield hover.COUPLED
    hover.COUPLED.clear()
    hover.COUPLED.update(saved)


def test_in_a_vehicle_the_vehicle_movers_packets_are_ours(bridge):
    vehicle = decoded(body=movement_body(low=0x5F25E4, high=VEHICLE_HIGH))[-1]
    deliver(bridge, vehicle)
    assert bridge.world.state.get("packet_flight") is None          # on foot: someone else's mover
    from wowbot.agent.models import Observation
    from test_packet_agent_bridge import addon
    bridge.world.ingest(Observation.create(addon(frame_id="v", in_vehicle=True), 9.5))
    deliver(bridge, replace(vehicle, event_id="b"*24, timestamp=vehicle.timestamp+.01))
    flight = bridge.world.state["packet_flight"]
    assert flight["vehicle_mover"] is True and flight["position"]["z"] == 31.75


def hover_state(*, x=0., y=0., z=284.3, facing=0., at=10.):
    position = {"x": x, "y": y, "z": z, "z_observed": True, "source": "PACKET_CLIENT_MOVEMENT",
                "sample_time": at, "instance_id": 2444, "coordinate_space": "WORLD_YARDS"}
    return {"in_vehicle": True, "movement": {"flying": True}, "orientation": facing,
            "player_world_position": position,
            "packet_flight": {"sample_time": at, "facing": facing, "flying": True, "vehicle_mover": True,
                              "position": position}}


def test_the_hover_control_climbs_descends_steers_and_arrives(fresh_couplings):
    fresh_couplings["vehicle"] = False           # a Steady-Flight seat: Jump climbs, Sit sinks
    control = HoverControl({"x": 50., "y": 0., "z": 270.}, 3.)
    (forward,) = control.commands(hover_state(), 0., 0., 0., 10.)
    assert forward.binding == "MOVEFORWARD" and "SITORSTAND" in forward.simultaneous
    climb = HoverControl({"x": 0., "y": 50., "z": 300.}, 3.)
    (turn,) = climb.commands(hover_state(), 0., 0., 0., 10.)
    # A climbing turn: Jump holds the lease, the turn rides along (valid lease).
    assert turn.binding == "JUMP" and turn.simultaneous == ("TURNLEFT",)
    # Judged on a sample taken after the last key's release.
    assert control.assess(hover_state(x=48., z=272., at=10.5), 0., 0., 10.5) == ("ARRIVED", "hover_arrived")
    assert control.assess(hover_state(x=48., z=284.3, at=10.5), 0., 0., 10.5)[0] == "MOVING"   # still too high


def test_climbing_turns_never_build_a_rejected_lease(tmp_path):
    from test_agent_core import Backend, binding_file
    from wowbot.agent.executor import InputExecutor
    from wowbot.agent.bindings import BindingsCache
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path, 'bind "X" "SITORSTAND"\n')), Backend())
    for target in ({"x": 0., "y": 50., "z": 300.}, {"x": 0., "y": 50., "z": 250.}, {"x": 50., "y": 0., "z": 300.}):
        for command in HoverControl(target, 3.).commands(hover_state(), 0., 0., 0., 10.):
            exe.execute_movement((command,))
    exe.stop_movement()


def unit(guid, x, y, z, entry=193994):
    return {"guid": guid, "kind": "CREATURE", "entry_id": entry, "map_id": 2444,
            "position": {"x": x, "y": y, "z": z, "sampled_at": 10., "source": "PACKET_CREATE_STATIONARY",
                         "coordinate_space": "WORLD_YARDS"}}


def test_tab_from_the_air_measures_in_three_dimensions():
    below = unit("Creature-0-1-2444-1-193994-1", 8., 0., 271.)            # in front, 15 yd away in 3D
    far_up = unit("Creature-0-1-2444-1-193994-2", 6., 1., 160.)           # flat-nearer, 124 yd below
    state = {**hover_state(), "packet_entities": {below["guid"]: below, far_up["guid"]: far_up}}
    assert tab_target_check(state, below["guid"]) == (False, "OTHER_FLOOR")    # the old flat rule
    assert tab_target_check(state, below["guid"], airborne=True)[0] is True


def test_the_whelp_hovers_above_and_short_of_the_nearest_weedling():
    weed = unit("Creature-0-1-2444-1-193994-1", 40., 0., 250.)
    state = {**hover_state(), "monotonic_time": 10., "packet_entities": {weed["guid"]: weed},
             "target": {}, "actionbar": []}
    units = [{**weed["position"], "guid": weed["guid"], "entry_id": 193994, "quest_id": "70061",
              "objective_id": "70061:1", "instance_id": 2444}]
    import wowbot.agent.vehicle_combat_planning as planning
    original = planning.kill_objective_units
    planning.kill_objective_units = lambda state: units
    try:
        (move,) = ServerVehicleCombatPolicy().propose(
            state, {"action": "ACTIONBUTTON1", "name": "Burning Bark", "max_range": 20, "id": 382778},
            cooling=False)
    finally:
        planning.kill_objective_units = original
    hover = move.parameters["hover_point"]
    assert move.skill == "MOVE" and hover["z"] == pytest.approx(256.) and hover["x"] == pytest.approx(34.)
    assert move.parameters["stop_distance"] == 3.


def test_a_vehicle_passenger_root_does_not_fail_the_vehicle_move():
    from wowbot.navigation.service import NavigationService
    nav = NavigationService()
    state = {**hover_state(), "movement_rooted": {"rooted": True, "sampled_at": 10.}, "monotonic_time": 10.}
    destination = {"x": 34., "y": 0., "coordinate_space": "WORLD_YARDS", "instance_id": 2444,
                   "hover_point": {"x": 34., "y": 0., "z": 256.}, "stop_distance": 3., "direct_flight": True}
    nav.start_skill_request("MOVE", destination, state, "o1", 10.)
    assert isinstance(nav._movement.flight, HoverControl)
    result = nav.observe(state, "o2", 10.2)
    assert not result.terminal, result
    commands = nav.command(state, "o2", 10.2)
    # Not yet known what Sit does on this seat: a short probe, flying on.
    assert commands and "MOVEFORWARD" in (commands[0].binding, *commands[0].simultaneous)


# -- live 2026-10-26 11:31-11:36: the whelp is steered by its pitch ----------

def pitched(*, pitch, at, x=0., y=0., z=284.3, facing=0.):
    state = hover_state(x=x, y=y, z=z, facing=facing, at=at)
    state["packet_flight"] = {**state["packet_flight"], "pitch": pitch}
    return state


def test_a_press_that_turns_the_pitch_makes_jump_and_sit_pitch_keys(fresh_couplings):
    control = HoverControl({"x": 40., "y": 0., "z": 300.}, 3.)
    (probe,) = control.commands(pitched(pitch=0., at=10.), 0., 0., 0., 10.)
    # Unknown seat: a short Jump press, forward riding along.
    assert probe.binding == "JUMP" and probe.duration == pytest.approx(.1) and "MOVEFORWARD" in probe.simultaneous
    # Measured: the press swung the pitch 0.31 rad (~3.1 rad/s) -> pitch keys.
    control.commands(pitched(pitch=.31, at=10.2), 0., 0., 0., 10.2)
    assert fresh_couplings["vehicle"] is True
    # Now the pitch is steered toward the climb angle (atan2(16, 40) = .38),
    # with a tap sized to the error, never toward the 90 degree stop.
    (tap,) = control.commands(pitched(pitch=0., at=10.4), 0., 0., 0., 10.4)
    assert tap.binding == "JUMP" and tap.duration == pytest.approx(min(.1, .38/3.1))
    (level,) = control.commands(pitched(pitch=.38, at=10.6), 0., 0., 0., 10.6)
    assert level.binding == "MOVEFORWARD" and not {"JUMP", "SITORSTAND"} & set(level.simultaneous)


def test_a_steep_climb_stops_short_of_the_vertical_stop(fresh_couplings):
    fresh_couplings["vehicle"] = True
    control = HoverControl({"x": 5., "y": 0., "z": 340.}, 3.)       # nearly straight above
    (tap,) = control.commands(pitched(pitch=1.1, at=10.), 0., 0., 0., 10.)
    assert tap.binding == "JUMP" and tap.duration <= .04 + 1e-9         # only to 1.2, not to 1.57
    (down,) = control.commands(pitched(pitch=1.5707, at=10.5), 0., 0., 0., 10.5)
    assert down.binding == "SITORSTAND"                                 # back from the stop


def test_each_tap_is_measured_before_the_next(fresh_couplings):
    fresh_couplings["vehicle"] = True
    control = HoverControl({"x": 40., "y": 0., "z": 230.}, 3.)
    (first,) = control.commands(pitched(pitch=.5, at=10.), 0., 0., 0., 10.)
    assert first.binding == "SITORSTAND"
    # The same stale sample a tick later: no second tap on top of the first.
    again = control.commands(pitched(pitch=.5, at=10.), 0., 0., 0., 10.07)
    assert not any(c.binding in {"JUMP", "SITORSTAND"} for c in again)
    # The pitch still far off (wanted -0.94): no thrust along the wrong pitch.
    assert not any("MOVEFORWARD" in (c.binding, *c.simultaneous) for c in again)


def test_arrival_faces_the_unit_and_aims_the_pitch_at_it(fresh_couplings):
    fresh_couplings["vehicle"] = True
    weed = {"x": 6., "y": 0., "z": 278.3}
    control = HoverControl({"x": 0., "y": 0., "z": 284.3}, 3., face=weed, aim=True)
    # At the hover point, facing away: not arrived (Tab would say NOT_FACING).
    assert control.assess(pitched(pitch=0., at=10., facing=math.pi), 0., 0., 10.) == ("MOVING", "hover_aim")
    (turn,) = control.commands(pitched(pitch=-.785, at=10., facing=math.pi), 0., 0., 0., 10.)
    assert turn.binding in {"TURNLEFT", "TURNRIGHT"}
    # Facing it, pitch level: aim down at it (atan2(-6, 6) = -0.785).
    (tap,) = control.commands(pitched(pitch=0., at=10.5, facing=0.), 0., 0., 0., 10.5)
    assert tap.binding == "SITORSTAND" and "MOVEFORWARD" not in tap.simultaneous
    assert control.assess(pitched(pitch=-.78, at=11., facing=0.), 0., 0., 11.) == ("ARRIVED", "hover_arrived")


def test_the_hovering_vehicles_last_pose_is_held(bridge):
    from test_packet_agent_bridge import addon
    from wowbot.agent.models import Observation
    bridge.world.ingest(Observation.create(addon(frame_id="v", in_vehicle=True), 9.5))
    vehicle = decoded(body=movement_body(low=0x5F25E4, high=VEHICLE_HIGH))[-1]
    deliver(bridge, vehicle)
    bridge.world.ingest(Observation.create(addon(frame_id="w", in_vehicle=True), 30.))
    state = bridge.world.state
    # 20 s without a packet: no fresh flight sample, but the held pose.
    assert state.get("packet_flight") is None
    assert state["packet_vehicle_pose"]["vehicle_mover"] is True
    assert state["packet_vehicle_pose"]["position"]["z"] == 31.75


BARK = {"action": "ACTIONBUTTON1", "name": "Burning Bark", "max_range": 20, "id": 382778,
        "source": "VEHICLE_BAR", "in_range": True}


def selected_weed_state(*, pitch):
    weed = unit("Creature-0-1-2444-1-193994-1", 6., 0., 278.3)
    state = {**pitched(pitch=pitch, at=10.), "monotonic_time": 10., "packet_entities": {weed["guid"]: weed},
             "target": {"guid": weed["guid"], "attackable": True, "dead": False}, "actionbar": [BARK],
             "vehicle_guid": "Vehicle-0-3769-2444-47-193979-00005824CC"}
    return state, [{**weed["position"], "guid": weed["guid"], "entry_id": 193994, "quest_id": "70061",
                    "objective_id": "70061:1", "instance_id": 2444}]


@pytest.mark.skipif(not __import__("wowbot.quests.client_catalog", fromlist=["x"]).ClientCatalog().path.is_file(),
                    reason="local client DB2 catalog missing")
def test_burning_bark_is_aimed_with_the_pitch_before_the_press(fresh_couplings, monkeypatch):
    import wowbot.agent.vehicle_combat_planning as planning
    fresh_couplings["193979"] = True
    state, units = selected_weed_state(pitch=1.34)            # live: +77 degrees, two misses
    monkeypatch.setattr(planning, "kill_objective_units", lambda state: units)
    (aim,) = ServerVehicleCombatPolicy().propose(state, BARK, cooling=False)
    assert aim.skill == "MOVE" and aim.parameters["purpose"] == "VEHICLE_AIM"
    assert aim.parameters["aim_pitch"] is True and aim.parameters["face_towards"]["z"] == pytest.approx(278.3)
    aimed, units = selected_weed_state(pitch=-.78)
    (press,) = ServerVehicleCombatPolicy().propose(aimed, BARK, cooling=False)
    assert press.skill == "VEHICLE_ABILITY" and press.parameters["use_mode"] == "TARGETED"


def test_a_landed_flying_vehicle_still_flies_and_boarding_waits_for_its_packets():
    from wowbot.agent.vehicle_combat_planning import flying
    landed = {"in_vehicle": True, "movement": {"flying": False},
              "packet_vehicle_pose": {"position": {"x": 0., "y": 0., "z": 286.}, "flying": False, "can_fly": True}}
    assert flying(landed) is True
    boarded = {"in_vehicle": True, "monotonic_time": 10., "movement": {"flying": False}, "target": {},
               "player_world_position": {"x": 0., "y": 0., "instance_id": 2444}, "actionbar": []}
    (wait,) = ServerVehicleCombatPolicy().propose(boarded, BARK, cooling=False)
    assert wait.skill == "WAIT" and wait.parameters["waiting_for"] == ["VEHICLE_MOVER_PACKET"]


def test_right_after_boarding_the_walks_own_sample_is_not_the_vehicles():
    from wowbot.agent.hover_control import vehicle_sample
    walk = {"position": {"x": 1570.7, "y": -219.2, "z": 311.2}, "sample_time": 10., "vehicle_mover": False,
            "flying": False, "can_fly": False}
    assert vehicle_sample({"in_vehicle": True, "packet_flight": walk}, 10.2) == {}
    assert vehicle_sample({"in_vehicle": False, "packet_flight": walk}, 10.2) == walk


def test_an_approach_ends_as_soon_as_its_unit_is_tab_ready():
    """Live 13:41-13:57: the unit was Tab-ready in 12 % of the samples but a
    long approach ran on; the agent Tabbed 4 times in 16 minutes."""
    weed = unit("Creature-0-1-2444-1-193994-1", 12., 0., 280.)           # in front, ~12.7 yd
    state = {**hover_state(), "packet_entities": {weed["guid"]: weed}, "target": {}}
    control = HoverControl({"x": 40., "y": 0., "z": 286.}, 3., tab_guid=weed["guid"])
    assert control.assess(state, 0., 0., 10.) == ("ARRIVED", "hover_tab_ready")
    behind = {**state, "packet_flight": {**state["packet_flight"], "facing": math.pi}, "orientation": math.pi}
    assert HoverControl({"x": 40., "y": 0., "z": 286.}, 3., tab_guid=weed["guid"]).assess(
        behind, 0., 0., 10.)[0] == "MOVING"
    selected = {**state, "target": {"guid": weed["guid"]}}                # already selected: fly on
    assert HoverControl({"x": 40., "y": 0., "z": 286.}, 3., tab_guid=weed["guid"]).assess(
        selected, 0., 0., 10.)[0] == "MOVING"
