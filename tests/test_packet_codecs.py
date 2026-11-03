"""Synthetic payload layout tests against reviewed WPP fields, not live evidence."""
from dataclasses import replace
import hashlib
import struct

import pytest

from wowbot.packetio.builds import VERIFIED_OPCODE_BUILDS, opcode_family
from wowbot.packetio.models import FlowDirection
from wowbot.packetio.opcodes_12_1 import REVIEWED_OPCODES
from wowbot.packetio.pkt import OpcodeManifest, PktEventDecoder, PktFormatError, PktV31StreamParser


def packed_guid(low=0x1234, high=(2<<58)|(1602<<42)):
    def part(value):
        mask = sum(1<<i for i in range(8) if value & (255<<(8*i)))
        return mask, bytes((value>>(8*i))&255 for i in range(8) if mask & (1<<i))
    lm, lb = part(low)
    hm, hb = part(high)
    return bytes((lm, hm))+lb+hb


def movement_body(*, low=0x1234, high=(2<<58)|(1602<<42), flags=0):
    return (packed_guid(low, high)+struct.pack("<QIffff", 5, 99, 10.5, -20.25, 31.75, 1.5)
            +struct.pack("<ffiif", 0., 0., 0, 0, 1.)+bytes((flags, 0)))


def pkt_bytes(name="CMSG_MOVE_HEARTBEAT", body=None, *, build=69587, timestamp=1000.):
    direction = 0x47534D43 if name.startswith("CMSG_") else 0x47534D53
    header = b"PKT"+struct.pack("<HBI", 0x301, 0x15, build)+b"enUS"+bytes(40)+struct.pack("<IIi", 1000, 1, 0)
    packet = struct.pack("<I", REVIEWED_OPCODES[name])+(movement_body() if body is None else body)
    return header+struct.pack("<IiIii", direction, 1, 2, 8, len(packet))+struct.pack("<d", timestamp*1000)+packet


def decoded(name="CMSG_MOVE_HEARTBEAT", body=None, *, build=69587, timestamp=1000.):
    parser = PktV31StreamParser()
    record = parser.feed(pkt_bytes(name, body, build=build, timestamp=timestamp))[0]
    decoder = PktEventDecoder(selected_pid=77, header=parser.header, manifest=OpcodeManifest.reviewed(build))
    decoder.capture_epoch = 'd'*32  # calls model frames of one synthetic worker
    return decoder.decode_all(record)


@pytest.mark.parametrize("build", sorted(VERIFIED_OPCODE_BUILDS))
def test_only_explicit_verified_build_family_decodes_movement(build):
    value = decoded(build=build)[-1]
    assert value.event_type == "MOVEMENT_UPDATE"
    assert value.payload["z"] == 31.75
    assert value.provenance["game_build"] == build
    assert value.provenance["opcode_defining_build"] == opcode_family(build).defining_build
    assert value.provenance["opcode_table_sha256"] == opcode_family(build).sha256
    assert value.payload["mover_guid"].endswith("0000000000001234")


def test_retail_70448_uses_only_the_explicit_70340_family():
    family = opcode_family(70448)
    assert family is not None and family.defining_build == 70340
    assert decoded(build=70448)[-1].provenance["game_build"] == 70448


@pytest.mark.parametrize("build", [69213, 69588, 70000, 70339, 70392, 70400])
def test_nearby_or_unknown_build_is_not_substituted(build):
    with pytest.raises(PktFormatError):
        decoded(build=build)


def test_incremental_framing_waits_and_does_not_emit_partial_record():
    parser, raw = PktV31StreamParser(), pkt_bytes()
    assert parser.feed(raw[:20]) == []
    assert parser.feed(raw[20:-1]) == []
    records = parser.feed(raw[-1:])
    assert len(records) == 1 and records[0].timestamp == 1000.
    assert parser.buffered_bytes == 0


def test_many_records_and_partial_next_record_keep_exact_offsets():
    raw = pkt_bytes()
    parser = PktV31StreamParser()
    second = raw[66:]
    records = parser.feed(raw+second+second[:5])
    assert len(records) == 2 and records[1].file_offset == len(raw)
    assert parser.buffered_bytes == 5
    assert parser.feed(second[5:])[0].record_number == 2
    assert parser.buffered_bytes == 0


def test_file_replacement_and_truncation_reset_parser(tmp_path):
    from wowbot.packetio.pkt import PktFileFollower
    path, replacement = tmp_path/"session.pkt", tmp_path/"next.pkt"
    path.write_bytes(pkt_bytes())
    class Stop:
        waits = 0
        def is_set(self): return self.waits >= 4
        def wait(self, _): self.waits += 1
    follower = PktFileFollower(path)
    iterator = follower.records(Stop())
    assert next(iterator).record_number == 0
    replacement.write_bytes(pkt_bytes(build=69814))
    replacement.replace(path)
    assert next(iterator).record_number == 0
    assert follower.parser.header.game_build == 69814 and follower.rotations == 1
    iterator.close()


def test_pkt_mode_recreates_decoder_after_file_header_changes(monkeypatch):
    from types import SimpleNamespace
    from wowbot.packetio.sidecar import _run_pkt
    from wowbot.packetio.forwarder import InMemorySink
    class Follower:
        def __init__(self, _): self.parser = SimpleNamespace(header=None)
        def records(self, _):
            for build in (69587, 70391, 70392):
                parser = PktV31StreamParser()
                record = parser.feed(pkt_bytes(build=build))[0]
                self.parser.header = parser.header
                yield record
        def snapshot(self): return {}
    monkeypatch.setattr("wowbot.packetio.sidecar.PktFileFollower", Follower)
    sink = InMemorySink()
    assert _run_pkt(SimpleNamespace(pid=77, pkt_file=None, opcode_map=None, diagnostics=None), sink, None) == 0
    moves = [e for e in sink.events if e.event_type == "MOVEMENT_UPDATE"]
    assert len(moves) == 2
    assert moves[1].provenance["opcode_defining_build"] == 70340
    assert sink.events[-1].provenance["game_build"] == 70392
    assert sink.events[-1].semantic_status == "UNKNOWN"


