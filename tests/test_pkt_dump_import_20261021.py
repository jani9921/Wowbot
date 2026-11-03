"""A finished Ymir dump fills the learned TDB once (user 2026-10-21).

"Leállításkor, amikor leállítom a Ymir dumpot, a packet parserrel fel
lehetne tölteni, ahol hiányos."  The record below is the real 70448
SMSG_UPDATE_OBJECT fixture (a door, the vehicle Jrokgar and creatures); it
holds no player data.
"""
import os
import sqlite3
import struct
import time

from wowbot.agent.pkt_dump_import import SOURCE, dump_spawns, import_dumps
from wowbot.packetio.opcodes_12_1 import FAMILY_OPCODES, REVIEWED_OPCODES

from test_packet_entities import UPDATES


def write_dump(path, body, *, age=120.):
    opcodes = {**REVIEWED_OPCODES, **FAMILY_OPCODES[70340]}
    header = b"PKT"+struct.pack("<HBI", 0x301, 0x15, 70448)+b"enUS"+bytes(40)+struct.pack("<IIi", 1000, 1, 0)
    packet = struct.pack("<I", opcodes["SMSG_UPDATE_OBJECT"])+body
    record = struct.pack("<IiIii", 0x47534D53, 1, 2, 8, len(packet))+struct.pack("<d", 1000.*1000)+packet
    path.write_bytes(header+record)
    stamp = time.time()-age
    os.utime(path, (stamp, stamp))
    return path


def test_a_dump_s_created_entities_become_learned_spawns_once(tmp_path):
    dumps = tmp_path / "dumps"
    dumps.mkdir()
    write_dump(dumps / "dump_a.pkt", UPDATES["create_door_vehicle_creatures"])
    spawns = dump_spawns(dumps / "dump_a.pkt")
    kinds = {(kind, entry) for kind, entry, *_ in spawns}
    assert ("GAMEOBJECT", 335718) in kinds and ("CREATURE", 161265) in kinds   # the door, Jrokgar
    learned = tmp_path / "tdb_learned.sqlite3"
    summary = import_dumps(dumps, learned)
    assert summary["imported"] == ["dump_a.pkt"] and summary["spawns_stored"] == len(spawns)
    with sqlite3.connect(learned) as db:
        rows = db.execute("SELECT count(*) FROM learned_row WHERE source=?", (SOURCE,)).fetchone()[0]
        assert 0 < rows <= len(spawns)       # the same entry within 8 yd is one spawn row
        door = db.execute("SELECT map, position_x FROM gameobject WHERE id=335718").fetchone()
    assert door[0] == 2175 and round(door[1]) == 767
    assert import_dumps(dumps, learned)["imported"] == []                 # imported once


def test_a_dump_still_being_written_waits(tmp_path):
    dumps = tmp_path / "dumps"
    dumps.mkdir()
    write_dump(dumps / "dump_live.pkt", UPDATES["create_door_vehicle_creatures"], age=1.)
    summary = import_dumps(dumps, tmp_path / "tdb_learned.sqlite3")
    assert summary["skipped"] == ["dump_live.pkt"] and summary["imported"] == []
    assert import_dumps(dumps, tmp_path / "tdb_learned.sqlite3", settled_seconds=0.)["imported"] == ["dump_live.pkt"]
