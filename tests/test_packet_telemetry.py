"""Offline audited-port transport tests. No game input/capture dependencies."""
from collections import namedtuple
from dataclasses import replace
import json
import socket
import struct
import time

import pytest

from wowbot.packetio.models import AgentPacketEvent, FlowDirection, PidTcpFlow, RawPacket, StreamChunk, TcpSegment
from wowbot.packetio.decoder import OpaqueStreamDecoder, JsonLineSemanticDecoder
from wowbot.packetio.flows import PidFlowResolver
from wowbot.packetio.forwarder import EventPolicy, InMemorySink, JsonlEventRecorder, UdpJsonForwarder
from wowbot.packetio.inbox import PacketEventInbox
from wowbot.packetio.ipc import canonical, envelope
from wowbot.packetio.network import decode_tcp, PacketDecodeError
from wowbot.packetio.pipeline import PacketPipeline
from wowbot.packetio.reassembly import TcpStreamReassembler


FLOW = PidTcpFlow(77, "10.0.0.2", 50000, "10.0.0.9", 8085)
OUT = FlowDirection.CLIENT_TO_SERVER


def raw_tcp(payload, sequence=1000):
    tcp = struct.pack("!HHIIHHHH", 50000, 8085, sequence, 0, (5<<12)|0x18, 65535, 0, 0)+payload
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20+len(tcp), 1, 0, 64, 6, 0,
                     bytes((10, 0, 0, 2)), bytes((10, 0, 0, 9)))+tcp
    data = bytes(12)+b"\x08\x00"+ip
    return RawPacket(1000., 1, data, "offline", len(data), len(data))


def segment(sequence, payload, flags=0x18):
    return TcpSegment(1000., FLOW.local_ip, FLOW.local_port, FLOW.remote_ip, FLOW.remote_port,
                      sequence, 0, flags, payload)


def event(kind="MOVEMENT_UPDATE", *, timestamp=1000., pid=77, body=None):
    return AgentPacketEvent.create(pid=pid, flow_id="offline", direction=OUT, event_type=kind,
        timestamp=timestamp, semantic_status="CONFIRMED", payload=body or {"x": timestamp,
        "mover_guid": "00000000000000000000000000000001"})


def context(**changes):
    return {"selected_pid": 77, "runtime_id": "runtime", "context_id": "ctx", "session_id": "s",
        "character_guid": "Player-1-1234", "map_id": 1409, "instance_id": 2175,
        "game_build": 69587, "phase": "world", "started_wall": 999., **changes}


@pytest.fixture
def inbox():
    value = PacketEventInbox(77, port=0, autostart=False, clock=lambda: 10., wall_clock=lambda: 1000.)
    value.configure(context())
    yield value
    value.close()


def send(inbox, value, *, descriptor=None):
    descriptor = descriptor or inbox.configure(context())
    return inbox.ingest_datagram(canonical(envelope(value.to_dict() if hasattr(value, "to_dict") else value, descriptor)))


def test_pid_flow_and_pipeline_use_only_exact_owned_tuple():
    Address = namedtuple("Address", "ip port")
    Connection = namedtuple("Connection", "laddr raddr")
    resolver = PidFlowResolver(77, connection_provider=lambda: [Connection(
        Address(FLOW.local_ip, FLOW.local_port), Address(FLOW.remote_ip, FLOW.remote_port))])
    seg = decode_tcp(raw_tcp(b"hello"))
    assert resolver.match(seg, now=0)[1] == OUT  # first poll must not be skipped
    assert resolver.match(replace(seg, source_port=2), now=1.) is None
    sink = InMemorySink()
    pipeline = PacketPipeline(resolver, JsonLineSemanticDecoder(), sink)
    assert pipeline.handle(raw_tcp(b'{"event_type":"SPELL_CAST_FAILED","payload":{"reason":"OUT_OF_RANGE"}}\n')) == 1
    assert sink.events[0].provenance["semantic_ground_truth"] is False


def test_pid_resolver_drops_cached_ownership_on_query_failure():
    resolver = PidFlowResolver(77, connection_provider=lambda: [])
    resolver.refresh(0)
    resolver._flows[(FLOW.local_ip, FLOW.local_port, FLOW.remote_ip, FLOW.remote_port)] = FLOW
    resolver.connection_provider = lambda: (_ for _ in ()).throw(RuntimeError("denied"))
    with pytest.raises(RuntimeError):
        resolver.refresh(1)
    assert not resolver.flows