@pytest.mark.parametrize("payload", [b"", packed_guid()+bytes(8), movement_body()[:-1]])
def test_truncated_movement_is_never_a_semantic_fact(payload):
    assert all(event.semantic_status == "UNKNOWN" for event in decoded(body=payload))


def test_unverified_manifest_name_lookup_cannot_promote_guessed_payload():
    parser = PktV31StreamParser()
    record = parser.feed(pkt_bytes())[0]
    unverified = OpcodeManifest(69587, {(record.direction, record.opcode): "CMSG_MOVE_HEARTBEAT"})
    values = PktEventDecoder(selected_pid=77, header=parser.header, manifest=unverified).decode_all(record)
    assert len(values) == 1 and values[0].semantic_status == "UNKNOWN"


@pytest.mark.parametrize("first, expected", [(0, "CANT_ATTACK"), (0x40, "OUT_OF_RANGE"),
    (0x80, "BAD_FACING"), (0xC0, "DEAD_TARGET")])
def test_attack_error_is_read_from_most_significant_bits(first, expected):
    value = decoded("SMSG_ATTACK_SWING_ERROR", bytes((first|3,)))[-1]
    assert value.payload["reason"] == expected


def test_attack_start_and_stop_use_two_packed_128_bit_guids():
    body = packed_guid()+packed_guid(0x4567, 8<<58)
    start = decoded("SMSG_ATTACK_START", body)[-1]
    stop = decoded("SMSG_ATTACK_STOP", body+b"\x80")[-1]
    assert len(start.payload["attacker_guid"]) == 32
    assert start.payload["victim_guid"].endswith("0000000000004567")
    assert stop.event_type == "ATTACK_STOPPED" and stop.payload["now_dead"] is True
    assert stop.event_type != "UNIT_DIED"  # nor a loot-eligibility assertion


def test_new_world_keeps_world_map_separate_from_ui_map_and_reads_floor_fields():
    body = struct.pack("<iffffiiI", 2175, 1., 2., 3., 1.5, -1, 2, 7)
    value = decoded("SMSG_NEW_WORLD", body)[-1]
    assert value.payload["world_map_id"] == 2175
    assert "map_id" not in value.payload
    assert value.payload["reason"] == 7 and value.payload["floor_index"] == 2


def test_quest_completion_is_not_a_turnin_and_unknown_body_never_leaks():
    value = decoded("SMSG_QUEST_UPDATE_COMPLETE", struct.pack("<I", 55639)+b"\x80")[-1]
    assert value.event_type == "QUEST_COMPLETED" and value.payload == {"quest_id": 55639}
    assert all(e.semantic_status == "UNKNOWN" for e in decoded("SMSG_QUEST_UPDATE_COMPLETE", struct.pack("<I", 55639)))
    parser = PktV31StreamParser()
    record = parser.feed(pkt_bytes())[0]
    value = PktEventDecoder(selected_pid=77, header=parser.header).decode(replace(record, opcode=123, payload=b"private chat"))
    assert "private chat" not in str(value.to_dict()) and value.semantic_status == "UNKNOWN"


@pytest.mark.parametrize("build", [69587, 70391])
def test_external_wpp_table_requires_namespace_hash_and_explicit_family(tmp_path, monkeypatch, build):
    from wowbot.packetio import builds
    family = opcode_family(build)
    path = tmp_path/"Opcodes.cs"
    text = (f"namespace WowPacketParser.Enums.Version.{family.namespace}\n"
        "private static readonly BiDictionary<Opcode, int> ClientOpcodes = new()\n"
        "{ { Opcode.CMSG_MOVE_HEARTBEAT, 0x41002E }, };\n")
    path.write_text(text)
    with pytest.raises(PktFormatError):
        OpcodeManifest.from_wpp_csharp(path, game_build=build)
    # Explicit test-only pin: tests never install or fetch a real opcode table.
    monkeypatch.setattr(builds, "OPCODE_FAMILIES", tuple(
        replace(item, sha256=hashlib.sha256(text.encode()).hexdigest()) if item == family else item
        for item in builds.OPCODE_FAMILIES))
    value = OpcodeManifest.from_wpp_csharp(path, game_build=build)
    assert value.game_build == family.defining_build and value.verified_source
    assert value.name(FlowDirection.CLIENT_TO_SERVER, 0x41002E) == "CMSG_MOVE_HEARTBEAT"
    with pytest.raises(PktFormatError):
        OpcodeManifest.from_wpp_csharp(path, game_build=69588)
    with pytest.raises(PktFormatError):
        OpcodeManifest.from_wpp_csharp(path, game_build=70391 if build == 69587 else 69587)


@pytest.mark.parametrize("table_build,capture_build", [(69214, 70391), (70340, 69587)])
def test_12_1_5_is_a_separate_opcode_family_not_an_alias_of_12_1_0(table_build, capture_build):
    parser = PktV31StreamParser()
    parser.feed(pkt_bytes(build=capture_build))
    with pytest.raises(PktFormatError):
        PktEventDecoder(selected_pid=77, header=parser.header, manifest=OpcodeManifest.reviewed(table_build))
