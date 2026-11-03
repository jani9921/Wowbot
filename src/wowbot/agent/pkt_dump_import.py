"""Fill the learned TDB from finished Ymir dumps (user 2026-10-21).

"Jó lenne, ha a TDB-nk is frissülne folyamatosan; leállításkor, amikor
leállítom a Ymir dumpot, a packet parserrel fel lehetne tölteni, ahol
hiányos."  The live PacketSpawnLearner only sees what reaches a running
agent; a dump also holds the minutes in MANUAL, before the start and after a
stop.  Each finished ``.pkt`` is replayed through the same PktEventDecoder;
the create point of every CREATURE/VEHICLE/GAMEOBJECT (never a player or a
pet: the decoder drops those, nor a lootable corpse) is merged into
``tdb_learned.sqlite3`` like a live server sighting.  A dump is imported once
(name and size in ``learned_meta``); the live dump being written is skipped.
"""
from __future__ import annotations

from pathlib import Path
import time

from wowbot.packetio.pkt import (OpcodeManifest, PktEventDecoder, PktFormatError,
                                 PktV31StreamParser, entity_guid_kind)

from .learned_world import LearnedWorld

SOURCE = "YMIR_DUMP"
# Dumps of the earlier 70448 client still import; same opcode family/layout.
EXPECTED_BUILDS = frozenset({70448, 70575})
UNIT_LOOTABLE = 0x4
READ_BYTES = 1024 * 1024
SETTLED_SECONDS = 30.          # a dump still growing belongs to a running Ymir


def dump_spawns(path: Path) -> list[tuple]:
    """(kind, entry, name, point, phase, at) of the entities a dump created."""
    parser, decoder, seen, result = PktV31StreamParser(), None, set(), []
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(READ_BYTES), b""):
            for record in parser.feed(chunk):
                if decoder is None:
                    header = parser.header
                    if header is None or header.game_build not in EXPECTED_BUILDS:
                        raise PktFormatError(f"PKT build {getattr(header, 'game_build', None)}, "
                                             f"required one of {sorted(EXPECTED_BUILDS)}")
                    decoder = PktEventDecoder(selected_pid=1, header=header,
                                              manifest=OpcodeManifest.reviewed(header.game_build))
                for event in decoder.decode_all(record):
                    if event.event_type != "ENTITY_CREATED" or event.semantic_status != "CONFIRMED":
                        continue
                    payload = event.payload
                    guid = str(payload.get("entity_guid") or "")
                    kind = entity_guid_kind(guid) if len(guid) == 32 else None
                    if guid in seen or kind is None or payload.get("entry_id") in (None, 0):
                        continue
                    seen.add(guid)
                    if kind[0] != "GAMEOBJECT" and int(payload.get("dynamic_flags") or 0) & UNIT_LOOTABLE:
                        continue                       # a corpse, not a spawn
                    if None in (payload.get("x"), payload.get("y"), payload.get("world_map_id")):
                        continue
                    result.append(("GAMEOBJECT" if kind[0] == "GAMEOBJECT" else "CREATURE",
                                   payload["entry_id"], None,
                                   {"x": payload["x"], "y": payload["y"], "z": payload.get("z"),
                                    "instance_id": payload["world_map_id"], "coordinate_space": "WORLD_YARDS"},
                                   None, event.timestamp))
    return result


def _meta_key(path: Path) -> str:
    return f"pkt_import:{path.name}"


def learned_has(learned_path: Path, path: Path) -> bool:
    """This exact dump (name and size) is already in the learned TDB."""
    import sqlite3
    try:
        db = sqlite3.connect(f"file:{Path(learned_path).as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        row = db.execute("SELECT value FROM learned_meta WHERE key=?", (_meta_key(Path(path)),)).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        db.close()
    return row is not None and row[0] == str(Path(path).stat().st_size)


def import_dumps(directory: Path, learned_path: Path, *, now: float | None = None,
                 settled_seconds: float = SETTLED_SECONDS) -> dict:
    """Import every finished, not yet imported dump in ``directory``."""
    directory, now = Path(directory), time.time() if now is None else now
    learned = LearnedWorld(learned_path)
    summary = {"imported": [], "skipped": [], "failed": [], "spawns_seen": 0, "spawns_stored": 0}
    try:
        for path in sorted(directory.glob("*.pkt")):
            status = path.stat()
            if now - status.st_mtime < settled_seconds:
                summary["skipped"].append(path.name)          # Ymir may still write it
                continue
            done = learned._db.execute("SELECT value FROM learned_meta WHERE key=?",
                                       (_meta_key(path),)).fetchone()
            if done is not None and done[0] == str(status.st_size):
                continue
            try:
                spawns = dump_spawns(path)
            except (PktFormatError, OSError, ValueError) as error:
                summary["failed"].append(f"{path.name}: {type(error).__name__}: {error}")
                continue
            stored = learned.record_spawns(spawns, source=SOURCE)
            with learned._lock, learned._db as db:
                db.execute("INSERT OR REPLACE INTO learned_meta VALUES (?,?)",
                           (_meta_key(path), str(status.st_size)))
            summary["imported"].append(path.name)
            summary["spawns_seen"] += len(spawns)
            summary["spawns_stored"] += stored
    finally:
        learned.close()
    return summary