def test_reassembly_handles_overlap_retransmission_wrap_and_reconnect():
    reassembler = TcpStreamReassembler()
    assert reassembler.feed(segment(0xFFFFFFFA, b"abc"), FLOW, OUT).payload == b"abc"
    assert reassembler.feed(segment(0, b"ghi"), FLOW, OUT) is None
    assert reassembler.feed(segment(0xFFFFFFFD, b"defg"), FLOW, OUT).payload == b"defghi"
    assert reassembler.feed(segment(0, b"ghi"), FLOW, OUT) is None
    assert reassembler.feed(segment(100, b"new", flags=2), FLOW, OUT).payload == b"new"
    assert reassembler.feed(segment(104, b"end", flags=1), FLOW, OUT).payload == b"end"
    assert not reassembler._streams


def test_reassembly_bounds_gap_memory_and_stream_count():
    reassembler = TcpStreamReassembler(max_pending_bytes=5, max_streams=2)
    reassembler.feed(segment(0, b"x"), FLOW, OUT)
    assert reassembler.feed(segment(10, b"123456"), FLOW, OUT) is None
    assert reassembler.resets == 1 and not reassembler._streams
    for port in range(5):
        reassembler.feed(segment(0, b"x"), replace(FLOW, local_port=port), OUT)
    assert len(reassembler._streams) <= 2


def test_ip_fragment_and_truncated_capture_never_form_tcp_facts():
    raw = raw_tcp(b"abc")
    data = bytearray(raw.payload)
    struct.pack_into("!H", data, 20, 0x2000)
    assert decode_tcp(replace(raw, payload=bytes(data))) is None
    with pytest.raises(PacketDecodeError):
        decode_tcp(replace(raw, payload=raw.payload[:-1]))


def test_opaque_payload_and_unknown_fields_are_not_recorded(tmp_path):
    chunk = StreamChunk(1000., FLOW, OUT, 2, b"chat-auth-session-secret")
    value = next(iter(OpaqueStreamDecoder().feed(chunk)))
    assert EventPolicy().prepare(value) is None
    allowed = EventPolicy(allow_unknown=True).prepare(value)
    assert "chat-auth-session-secret" not in json.dumps(allowed)
    recorder = JsonlEventRecorder(tmp_path/"safe.jsonl")
    altered = replace(value, payload={**value.payload, "raw_payload": "secret", "nested": {"password": "secret"}})
    assert recorder.emit(altered)
    assert "secret" not in (tmp_path/"safe.jsonl").read_text()
    assert EventPolicy().prepare(event("QUEST_COMPLETED", body={"quest_id": 7, "session_key": "secret"}))["payload"] == {"quest_id": 7}


@pytest.mark.parametrize("kind, body", [("SPELL_CAST_FAILED", {"reason": "private chat message"}),
    ("MOVEMENT_UPDATE", {"mover_guid": "account-secret"}),
    ("PACKET_OPCODE_OBSERVED", {"opcode_name": "private account text"})])
def test_allowlisted_fields_cannot_smuggle_unstructured_private_text(kind, body):
    value = event(kind, body=body)
    if kind == "PACKET_OPCODE_OBSERVED":
        value = replace(value, semantic_status="UNKNOWN")
    assert EventPolicy(allow_unknown=True).prepare(value) is None


def test_sandbox_line_buffers_are_bounded_and_connection_reset_discards_partial_json():
    decoder = JsonLineSemanticDecoder(max_line_bytes=100, max_streams=2)
    for port in range(5):
        flow = replace(FLOW, local_port=port)
        decoder.feed(StreamChunk(1000., flow, OUT, 0, b"x"*101))
    assert len(decoder._buffers) <= 2 and all(len(b) <= 100 for b in decoder._buffers.values())
    decoder.feed(StreamChunk(1000., FLOW, OUT, 0, b'{"event_type":'))
    decoder.reset_flow(FLOW.flow_id)
    assert decoder.feed(StreamChunk(1000., FLOW, OUT, 20, b'"QUEST_COMPLETED"}\n')) == []


