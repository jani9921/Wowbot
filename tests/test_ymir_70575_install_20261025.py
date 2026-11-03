"""The user's Ymir 70575 V3 port candidate is the pinned capture (2026-10-25).

"itt van az exe, bekéne tenni a helyére, elvileg mukodik faszán" — the client
is 12.1.5.70575.  WPP aliases 70575 to the 70340 opcode table (same SHA-256 as
the table already pinned), and the user's own 70575 capture decoded cleanly.
"""
from pathlib import Path
import struct

import pytest

from wowbot.agent import pkt_dump_import
from wowbot.agent.pkt_dump_import import dump_spawns
from wowbot.packetio import ymir_bridge
from wowbot.packetio.builds import opcode_family
from wowbot.packetio.opcodes_12_1 import FAMILY_OPCODES, REVIEWED_OPCODES
from wowbot.packetio.pkt import OpcodeManifest, PktEventDecoder, PktV31StreamParser

from test_packet_entities import UPDATES

ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "runtime" / "ymir" / "ymir_retail_12.1.5.70575_PORT_CANDIDATE_V3.exe"
USER_DUMP = (ROOT.parents[2] / "ai_visual_bot_midnight 1.2" / "_local_reverse_engineering" / "ymir-2026-10-15"
             / "test-copy" / "dumps" / "dump_12.1.0.70575_2026-10-25_10-00-12.pkt")


def test_70575_shares_the_70340_opcode_family_but_70529_does_not():
    assert opcode_family(70575).defining_build == 70340
    assert opcode_family(70448).defining_build == 70340
    assert opcode_family(70529) is None            # aliased by WPP, never captured here


def test_the_bridge_pins_the_v3_binary_and_the_gui_starts_it():
    assert ymir_bridge.EXPECTED_BUILD == 70575
    assert ymir_bridge.VALIDATED_SHA256 == "77cc8a63b94ee52c47090290a69f3d6fa3db3995ded3c7534c886c85dcbec6b9"
    assert V3.name in (ROOT / "src" / "wowbot" / "agent" / "gui.py").read_text(encoding="utf-8")
    if V3.is_file():
        assert ymir_bridge.sha256_file(V3) == ymir_bridge.VALIDATED_SHA256


@pytest.mark.parametrize("build", [70448, 70575])
def test_dumps_of_both_clients_fill_the_learned_tdb(tmp_path, build):
    opcodes = {**REVIEWED_OPCODES, **FAMILY_OPCODES[70340]}
    header = b"PKT"+struct.pack("<HBI", 0x301, 0x15, build)+b"enUS"+bytes(40)+struct.pack("<IIi", 1000, 1, 0)
    packet = struct.pack("<I", opcodes["SMSG_UPDATE_OBJECT"])+UPDATES["create_door_vehicle_creatures"]
    record = struct.pack("<IiIii", 0x47534D53, 1, 2, 8, len(packet))+struct.pack("<d", 1000.*1000)+packet
    dump = tmp_path / "dump.pkt"
    dump.write_bytes(header+record)
    kinds = {(kind, entry) for kind, entry, *_ in dump_spawns(dump)}
    assert ("GAMEOBJECT", 335718) in kinds and ("CREATURE", 161265) in kinds
    assert build in pkt_dump_import.EXPECTED_BUILDS


@pytest.mark.skipif(not USER_DUMP.is_file(), reason="the user's 70575 capture is local only")
def test_the_user_run_70575_capture_decodes():
    parser, decoder, created = PktV31StreamParser(), None, []
    with USER_DUMP.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            for record in parser.feed(chunk):
                if decoder is None:
                    assert parser.header.game_build == 70575
                    decoder = PktEventDecoder(selected_pid=1, header=parser.header,
                                              manifest=OpcodeManifest.reviewed(70575))
                created += [e for e in decoder.decode_all(record)
                            if e.event_type == "ENTITY_CREATED" and e.semantic_status == "CONFIRMED"]
    assert len(created) >= 100
    placed = [e.payload for e in created if e.payload.get("x") is not None]
    assert len(placed) >= len(created) - 2            # two mammoth passengers ride a transport
    assert all(abs(p["x"]) < 100_000 and abs(p["y"]) < 100_000 for p in placed)
