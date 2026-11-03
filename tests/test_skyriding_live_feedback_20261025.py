"""Live 15:14/15:18 regression: jump, then no pitch/speed/height in control."""
from copy import deepcopy
from dataclasses import replace

import pytest

from test_packet_agent_bridge import addon, bridge, deliver
from test_packet_codecs import decoded
from test_active_pointer_tracking import attempt
from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.fast_movement_lane import advance_fast_movement
from wowbot.agent.models import Mode, Observation
from wowbot.agent.parallel_view import control_safety
from wowbot.agent.skyriding_control import SkyridingControl


def flying_event():
    event = decoded()[-1]
    return replace(event, payload={**event.payload, "pitch": -.3, "adv_flying": True,
                                  "forward_velocity": 45., "up_velocity": -2.})


def start_flight(fixture, *, airborne=True):
    fixture.world.ingest(Observation.create(addon(
        frame_id="mounted", is_mounted=True,
        movement={"flying": airborne, "falling": False}), 9.))
    if airborne:
        deliver(fixture, flying_event())
    executor = RecordingExecutor()
    agent = AutonomousAgent(executor)
    agent.world = fixture.world
    agent.set_mode(Mode.FULL_AI)
    position = agent.world.state["player_world_position"]
    destination = {"coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                   "map_id": 1409, "x": position["x"]+100, "y": position["y"], "z": position["z"]+30,
                   "flight_path": {"mode": "SKYRIDING", "instance_id": 2175,
                        "waypoints": [{"x": position["x"]+100, "y": position["y"], "z": position["z"]+30}],
                        "landing": {"x": position["x"]+200, "y": position["y"], "z": position["z"]}},
                   "purpose": "SKYRIDING_COURSE"}
    agent.pending = attempt("MOVE", destination)
    agent.navigation.start_skill_request("MOVE", destination, agent.world.state, "start", 10.)
    agent.parallel_control.enabled = True
    return agent, executor


def fast_sample(agent, at, sequence, *, airborne=True, falling=False):
    payload = deepcopy(agent.world.addon_state)
    payload.update(monotonic_time=at, timestamp=at, transport_kind="FAST", fast_sequence=sequence,
                   frame_id=f"fast:{sequence}", is_mounted=True,
                   movement={"flying": airborne, "falling": falling})
    point = payload["player_world_position"]
    # The actual addon FAST sample contains XY but no player height.
    payload["player_world_position"] = {k: v for k, v in point.items() if k != "z"}
    payload["player_world_position"].update(z_known=False, z_observed=False, sample_time=at)
    return payload


def test_confirmed_flight_feedback_is_projected_into_the_canonical_state(bridge):
    deliver(bridge, flying_event())
    flight = bridge.world.state.get("packet_flight")
    assert flight is not None
    assert flight["sample_time"] == 10. and flight["pitch"] == -.3
    assert flight["forward_velocity"] == 45. and flight["up_velocity"] == -2.
    assert flight["position"]["z"] == 31.75
    assert flight["position"]["sample_time"] == 10.
    assert flight["facing"] == 1.5


def test_newer_addon_xy_does_not_erase_other_sensor_flight_measurements(bridge):
    deliver(bridge, flying_event())
    point = dict(bridge.world.state["player_world_position"])
    point.pop("z")
    bridge.world.ingest(Observation.create(addon(
        frame_id="fast:10.2", monotonic_time=10.2, timestamp=10.2, transport_kind="FAST",
        player_world_position={**point, "x": point["x"]+4, "sample_time": 10.2, "z_known": False}), 10.2))
    flight = bridge.world.state.get("packet_flight")
    assert flight is not None and flight["sample_time"] == 10.
    assert flight["position"]["z"] == 31.75


@pytest.mark.parametrize("change", [{"monotonic_time": 12., "timestamp": 12.},
                                    {"character_guid": "Player-1602-12345678"},
                                    {"session_id": "another-session"}, {"phase": "other-phase"},
                                    {"loading": True}])
def test_stale_or_wrong_context_feedback_cannot_remain_active(bridge, change):
    deliver(bridge, flying_event())
    bridge.world.ingest(Observation.create(addon(frame_id="changed", **change), 12. if "timestamp" in change else 10.2))
    assert bridge.world.state.get("packet_flight") is None


def test_a_ui_map_step_in_the_same_world_keeps_the_flight_feedback(bridge):
    # Live 2026-10-31 (Fargodeep): a UI-map step is no world/session/phase change.
    deliver(bridge, flying_event())
    bridge.world.ingest(Observation.create(addon(frame_id="changed", map_id=84), 10.2))
    assert bridge.world.state.get("packet_flight") is not None


@pytest.mark.parametrize("lane", ["parallel", "fast"])
def test_real_control_chain_steers_with_xy_only_fast_sample_and_fall_flag(bridge, lane):
    agent, executor = start_flight(bridge)
    payload = fast_sample(agent, 10.2, 1, falling=True)
    before = deepcopy(agent.world.state)
    if lane == "parallel":
        result = agent.parallel_control.tick(payload, 10.2, None, 10.2)
    else:
        result = advance_fast_movement(agent, payload, 10.2, {"MOVE"})
    assert result.get("consumed") and result.get("dispatched"), result
    assert any(c.binding in {"PITCHUP", "PITCHDOWN"} or
               set(c.simultaneous) & {"PITCHUP", "PITCHDOWN"} for c in executor.commands)
    assert agent.world.state == before  # projection is read-only, no second state writer
    assert agent.pending.action_id == "a"


def test_takeoff_can_issue_the_second_jump_without_addon_player_height(bridge):
    agent, executor = start_flight(bridge, airborne=False)
    for sequence, at in enumerate([10., 10.5]):
        result = agent.parallel_control.tick(fast_sample(
            agent, at, sequence, airborne=False, falling=sequence > 0), at, None, at)
        assert result.get("dispatched"), result
    assert [c.binding for c in executor.commands] == ["JUMP", "JUMP"]


def test_ordinary_ground_falling_still_revokes_fast_input():
    base = addon(is_mounted=True, movement={"falling": True})
    assert control_safety(base, base, 9., 9.) == "fall_transition"


@pytest.mark.parametrize("change", [{"is_mounted": False}, {"in_vehicle": True},
                                    {"on_taxi": True}, {"is_dead": True}, {"is_ghost": True}])
def test_flight_route_does_not_remove_other_control_authority_gates(bridge, change):
    agent, _ = start_flight(bridge)
    current = {**agent.world.state, **change}
    assert not agent.navigation.flight_controls_allowed(current)


def test_fast_control_reports_missing_feedback_without_issuing_blind_steering(bridge):
    agent, executor = start_flight(bridge)
    result = agent.parallel_control.tick(fast_sample(agent, 12., 1), 12., None, 12.)
    assert result.get("consumed") and not result.get("dispatched")
    assert result["reason"] == "skyriding_waiting_for_flight_feedback"
    assert executor.commands == []


def test_future_flight_sample_is_not_usable_feedback():
    from wowbot.navigation.flight_path import FlightPath
    flight = SkyridingControl(FlightPath.from_dict({"mode": "SKYRIDING", "instance_id": 2175, "waypoints": [], "landing": {"x":10,"y":0,"z":10}}))
    assert flight._flight({"packet_flight": {"sample_time": 11., "pitch": .5}}, 10.) is None