def test_inbox_requires_authenticated_current_context_and_selected_pid(inbox):
    descriptor = inbox.configure(context())
    assert not inbox.ingest_datagram(canonical(event().to_dict()))
    assert not send(inbox, event(pid=999), descriptor=descriptor)
    forged = envelope(event().to_dict(), descriptor)
    forged["event"]["payload"]["x"] = 4
    assert not inbox.ingest_datagram(canonical(forged))
    assert send(inbox, event(), descriptor=descriptor)
    assert not send(inbox, event(), descriptor=descriptor)
    old = envelope(event(timestamp=1000.01).to_dict(), descriptor)
    inbox.configure(context(context_id="new"))
    assert not inbox.ingest_datagram(canonical(old))
    assert not inbox.poll()


@pytest.mark.parametrize("change", [{"timestamp": 1.}, {"timestamp": 1001.}, {"confidence": 2.},
    {"event_type": "CHAT"}, {"event_id": "wrong"}, {"selected_pid": True}, {"direction": "WRONG"}])
def test_inbox_rejects_malformed_or_stale_data(inbox, change):
    assert not send(inbox, {**event().to_dict(), **change})


def test_inbox_coalesces_by_mover_without_losing_discrete_event_order(inbox):
    for i in range(25):
        assert send(inbox, event(timestamp=999.5+i*.01))
    assert send(inbox, event("QUEST_COMPLETED", body={"quest_id": 1}))
    queued = inbox.poll()
    assert [e["event_type"] for e in queued] == ["MOVEMENT_UPDATE", "QUEST_COMPLETED"]
    assert queued[0]["payload"]["x"] == 999.74 and inbox.coalesced == 24
    assert queued[0]["sampled_at_monotonic"] < 10.
    assert send(inbox, event(timestamp=1000.01))
    assert send(inbox, event("MAP_CHANGED", timestamp=1000.02, body={"world_map_id": 1}))
    assert [e["event_type"] for e in inbox.poll()] == ["MAP_CHANGED"]


def test_movement_from_another_mover_cannot_replace_our_pending_sample(inbox):
    assert send(inbox, event())
    assert send(inbox, event(timestamp=1000.01, body={"x": 20, "mover_guid": "0"*31+"2"}))
    assert len(inbox.poll()) == 2


def test_unsigned_or_inactive_endpoint_is_never_forwarded(tmp_path):
    forwarder = UdpJsonForwarder(descriptor_path=tmp_path/"missing.json")
    try:
        assert not forwarder.emit(event())
        assert forwarder.sent == 0
    finally:
        forwarder.close()


@pytest.mark.parametrize("args", [[], ["--pid", "0", "--interface", "x"],
    ["--pid", "77", "--pkt-file", "x"], ["--pid", "77", "--pkt-file", "x", "--endpoint", "y"],
    ["--pid", "77", "--pkt-file", "x", "--record-only"]])
def test_sidecar_requires_explicit_scope_before_any_capture_or_forward(args):
    from wowbot.packetio.sidecar import main
    with pytest.raises(SystemExit):
        main(args)


def test_receiver_and_forwarder_round_trip_use_real_loopback_only(tmp_path):
    inbox = PacketEventInbox(77, port=0)
    forwarder = UdpJsonForwarder(descriptor_path=tmp_path/"endpoint.json")
    try:
        descriptor = inbox.configure(context(started_wall=time.time()-1))
        (tmp_path/"endpoint.json").write_text(json.dumps(descriptor))
        value = next(iter(OpaqueStreamDecoder().feed(StreamChunk(time.time(), FLOW, OUT, 0, b"not forwarded"))))
        forwarder.policy = EventPolicy(allow_unknown=True)
        assert forwarder.emit(value)
        deadline = time.monotonic()+1
        received = []
        while not received and time.monotonic() < deadline:
            received = inbox.poll()
            time.sleep(.005)
        assert len(received) == 1 and received[0]["selected_pid"] == 77, inbox.diagnostics()
        assert "ipc_key" not in json.dumps(inbox.diagnostics())
        with pytest.raises(ValueError):
            UdpJsonForwarder("192.0.2.1")
    finally:
        inbox.close()
        forwarder.close()
