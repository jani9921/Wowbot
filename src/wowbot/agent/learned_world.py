"""Learned world memory as a second TDB (user 2026-10-10/11).

The user's server runs on the imported TDB, so the TDB is the static world
memory.  It has gaps (script-summoned NPCs such as Captain Garrick 245394
have no `creature` row; quest 55639 has no starter/ender; some quests have
no quest POI), and a new zone may have none at all.  What the agent verifies
live is saved in ``tdb_learned.sqlite3`` -- the TDB's own tables with the
same columns (creature, gameobject, creature_queststarter/-ender,
gameobject_queststarter/-ender, quest_poi, quest_poi_points).  The original
TDB file stays read-only and untouched; SQLite can ATTACH this file next to
it.  Learned rows carry ``VerifiedBuild = -1`` and guids from 9 000 000 000;
how often/when/from what a row was seen, and an object's name, live in
``learned_row``, because the TDB rows have no place for them.

These rows are positions of existing NPCs/objects seen live: never import
the creature/gameobject rows into the server's database -- they would spawn
duplicates.

The addon exports no NPC/object position, so a position is the player's at
an interaction that needs proximity (talk, quest dialog, melee kill, object
use): an OBSERVER position, a few yards off - a search area, never identity.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
import threading
import time

from .models import number

CELL_YARDS = 8.          # one learned spawn per entity within 8 yd
MERGE_YARDS = 15.        # a learned row this close to a TDB spawn confirms it
ROLE_NAMES = {"GIVER": "QUEST_STARTER", "ENDER": "QUEST_ENDER"}
LEARNED_BUILD = -1
GUID_BASE = 9_000_000_000
LEARNED_POI_IDX1 = 90    # quest_poi.Idx1 of a learned area (TDB uses small ones)

# Verbatim column lists of the TDB 1210.26091 SQLite tables.
TDB_TABLES = '''
CREATE TABLE IF NOT EXISTS "creature" ("guid" TEXT, "id" INTEGER, "map" INTEGER, "zoneId" INTEGER,
 "areaId" INTEGER, "spawnDifficulties" TEXT, "phaseUseFlags" INTEGER, "PhaseId" INTEGER,
 "PhaseGroup" INTEGER, "terrainSwapMap" INTEGER, "modelid" INTEGER, "equipment_id" INTEGER,
 "position_x" REAL, "position_y" REAL, "position_z" REAL, "orientation" REAL, "spawntimesecs" INTEGER,
 "wander_distance" REAL, "currentwaypoint" INTEGER, "curHealthPct" INTEGER, "MovementType" INTEGER,
 "npcflag" TEXT, "unit_flags" INTEGER, "unit_flags2" INTEGER, "unit_flags3" INTEGER,
 "ScriptName" TEXT, "StringId" TEXT, "VerifiedBuild" INTEGER);
CREATE TABLE IF NOT EXISTS "gameobject" ("guid" TEXT, "id" INTEGER, "map" INTEGER, "zoneId" INTEGER,
 "areaId" INTEGER, "spawnDifficulties" TEXT, "phaseUseFlags" INTEGER, "PhaseId" INTEGER,
 "PhaseGroup" INTEGER, "terrainSwapMap" INTEGER, "position_x" REAL, "position_y" REAL,
 "position_z" REAL, "orientation" REAL, "rotation0" REAL, "rotation1" REAL, "rotation2" REAL,
 "rotation3" REAL, "spawntimesecs" INTEGER, "animprogress" INTEGER, "state" INTEGER,
 "ScriptName" TEXT, "StringId" TEXT, "VerifiedBuild" INTEGER);
CREATE TABLE IF NOT EXISTS "creature_queststarter" ("id" INTEGER, "quest" INTEGER, "VerifiedBuild" INTEGER);
CREATE TABLE IF NOT EXISTS "creature_questender" ("id" INTEGER, "quest" INTEGER, "VerifiedBuild" INTEGER);
CREATE TABLE IF NOT EXISTS "gameobject_queststarter" ("id" INTEGER, "quest" INTEGER, "VerifiedBuild" INTEGER);
CREATE TABLE IF NOT EXISTS "gameobject_questender" ("id" INTEGER, "quest" INTEGER, "VerifiedBuild" INTEGER);
CREATE TABLE IF NOT EXISTS "quest_poi" ("QuestID" INTEGER, "BlobIndex" INTEGER, "Idx1" INTEGER,
 "ObjectiveIndex" INTEGER, "QuestObjectiveID" INTEGER, "QuestObjectID" INTEGER, "MapID" INTEGER,
 "UiMapID" INTEGER, "Priority" INTEGER, "Flags" INTEGER, "WorldEffectID" INTEGER,
 "PlayerConditionID" INTEGER, "NavigationPlayerConditionID" INTEGER, "SpawnTrackingID" INTEGER,
 "AlwaysAllowMergingBlobs" INTEGER, "VerifiedBuild" INTEGER);
CREATE TABLE IF NOT EXISTS "quest_poi_points" ("QuestID" INTEGER, "Idx1" INTEGER, "Idx2" INTEGER,
 "X" INTEGER, "Y" INTEGER, "Z" INTEGER, "VerifiedBuild" INTEGER);
CREATE INDEX IF NOT EXISTS learned_creature_lookup ON creature(map, id);
CREATE INDEX IF NOT EXISTS learned_gameobject_lookup ON gameobject(map, id);
CREATE INDEX IF NOT EXISTS learned_poi_points ON quest_poi_points(QuestID, Idx1);
CREATE TABLE IF NOT EXISTS learned_row (
    table_name TEXT NOT NULL, guid TEXT NOT NULL, name TEXT, seen_count INTEGER NOT NULL,
    first_seen REAL NOT NULL, last_seen REAL NOT NULL, source TEXT, detail TEXT,
    PRIMARY KEY (table_name, guid)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS learned_meta (key TEXT PRIMARY KEY, value TEXT);
'''
SPAWN_TABLES = {"CREATURE": "creature", "GAMEOBJECT": "gameobject"}
ROLE_TABLES = {("CREATURE", "QUEST_STARTER"): "creature_queststarter",
               ("CREATURE", "QUEST_ENDER"): "creature_questender",
               ("GAMEOBJECT", "QUEST_STARTER"): "gameobject_queststarter",
               ("GAMEOBJECT", "QUEST_ENDER"): "gameobject_questender"}


def _finite(value):
    result = number(value)
    return result if result is not None and math.isfinite(result) else None


def learned_path_for(entities) -> Path:
    """``tdb_learned.sqlite3`` next to the profile's entity memory."""
    return Path(entities.path).parent / "tdb_learned.sqlite3"


