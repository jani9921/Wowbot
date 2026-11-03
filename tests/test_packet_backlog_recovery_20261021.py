"""Portable startup-backlog recovery; authenticated loopback IPC, no game input."""
from dataclasses import replace
import json
import struct

import pytest

from wowbot.agent.models import Observation
from wowbot.agent.runtime_packet_source import RuntimePacketSource
from wowbot.agent.world import WorldModel
from wowbot.packetio.forwarder import EntitySnapshot, EventPolicy, SnapshotReplayForwarder
from wowbot.packetio.inbox import PacketEventInbox
from wowbot.packetio.ipc import canonical, envelope
from test_packet_codecs import decoded
from test_packet_entities import UPDATES, addon, decoder, update_events


class Delivery:
    """Same descriptor/authentication/age boundary, without UDP scheduling."""
    def __init__(self, path, inbox):
        self.path, self.inbox, self.sent = path, inbox, []

    def descriptor(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def context_id(self):
        return self.descriptor()["context"]["context_id"]

    def entity_snapshot_request(self):
        return self.descriptor().get("entity_snapshot_request", 0)

    def emit(self, event):
        value = EventPolicy().prepare(event)
        if value is None:
            return False
        self.sent.append(event)
        return self.inbox.ingest_datagram(canonical(envelope(value, self.descriptor())))


@pytest.fixture
def setup(tmp_path):
    clock = {"wall": 1000., "mono": 10.}
    world = WorldModel()
    world.ingest(Observation.create(addon(), 9.))
    inbox = PacketEventInbox(77, port=0, autostart=False,
        wall_clock=lambda: clock["wall"], clock=lambda: clock["mono"])
    adapter = RuntimePacketSource(77, tmp_path, source=inbox, wall_clock=lambda: 999.)
    adapter.observations(None, world, 10.)
    delivery = Delivery(adapter.path, inbox)
    sink = SnapshotReplayForwarder(delivery, wall_clock=lambda: clock["wall"])
    yield clock, world, inbox, adapter, delivery, sink
    adapter.close()


def creates():
    source = decoder()
    # These calls model frames of one capture, not a fresh worker per frame.
    # Set it before decode so event IDs and their common evidence root agree.
    source.capture_epoch = 'd'*32
    return update_events(source, "SMSG_UPDATE_OBJECT", UPDATES["create_door_vehicle_creatures"])


def heartbeat(at):
    # Unknown diagnostic triggers the existing snapshot lifecycle, but itself
    # can never enter the allowlisted runtime stream.
    return replace(decoded(build=70448)[0], timestamp=at)


def test_eight_second_startup_backlog_requests_fresh_snapshot_then_reaches_world(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    for event in creates():
        assert sink.emit(event)
    before = delivery.descriptor()
    clock.update(wall=1008., mono=18.)
    assert adapter.observations(None, world, 18.) == ()
    assert not world.state.get("packet_entities")
    status = adapter.diagnostics()
    assert status["stale_entity_discards"] == len(creates())
    assert status["entity_snapshot_requests"] == 1 and status["observations_emitted"] == 0
    after = delivery.descriptor()
    assert after["context"] == before["context"] and after["ipc_key"] == before["ipc_key"]
    assert after["entity_snapshot_request"] == 1
    # The producer retained current create facts; it sends a *new* snapshot
    # in the same authenticated context, not a restamped stale inbox event.
    sink.emit(heartbeat(1008.))
    observations = adapter.observations(None, world, 18.)
    assert len(observations) == len(creates())
    for observation in observations:
        assert world.ingest(observation)
    assert len(world.state["packet_entities"]) == len(creates())
    assert adapter.diagnostics()["observations_emitted"] == len(creates())
    assert not adapter.error


@pytest.mark.parametrize("event", [
    decoded(build=70448)[-1],
    decoded("SMSG_QUEST_UPDATE_COMPLETE", struct.pack("<I", 55639) + b"\x80", build=70448)[-1],
])
def test_old_movement_and_quest_credit_are_dropped_not_restamped_or_replayed(setup, event):
    clock, world, inbox, adapter, delivery, sink = setup
    assert sink.emit(event)
    clock.update(wall=1008., mono=18.)
    assert adapter.observations(None, world, 18.) == ()
    assert adapter.diagnostics()["stale_event_discards"] == 1
    assert adapter.diagnostics()["entity_snapshot_requests"] == 0
    assert world.state["player_world_position"]["source"] != "PACKET_CLIENT_MOVEMENT"
    assert not sink.snapshot.entities


def test_snapshot_revision_retries_are_bounded_and_do_not_clear_discrete_queue(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    event = decoded(build=70448)[-1]
    assert sink.emit(event)
    queued = len(inbox.poll())
    assert queued == 1
    # Fill again with a new event ID; same-context configure must not consume it.
    assert sink.emit(replace(event, event_id="b" * 24))
    adapter._request_entity_snapshot(10.)
    assert inbox.diagnostics()["queued"] == 1
    adapter._request_entity_snapshot(10.5)
    assert adapter.entity_snapshot_requests == 1
    adapter._request_entity_snapshot(10.+adapter.SNAPSHOT_RETRY_SECONDS)
    assert adapter.entity_snapshot_requests == 2


def test_new_snapshot_never_revives_an_entity_removed_from_producers_cache(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    original = creates()[0]
    assert sink.emit(original)
    for observation in adapter.observations(None, world, 10.):
        assert world.ingest(observation)
    removed = replace(original, event_id="c" * 24, event_type="ENTITY_REMOVED",
        payload={"entity_guid": original.payload["entity_guid"], "entry_id": original.payload["entry_id"],
                 "removal": "OUT_OF_RANGE"})
    assert sink.emit(removed)
    clock.update(wall=1008., mono=18.)
    assert adapter.observations(None, world, 18.) == ()
    count = len(delivery.sent)
    sink.emit(heartbeat(1008.))
    assert len(delivery.sent) == count + 1
    assert delivery.sent[-1].event_type == "ENTITY_REMOVED" and delivery.sent[-1].timestamp == 1008.
    for observation in adapter.observations(None, world, 18.):
        assert world.ingest(observation)
    assert all(entity.get("removed") for entity in world.state["packet_entities"].values())


def test_failed_recovery_descriptor_write_does_not_break_the_packet_sensor(setup, monkeypatch):
    clock, world, inbox, adapter, delivery, sink = setup
    for event in creates():
        sink.emit(event)
    clock.update(wall=1008., mono=18.)
    def fail(*args, **kwargs):
        raise OSError("private error text must not be exposed")
    monkeypatch.setattr("adapters.atomic_file.write_json_replace", fail)
    assert adapter.observations(None, world, 18.) == ()
    status = adapter.diagnostics()
    assert status["entity_snapshot_request_error"] == "entity_snapshot_request_failed"
    assert adapter.error is None and "private error" not in str(status)


def test_repeat_revision_does_not_repeat_the_snapshot(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    for event in creates():
        sink.emit(event)
    adapter._request_entity_snapshot(10.)
    sink.emit(heartbeat(1000.))
    count = len(delivery.sent)
    sink.emit(heartbeat(1000.))
    assert len(delivery.sent) == count


def test_failed_snapshot_request_is_retried_after_cooldown_even_with_empty_inbox(setup, monkeypatch):
    clock, world, inbox, adapter, delivery, sink = setup
    for event in creates():
        sink.emit(event)
    clock.update(wall=1008., mono=18.)
    from adapters.atomic_file import write_json_replace
    def fail(*args, **kwargs):
        raise OSError("offline fault")
    monkeypatch.setattr("adapters.atomic_file.write_json_replace", fail)
    assert adapter.observations(None, world, 18.) == ()
    assert adapter.diagnostics()["entity_snapshot_request_pending"]
    monkeypatch.setattr("adapters.atomic_file.write_json_replace", write_json_replace)
    clock.update(wall=1013., mono=23.)
    assert adapter.observations(None, world, 23.) == ()
    assert adapter.entity_snapshot_requests == 1
    assert not adapter.diagnostics()["entity_snapshot_request_pending"]


def test_a_clock_edge_does_not_trigger_a_stale_entity_replay_storm(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    for event in creates():
        sink.emit(event)
    assert adapter.observations(None, world, 9.99) == ()
    assert adapter.diagnostics()["invalid_time_discards"] == len(creates())
    assert adapter.entity_snapshot_requests == 0


def test_late_flags_never_resurrect_a_removed_entity_in_a_requested_snapshot(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    original = creates()[0]
    snapshot = EntitySnapshot()
    snapshot.note(original)
    removed = replace(original, event_type="ENTITY_REMOVED",
        payload={"entity_guid": original.payload["entity_guid"], "entry_id": original.payload["entry_id"],
                 "removal": "OUT_OF_RANGE"})
    snapshot.note(removed)
    snapshot.note(replace(original, event_type="ENTITY_FLAGS", payload={
        "entity_guid": original.payload["entity_guid"], "dynamic_flags": 0}))
    assert [event.event_type for event in snapshot.replay(1008.)] == ["ENTITY_REMOVED"]
    snapshot.note(original)
    assert [event.event_type for event in snapshot.replay(1008.)] == ["ENTITY_CREATED"]

