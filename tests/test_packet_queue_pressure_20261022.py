"""Authenticated synthetic pressure tests; no sniffer, game or input."""
from dataclasses import replace
import struct

from test_packet_backlog_recovery_20261021 import setup, creates, heartbeat
from test_packet_codecs import decoded


def entity(index, *, kind="ENTITY_CREATED", stamp=1000.):
    original = creates()[0]
    payload = {**original.payload, "entity_guid": original.payload["entity_guid"][:16]+f"{index:016X}"}
    if kind == "ENTITY_REMOVED":
        payload = {"entity_guid": payload["entity_guid"], "entry_id": payload["entry_id"], "removal": "OUT_OF_RANGE"}
    if kind == "ENTITY_FLAGS":
        payload = {"entity_guid": payload["entity_guid"], "entry_id": payload["entry_id"], "dynamic_flags": index}
    return replace(original, event_type=kind, event_id=f"{index+10000:024x}", timestamp=stamp, payload=payload)


def test_repeated_entity_state_does_not_fill_the_discrete_fifo(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    for index in range(1500):
        event = entity(7, kind="ENTITY_FLAGS")
        assert sink.emit(replace(event, event_id=f"{index+30000:024x}",
                                 payload={**event.payload, "dynamic_flags": index}))
    quest = decoded("SMSG_QUEST_UPDATE_COMPLETE", struct.pack("<I", 55639)+b"\x80", build=70448)[-1]
    assert sink.emit(quest)
    records = inbox.poll()
    assert [e["event_type"] for e in records] == ["ENTITY_FLAGS", "QUEST_COMPLETED"]
    assert records[0]["payload"]["dynamic_flags"] == 1499
    assert inbox.diagnostics()["dropped"] == 0
    assert inbox.diagnostics()["coalesced"] >= 1499


def test_a_thousand_stale_states_cannot_hide_a_fresh_entity(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    for index in range(1000):
        assert sink.emit(entity(index))
    clock.update(wall=1003., mono=13.)
    assert sink.emit(entity(2000, stamp=1003.))
    result = adapter.observations(None, world, 13.)
    assert len(result) == 1
    assert result[0].payload["packet_event"]["payload"]["entity_guid"].endswith(f"{2000:016X}")
    assert adapter.stale_entity_discards == 1000
    assert adapter.entity_snapshot_requests == 1
    assert inbox.diagnostics()["queued"] == 0


def test_replay_is_paced_and_reads_current_cache_at_send_time(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    for index in range(300):
        sink.snapshot.note(entity(index))
    sink.emit(heartbeat(1000.))
    assert len(delivery.sent) == sink.REPLAY_BATCH
    for _ in range(20):
        sink.emit(heartbeat(1000.))
    assert len(delivery.sent) == sink.REPLAY_BATCH
    victim = entity(200, kind="ENTITY_REMOVED")
    assert sink.emit(victim)
    for step in range(1, 8):
        clock.update(wall=1000.+step*.5, mono=10.+step*.5)
        sink.flush()
        adapter.observations(None, world, clock["mono"])
    assert not sink._pending_replay
    assert not any(e.event_type == "ENTITY_CREATED" and e.payload["entity_guid"] == victim.payload["entity_guid"]
                   for e in delivery.sent)
    assert all(abs(e.timestamp-1000.) <= 3.5 for e in delivery.sent)
    assert adapter.stale_entity_discards == 0


def test_resynchronization_has_backoff_and_a_finite_attempt_budget(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    for now in range(10, 100):
        adapter._request_entity_snapshot(float(now))
    assert adapter.entity_snapshot_requests == adapter.SNAPSHOT_MAX_ATTEMPTS == 3
    assert adapter.entity_snapshot_request_error == "snapshot_recovery_exhausted"


def test_remove_supersedes_create_and_late_flags_cannot_undo_it(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    sink.emit(entity(3))
    sink.emit(replace(entity(3, kind="ENTITY_REMOVED"), event_id="a"*24))
    sink.emit(replace(entity(3, kind="ENTITY_FLAGS"), event_id="b"*24))
    assert [e["event_type"] for e in inbox.poll()] == ["ENTITY_REMOVED"]


def test_unallowlisted_fields_cannot_gain_authority_during_coalescing(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    first = entity(5, kind="ENTITY_FLAGS")
    first = replace(first, payload={**first.payload, "npc_flags": 0x1000000})
    second = replace(entity(5, kind="ENTITY_FLAGS"), event_id="d"*24,
                     payload={**first.payload, "dynamic_flags": 4})
    second = replace(second, payload={k: v for k, v in second.payload.items() if k != "npc_flags"})
    sink.emit(first)
    sink.emit(second)
    (queued,) = inbox.poll()
    assert "npc_flags" not in queued["payload"]
    assert queued["payload"]["dynamic_flags"] == 4
    (remembered,) = sink.snapshot.replay(1000.)
    assert "npc_flags" not in remembered.payload
    assert remembered.payload["dynamic_flags"] == 4


def test_failed_descriptor_writes_also_spend_the_recovery_budget(setup, monkeypatch):
    clock, world, inbox, adapter, delivery, sink = setup
    def fail(*args, **kwargs):
        raise OSError("offline failure")
    monkeypatch.setattr("adapters.atomic_file.write_json_replace", fail)
    for now in (10., 15., 25., 45., 100.):
        adapter._request_entity_snapshot(now)
    assert adapter.entity_snapshot_requests == 0
    assert adapter._snapshot_attempts == 3
    assert adapter.entity_snapshot_request_error == "snapshot_recovery_exhausted"


def test_observed_healthy_stream_can_reset_a_spent_recovery_budget(setup):
    clock, world, inbox, adapter, delivery, sink = setup
    for now in (10., 15., 25., 45.):
        adapter._request_entity_snapshot(now)
    assert adapter._snapshot_attempts == 3
    for step in range(7):
        clock.update(wall=1040.+step, mono=50.+step)
        sink.emit(entity(500+step, stamp=clock["wall"]))
        adapter.observations(None, world, clock["mono"])
    assert adapter._snapshot_attempts == 0
    assert adapter.entity_snapshot_request_error is None