class LearnedWorld:
    def __init__(self, path, on_change=None, *, legacy_entities=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.on_change = on_change
        self.creature_memory = None
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(TDB_TABLES)
        if legacy_entities is not None:
            self._import_legacy(legacy_entities)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _changed(self):
        if self.on_change:
            self.on_change()

    def _rows(self, sql, args=()):
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _next_guid(self, db) -> str:
        row = db.execute("SELECT value FROM learned_meta WHERE key='next_guid'").fetchone()
        guid = int(row[0]) if row else GUID_BASE + 1
        db.execute("INSERT OR REPLACE INTO learned_meta VALUES ('next_guid', ?)", (str(guid + 1),))
        return str(guid)

    def _seen(self, db, table, guid, *, name=None, source=None, at, detail=None, bump=True):
        row = db.execute("SELECT seen_count FROM learned_row WHERE table_name=? AND guid=?",
                         (table, guid)).fetchone()
        if row is None:
            db.execute("INSERT INTO learned_row VALUES (?,?,?,?,?,?,?,?)",
                       (table, guid, name, 1, at, at, source, detail))
        else:
            db.execute("UPDATE learned_row SET seen_count=seen_count+?, last_seen=?,"
                       " name=COALESCE(?, name), source=COALESCE(?, source), detail=COALESCE(?, detail)"
                       " WHERE table_name=? AND guid=?",
                       (1 if bump else 0, at, name or None, source, detail, table, guid))

    # ---- writing -----------------------------------------------------------

    def record_spawn(self, kind, entry, name, position, *, phase=None, source="LIVE", at=None):
        """Merge one observation into the entity's place within 8 yd
        (running-mean position), or add a new TDB-shaped spawn row."""
        table = SPAWN_TABLES.get(kind)
        entry = int(entry) if entry not in (None, "") else 0
        name = str(name or "").strip()
        position = position or {}
        x, y, z = (_finite(position.get(k)) for k in ("x", "y", "z"))
        world_map = position.get("instance_id", position.get("world_map_id"))
        if (table is None or x is None or y is None or world_map is None or (entry <= 0 and not name)
                or position.get("coordinate_space", "WORLD_YARDS") != "WORLD_YARDS"):
            return False
        if position.get("z_known") is False:
            z = None
        at = time.time() if at is None else at
        with self._lock, self._db as db:
            if not name and entry > 0:
                # A LOOT outcome often has no target name any more (live
                # 2026-10-10): the entry's known name keeps one row per place.
                known = db.execute(
                    f"SELECT r.name FROM {table} t JOIN learned_row r ON r.table_name=? AND r.guid=t.guid"
                    " WHERE t.id=? AND r.name<>'' ORDER BY r.seen_count DESC LIMIT 1",
                    (table, entry)).fetchone()
                name = known[0] if known else name
            rows = db.execute(
                f"SELECT t.guid, t.position_x, t.position_y, t.position_z, r.seen_count FROM {table} t"
                " JOIN learned_row r ON r.table_name=? AND r.guid=t.guid"
                " WHERE t.map=? AND t.id=? AND (t.id<>0 OR r.name=? COLLATE NOCASE)",
                (table, int(world_map), entry, name)).fetchall()
            near = [r for r in rows if math.hypot(r[1]-x, r[2]-y) <= CELL_YARDS]
            phase_id = int(phase) if str(phase or "").lstrip("-").isdigit() else 0
            if near:
                guid, ox, oy, oz, n = min(near, key=lambda r: math.hypot(r[1]-x, r[2]-y))
                mz = oz if z is None else z if oz is None else (oz*n+z)/(n+1)
                db.execute(f"UPDATE {table} SET position_x=?, position_y=?, position_z=?, PhaseId=?"
                           " WHERE guid=?", ((ox*n+x)/(n+1), (oy*n+y)/(n+1), mz, phase_id, guid))
                self._seen(db, table, guid, name=name or None, source=source, at=at)
            else:
                guid = self._next_guid(db)
                db.execute(f"INSERT INTO {table} (guid, id, map, spawnDifficulties, phaseUseFlags,"
                           " PhaseId, PhaseGroup, terrainSwapMap, position_x, position_y, position_z,"
                           " VerifiedBuild) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (guid, entry, int(world_map), "0", 0, phase_id, 0, -1, x, y, z, LEARNED_BUILD))
                self._seen(db, table, guid, name=name or None, source=source, at=at)
        self._changed()
        return True

    def record_role(self, kind, entry, quest_id, role, name=None, *, source="LIVE", at=None):
        table = ROLE_TABLES.get((kind, role))
        entry, quest_id = number(entry), number(quest_id)
        if table is None or entry is None or quest_id is None or entry <= 0:
            return False
        at = time.time() if at is None else at
        with self._lock, self._db as db:
            if not db.execute(f"SELECT 1 FROM {table} WHERE id=? AND quest=?",
                              (int(entry), int(quest_id))).fetchone():
                db.execute(f"INSERT INTO {table} VALUES (?,?,?)", (int(entry), int(quest_id), LEARNED_BUILD))
            self._seen(db, table, f"{int(entry)}:{int(quest_id)}", name=name, source=source, at=at)
        self._changed()
        return True

    def record_quest_area(self, quest_id, world_map_id, ui_map_id, points, cells: int,
                          *, source="MINIMAP_QUEST_AREA", at=None) -> bool:
        """The minimap's blue quest area as a quest_poi + quest_poi_points
        polygon (user 2026-10-10: fill a missing quest POI from vision).  A
        larger cell count replaces the stored outline; a smaller never does."""
        quest_id, world_map_id = number(quest_id), number(world_map_id)
        if quest_id is None or world_map_id is None or len(points or ()) < 3:
            return False
        quest_id, world_map_id = int(quest_id), int(world_map_id)
        key = f"{quest_id}:{world_map_id}"
        at = time.time() if at is None else at
        with self._lock, self._db as db:
            row = db.execute("SELECT detail FROM learned_row WHERE table_name='quest_poi' AND guid=?",
                             (key,)).fetchone()
            if row is not None and (json.loads(row[0] or "{}").get("cells") or 0) >= cells:
                return False
            db.execute("DELETE FROM quest_poi WHERE QuestID=? AND Idx1=? AND MapID=? AND VerifiedBuild=?",
                       (quest_id, LEARNED_POI_IDX1, world_map_id, LEARNED_BUILD))
            db.execute("DELETE FROM quest_poi_points WHERE QuestID=? AND Idx1=? AND VerifiedBuild=?",
                       (quest_id, LEARNED_POI_IDX1, LEARNED_BUILD))
            ui = number(ui_map_id)
            db.execute("INSERT INTO quest_poi VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (quest_id, 0, LEARNED_POI_IDX1, 0, 0, 0, world_map_id,
                        int(ui) if ui is not None else None, 0, 0, 0, 0, 0, 0, 0, LEARNED_BUILD))
            db.executemany("INSERT INTO quest_poi_points VALUES (?,?,?,?,?,?,?)",
                           [(quest_id, LEARNED_POI_IDX1, index, round(float(p["x"])), round(float(p["y"])),
                             0, LEARNED_BUILD) for index, p in enumerate(points)])
            self._seen(db, "quest_poi", key, source=source, at=at,
                       detail=json.dumps({"cells": int(cells)}), bump=row is None)
        self._changed()
        return True

    def attach_creature_memory(self, memory):
        """Follow the 2026-10-05 quest-creature memory; import its history once."""
        self.creature_memory = memory
        memory.on_role = self.from_creature_memory
        if self._rows("SELECT 1 FROM learned_meta WHERE key='quest_creature_import'"):
            return 0
        try:
            with memory._lock:
                rows = memory._db.execute("SELECT quest_id,role,npc_id,name,instance_id,x,y,seen_at "
                                          "FROM quest_creature WHERE npc_id IS NOT NULL").fetchall()
        except Exception:
            return 0
        imported = sum(self.from_creature_memory(quest_id, role, npc_id, name,
                                                 {"x": x, "y": y, "instance_id": instance}, seen_at)
                       for quest_id, role, npc_id, name, instance, x, y, seen_at in rows)
        with self._lock, self._db as db:
            db.execute("INSERT OR REPLACE INTO learned_meta VALUES ('quest_creature_import', ?)",
                       (str(imported),))
        return imported

    def from_creature_memory(self, quest_id, role, npc_id, name, position, at=None):
        """A giver/ender/objective creature remembered at a quest event."""
        if not npc_id:
            return 0
        count = 0
        if role in ROLE_NAMES:
            count += self.record_role("CREATURE", npc_id, quest_id, ROLE_NAMES[role], name,
                                      source="QUEST_CREATURE_MEMORY", at=at)
        if (position or {}).get("x") is not None and (position or {}).get("instance_id") is not None:
            count += self.record_spawn("CREATURE", npc_id, name, position,
                                       source="QUEST_CREATURE_MEMORY", at=at)
        return count

    def _import_legacy(self, entities) -> None:
        """Move the 2026-10-10 rows from entity_memory's learned_* tables."""
        if self._rows("SELECT 1 FROM learned_meta WHERE key='legacy_import'"):
            return
        try:
            with entities._connect() as old:
                tables = {row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                spawns = (old.execute("SELECT kind,entry,name,world_map_id,x,y,z,phase,seen_count,"
                                      "first_seen,last_seen,source FROM learned_spawn").fetchall()
                          if "learned_spawn" in tables else [])
                roles = (old.execute("SELECT kind,entry,quest_id,role,name,last_seen,source"
                                     " FROM learned_quest_role").fetchall()
                         if "learned_quest_role" in tables else [])
                areas = (old.execute("SELECT quest_id,world_map_id,ui_map_id,points,cells,updated_at,source"
                                     " FROM learned_quest_area").fetchall()
                         if "learned_quest_area" in tables else [])
                marker = (old.execute("SELECT value FROM learned_meta WHERE key='quest_creature_import'")
                          .fetchone() if "learned_meta" in tables else None)
        except sqlite3.Error:
            return
        for kind, entry, name, world_map, x, y, z, phase, seen, first, last, source in spawns:
            position = {"x": x, "y": y, "z": z, "instance_id": world_map}
            if self.record_spawn(kind, entry, name, position, phase=phase, source=source, at=last):
                with self._lock, self._db as db:
                    table = SPAWN_TABLES[kind]
                    guid = db.execute(
                        f"SELECT t.guid FROM {table} t JOIN learned_row r ON r.table_name=? AND r.guid=t.guid"
                        " WHERE t.map=? AND t.id=? ORDER BY ((t.position_x-?)*(t.position_x-?)"
                        "+(t.position_y-?)*(t.position_y-?)) LIMIT 1",
                        (table, world_map, entry, x, x, y, y)).fetchone()
                    if guid:
                        db.execute("UPDATE learned_row SET seen_count=seen_count+?, first_seen=MIN(first_seen,?)"
                                   " WHERE table_name=? AND guid=?", (max(0, seen-1), first, table, guid[0]))
        for kind, entry, quest_id, role, name, last, source in roles:
            self.record_role(kind, entry, quest_id, role, name, source=source, at=last)
        for quest_id, world_map, ui, points, cells, at, source in areas:
            self.record_quest_area(quest_id, world_map, ui, json.loads(points), cells, source=source, at=at)
        with self._lock, self._db as db:
            if marker:
                db.execute("INSERT OR REPLACE INTO learned_meta VALUES ('quest_creature_import', ?)",
                           (marker[0],))
            db.execute("INSERT OR REPLACE INTO learned_meta VALUES ('legacy_import', ?)",
                       (str(len(spawns) + len(roles) + len(areas)),))

    # ---- reading -----------------------------------------------------------

    def spawns(self, world_map_id, kind, entry=None, name=None):
        """Learned spawn rows of one entity (by entry, or by name if no entry)."""
        table = SPAWN_TABLES.get(kind)
        if table is None or world_map_id is None or (not entry and not name):
            return []
        sql = (f"SELECT t.guid, t.id, r.name, t.position_x, t.position_y, t.position_z, t.PhaseId,"
               f" r.seen_count, r.first_seen, r.last_seen, r.source FROM {table} t"
               " JOIN learned_row r ON r.table_name=? AND r.guid=t.guid WHERE t.map=? AND ")
        if entry:
            rows = self._rows(sql + "t.id=?", (table, int(world_map_id), int(entry)))
            if name:   # an object used before its entry was known
                rows += self._rows(sql + "t.id=0 AND r.name=? COLLATE NOCASE",
                                   (table, int(world_map_id), str(name)))
        else:
            rows = self._rows(sql + "r.name=? COLLATE NOCASE", (table, int(world_map_id), str(name)))
        result = []
        for guid, entry_, name_, x, y, z, phase, seen, first, last, source in rows:
            result.append({"spawn_id": f"learned:{guid}",
                "npc_id": entry_ if kind == "CREATURE" else None,
                "object_id": entry_ if kind == "GAMEOBJECT" else None,
                "name": name_ or "", "world_map_id": world_map_id, "x": x, "y": y, "z": z,
                "z_known": z is not None, "context": {"PhaseId": phase or None},
                "coordinate_space": "WORLD_YARDS", "belief": "LEARNED", "source": "LEARNED_SPAWN",
                "location_kind": "OBSERVER_POSITION", "seen_count": seen,
                "first_seen": first, "last_seen": last, "evidence_source": source,
                "verified_build": LEARNED_BUILD, "confirmed": False, "navigation_trusted": False})
        return result

    def quest_roles(self, quest_id):
        """Learned starter/ender rows plus the live quest-creature memory."""
        rows = []
        if number(quest_id) is None:
            return rows
        for role, table in (("QUEST_STARTER", "creature_queststarter"),
                            ("QUEST_ENDER", "creature_questender")):
            for entry, quest, name, seen in self._rows(
                    f"SELECT t.id, t.quest, r.name, r.seen_count FROM {table} t"
                    " LEFT JOIN learned_row r ON r.table_name=? AND r.guid=t.id||':'||t.quest"
                    " WHERE t.quest=?", (table, int(number(quest_id)))):
                rows.append({"npc_id": entry, "quest_id": quest, "role": role, "name": name,
                             "source": "LEARNED", "seen_count": seen or 1})
        if self.creature_memory is not None:
            try:
                live = self.creature_memory.roles(quest_id)
            except Exception:
                live = {}
            for role, name in ROLE_NAMES.items():
                for row in live.get(role) or ():
                    npc = number(row.get("npc_id"))
                    if npc and not any(r["npc_id"] == npc and r["role"] == name for r in rows):
                        rows.append({"npc_id": int(npc), "quest_id": int(quest_id), "role": name,
                                     "name": row.get("name"), "source": "LEARNED", "seen_count": 1})
        return rows

    def quest_areas(self, quest_id, world_map_id) -> list[dict]:
        """Learned quest-POI polygons (the blue minimap area) of a quest."""
        if number(quest_id) is None or world_map_id is None:
            return []
        quest_id = int(number(quest_id))
        result = []
        for idx1, ui in self._rows("SELECT Idx1, UiMapID FROM quest_poi WHERE QuestID=? AND MapID=?"
                                   " AND VerifiedBuild=?", (quest_id, int(world_map_id), LEARNED_BUILD)):
            points = [{"x": float(x), "y": float(y)} for x, y in self._rows(
                "SELECT X, Y FROM quest_poi_points WHERE QuestID=? AND Idx1=? ORDER BY Idx2",
                (quest_id, idx1))]
            detail = self._rows("SELECT detail FROM learned_row WHERE table_name='quest_poi' AND guid=?",
                                (f"{quest_id}:{int(world_map_id)}",))
            cells = json.loads((detail[0][0] if detail else None) or "{}").get("cells")
            if len(points) >= 3:
                result.append({"points": points, "ui_map_id": ui, "cells": cells,
                               "source": "LEARNED_MINIMAP_AREA", "confirmed": False})
        return result


def merge_spawns(tdb_rows, learned_rows):
    """TDB rows (confirmed by a nearby learned row) plus learned gap fillers."""
    result = [dict(row) for row in tdb_rows]
    for learned in learned_rows:
        near = [row for row in result if row.get("source") != "LEARNED_SPAWN"
                and _finite(row.get("x")) is not None and _finite(row.get("y")) is not None
                and math.hypot(row["x"]-learned["x"], row["y"]-learned["y"]) <= MERGE_YARDS]
        for row in near:
            row["live_confirmed"] = True
            row["live_seen_count"] = row.get("live_seen_count", 0) + learned["seen_count"]
            row["live_last_seen"] = max(row.get("live_last_seen", 0), learned["last_seen"])
        if not near:
            result.append(dict(learned))
    return result
