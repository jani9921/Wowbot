"""Real WorldModel/runtime boundary, with synthetic packets and no OS input."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from wowbot.agent.models import Observation, Mode
from wowbot.agent.observation_ingestion import ObservationIngestion
from wowbot.agent.runtime_packet_source import RuntimePacketSource
from wowbot.agent.world import WorldModel
from wowbot.packetio.context import same_player
from wowbot.packetio.inbox import PacketEventInbox
from wowbot.packetio.ipc import canonical, envelope
from test_packet_codecs import decoded, movement_body, packed_guid


def addon(**changes):
    return {"session_id": "live-s", "character_guid": "Player-1602-00001234", "game_build": "69587",
        "frame_id": "addon:9", "timestamp": 9., "monotonic_time": 9., "map_id": 1409,
        "phase": "world", "player_present": True, "orientation": .25,
        "player_world_position": {"coordinate_space": "WORLD_YARDS", "x": 1., "y": 2., "z": 3.,
                                  "instance_id": 2175, "source": "ADDON", "z_known": True},
        "active_quests": [{"quest_id": 55639, "title": "Current quest", "is_complete": False,
            "objectives": [{"objective_id": "55639:0", "type": "KILL", "current": 0, "total": 1}]}], **changes}


@pytest.fixture
def bridge(tmp_path):
    world = WorldModel()
    world.ingest(Observation.create(addon(), 9.))
    inbox = PacketEventInbox(77, port=0, autostart=False, clock=lambda: 10., wall_clock=lambda: 1000.)
    adapter = RuntimePacketSource(77, tmp_path, source=inbox, wall_clock=lambda: 999.)
    adapter.observations(None, world, 10.)
    yield SimpleNamespace(world=world, inbox=inbox, adapter=adapter, path=tmp_path/"packet_endpoint.json")
    adapter.close()


def deliver(fixture, event, *, at=10., defer=False):
    descriptor = json.loads(fixture.path.read_text())
    assert fixture.inbox.ingest_datagram(canonical(envelope(event.to_dict(), descriptor)))
    observations = fixture.adapter.observations(None, fixture.world, at)
    assert len(observations) == 1
    if defer:
        return ObservationIngestion.ingest(fixture.world, None, observations)
    assert fixture.world.ingest(observations[0])
    return observations[0]


def test_confirmed_same_player_movement_preserves_addon_map_instance_and_health(bridge):
    before = dict(bridge.world.addon_state)
    deliver(bridge, decoded()[-1])
    state = bridge.world.state
    assert state["player_world_position"]["z"] == 31.75
    assert state["player_world_position"]["instance_id"] == 2175 and state["map_id"] == 1409
    assert state["player_world_position"]["sample_time"] == 10. and state["orientation"] == 1.5
    assert bridge.world.addon_state == before
    point = bridge.world.evidence["player_world_position"][-1].value
    assert point["coordinate_space"] == "WORLD_YARDS" and point["instance_id"] == 2175
    assert bridge.world.evidence["orientation"][-1].value == 1.5
    assert bridge.world.last_received == 9.  # packet receipt is NOT addon liveness/input authority
    assert not bridge.world.fresh(20.)


@pytest.mark.parametrize("value", [decoded(body=movement_body(low=0x9999))[-1],
    decoded(body=movement_body(high=9<<58))[-1], decoded(body=movement_body(flags=0x40))[-1],
    decoded(body=movement_body(flags=0x80))[-1], decoded("SMSG_MOVE_TELEPORT", packed_guid()+bytes(4)+bytes(16))[-1]])
def test_other_mover_vehicle_transport_or_inbound_teleport_cannot_move_player(bridge, value):
    deliver(bridge, value)
    assert bridge.world.state["player_world_position"]["z"] == 3.
    assert bridge.world.state["orientation"] == .25


def test_newer_addon_world_sample_wins_and_packet_expires_back_to_addon(bridge):
    deliver(bridge, decoded()[-1])
    changed = addon(frame_id="addon:11", timestamp=11., monotonic_time=11., transport_kind="FAST")
    bridge.world.ingest(Observation.create(changed, 11.), defer_rebuild=True)
    bridge.world.flush_pending()
    assert bridge.world.state["player_world_position"]["source"] == "ADDON"
    assert bridge.world.state["orientation"] == .25
    assert "_packet_navigation" not in bridge.world.__dict__


def test_packet_ttl_expires_on_perception_without_relabeling_addon_freshness(bridge):
    deliver(bridge, decoded()[-1])
    bridge.world.ingest(Observation.create({"session_id": "live-s", "frame_id": "cv:12",
        "timestamp": 12., "visual_candidates": []}, 12., "WORLD3D"))
    assert bridge.world.state["player_world_position"]["z"] == 3.
    assert bridge.world.last_received == 9.


def test_packet_completion_updates_real_quest_but_does_not_turn_in_or_accept(bridge):
    import struct
    value = decoded("SMSG_QUEST_UPDATE_COMPLETE", struct.pack("<I", 55639)+b"\x80")[-1]
    deliver(bridge, value)
    record = bridge.world.quest_model.records[55639]
    assert record.current_state == "COMPLETED"
    assert any(e.event_type == "QUEST_COMPLETED" for e in bridge.world.event_records)
    assert not any(e.event_type == "QUEST_TURNED_IN" for e in bridge.world.event_records)
    assert not bridge.world.owned_corpse_guids


def test_unknown_unverified_or_wrong_build_event_stays_only_weak_diagnostic(bridge):
    value = decoded()[-1]
    value = replace(value, provenance={**value.provenance, "game_build": 69214})
    deliver(bridge, value)
    assert bridge.world.state["player_world_position"]["z"] == 3.
    assert bridge.world.state["packet_telemetry"]["semantic_verified"] is False
    assert not any(e.event_type == "MOVEMENT_UPDATE" for e in bridge.world.event_records)


@pytest.mark.parametrize("change", [{"session_id": "next"}, {"character_guid": "Player-1602-9999"},
    {"instance_id": 0}, {"phase": "other"}, {"loading": True}, {"game_build": "69588"}])
def test_context_change_discards_queued_data_instead_of_rebinding_it(bridge, change):
    if "instance_id" in change:
        change = {"player_world_position": {**addon()["player_world_position"], **change}}
    descriptor = json.loads(bridge.path.read_text())
    assert bridge.inbox.ingest_datagram(canonical(envelope(decoded()[-1].to_dict(), descriptor)))
    assert bridge.adapter.observations(addon(**change), bridge.world, 10.) == ()
    assert bridge.inbox.poll() == []
    assert not bridge.inbox.ingest_datagram(canonical(envelope(decoded(timestamp=1000.01)[-1].to_dict(), descriptor)))


def test_a_ui_map_step_in_the_same_world_keeps_the_transport_and_its_queued_movement(bridge):
    """Live 2026-10-31 02:09-02:12 (Fargodeep Mine): the UI map flipped 37/39;
    each flip took a new transport nonce and dropped every in-flight own
    movement packet. A UI map is no world/session/phase identity."""
    descriptor = json.loads(bridge.path.read_text())
    assert bridge.inbox.ingest_datagram(canonical(envelope(decoded()[-1].to_dict(), descriptor)))
    (observation,) = bridge.adapter.observations(addon(map_id=84), bridge.world, 10.)
    assert json.loads(bridge.path.read_text())["context"] == descriptor["context"]      # same nonce
    bridge.world.ingest(Observation.create(addon(frame_id="addon:map", map_id=84), 9.5))
    assert bridge.world.ingest(observation)
    position = bridge.world.state["player_world_position"]
    assert position["z"] == 31.75 and position["source"] == "PACKET_CLIENT_MOVEMENT" and bridge.world.state["map_id"] == 84


def test_discrete_attack_stop_death_does_not_grant_our_loot_or_corpse_anchor(bridge):
    value = decoded("SMSG_ATTACK_STOP", packed_guid()+packed_guid(0x9999, 8<<58)+b"\x80")[-1]
    deliver(bridge, value)
    assert any(e.event_type == "ATTACK_STOPPED" for e in bridge.world.event_records)
    assert not bridge.world.owned_corpse_guids and not bridge.world.corpse_anchors


def test_packet_observations_do_not_enter_hot_loop_sqlite_but_events_remain(bridge):
    result = deliver(bridge, decoded()[-1], defer=True)
    assert result.durable == ()
    assert bridge.world.state["player_world_position"]["source"] == "PACKET_CLIENT_MOVEMENT"
    assert any(obs.source == "PACKET_TELEMETRY" for obs in bridge.world.history)


@pytest.mark.parametrize("raw", [None, 12345678901234567890123456789012, "wrong", "0"*32])
def test_invalid_guid_never_becomes_self(raw):
    assert not same_player(raw, "Player-1602-00001234")


def test_optional_sensor_failure_does_not_block_observations_or_expose_endpoint_key(tmp_path):
    world = WorldModel()
    world.ingest(Observation.create(addon(), 9.))
    source = SimpleNamespace(configure=lambda _: {}, poll=lambda **_: (_ for _ in ()).throw(OSError("secret")),
                             diagnostics=lambda: {}, close=lambda: None)
    adapter = RuntimePacketSource(77, tmp_path, source=source)
    assert adapter.observations(None, world, 10.) == ()
    assert adapter.error == "packet_sensor_failed" and "secret" not in str(adapter.diagnostics())
    adapter.close()


def test_runtime_integrates_injected_sensor_without_starting_game_capture(tmp_path):
    from test_agent_runtime import Sensor
    from test_agent_core import binding_file
    from wowbot.agent.executor import RecordingExecutor
    from wowbot.agent.runtime import AgentRuntime
    sensor = Sensor()
    inbox = PacketEventInbox(77, port=0, autostart=False, clock=lambda: 10., wall_clock=lambda: 1000.)
    runtime = AgentRuntime(77, binding_file(tmp_path), tmp_path/"out", sensor=sensor,
        executor=RecordingExecutor(), vision=False, packet_source=inbox)
    runtime.packet_telemetry.wall_clock = lambda: 999.
    try:
        sensor.payload = addon()
        runtime.step(9.)
        descriptor = json.loads(runtime.packet_telemetry.path.read_text())
        assert inbox.ingest_datagram(canonical(envelope(decoded()[-1].to_dict(), descriptor)))
        result = runtime.step(10.)
        assert runtime.agent.world.state["player_world_position"]["z"] == 31.75
        assert result["packet_telemetry"]["received"] == 1
        assert runtime.agent.mode == Mode.MANUAL and runtime.executor.commands == []
    finally:
        runtime.close()
    assert json.loads(runtime.packet_telemetry.path.read_text())["status"] == "closed"


@pytest.mark.parametrize("build", [70340, 70391])
def test_12_1_5_build_configures_endpoint_and_reaches_existing_world_reducer(bridge, build):
    bridge.world.ingest(Observation.create(addon(game_build=str(build), frame_id="addon:next"), 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)
    descriptor = json.loads(bridge.path.read_text())
    assert descriptor["context"]["game_build"] == build
    deliver(bridge, decoded(build=build)[-1])
    assert bridge.world.state["player_world_position"]["z"] == 31.75
    assert bridge.adapter.diagnostics()["observed_game_build"] == build
    assert bridge.adapter.diagnostics()["context_status"] == "ready"


def test_unreviewed_build_reports_real_blocker_not_generic_context_wait(bridge):
    bridge.adapter.observations(addon(game_build="70392"), bridge.world, 10.)
    status = bridge.adapter.diagnostics()
    assert status["status"] == "unsupported_game_build"
    assert status["observed_game_build"] == 70392 and status["game_build"] is None
    assert json.loads(bridge.path.read_text())["context"] is None


def test_reconnect_context_does_not_show_old_receipt_as_new_data(bridge):
    deliver(bridge, decoded()[-1])
    assert bridge.inbox.diagnostics()["last_received_at"] == 10.
    bridge.adapter.observations(addon(session_id="new-session"), bridge.world, 10.)
    assert bridge.inbox.diagnostics()["last_received_at"] is None


@pytest.mark.parametrize("wrong", [{"opcode_defining_build": 69214},
    {"opcode_table_sha256": "5e4387ac682620c7ca45013fa554ad14ca8e619d8a9fe45ce5ceb8f33519ef2c"}])
def test_12_1_5_cannot_reuse_old_family_provenance(bridge, wrong):
    bridge.world.ingest(Observation.create(addon(game_build="70391", frame_id="addon:new-build"), 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)
    value = decoded(build=70391)[-1]
    deliver(bridge, replace(value, provenance={**value.provenance, **wrong}))
    assert bridge.world.state["player_world_position"]["source"] == "ADDON"
    assert bridge.world.state["packet_telemetry"]["semantic_verified"] is False
