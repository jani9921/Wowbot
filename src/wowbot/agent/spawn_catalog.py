"""Read-only reference locations, never live Entity identities or target positions."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

DEFAULT_CATALOG = Path(__file__).resolve().parents[3] / "data" / "tdb_spawn_catalog.sqlite3"


def sql_rows(values):
    """Parse mysqldump value tuples as data. Never execute source SQL."""
    row, field, quoted, escaped, active = [], [], False, False, False
    for char in values:
        if escaped:
            field.append(char)
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == "'":
            quoted = not quoted
        elif quoted:
            field.append(char)
        elif char == "(" and not active:
            active = True
            row, field = [], []
        elif active and char in ",)":
            row.append("".join(field).strip())
            field = []
            if char == ")":
                yield row
                active = False
        elif active:
            field.append(char)
    if quoted or active or escaped:
        raise ValueError("Incomplete SQL tuple")


def import_dump(source: Path, destination: Path):
    if destination.exists():
        raise FileExistsError(f"Catalog already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    columns = []
    in_schema = False
    count = 0
    connection = sqlite3.connect(destination)
    try:
        connection.execute("CREATE TABLE spawns (spawn_id INTEGER PRIMARY KEY, npc_id INTEGER, world_map_id INTEGER, x REAL, y REAL, z REAL, context TEXT)")
        connection.execute("CREATE INDEX spawn_lookup ON spawns(world_map_id,npc_id)")
        connection.execute("CREATE TABLE provenance (source TEXT, sha256 TEXT, count INTEGER)")
        with source.open("rb") as stream:
            for raw in stream:
                digest.update(raw)
                line = raw.decode("utf-8")
                if line.startswith("CREATE TABLE `creature` ("):
                    in_schema = True
                    continue
                if in_schema:
                    if line.startswith(")"):
                        in_schema = False
                    else:
                        match = re.match(r"\s*`([^`]+)`", line)
                        if match:
                            columns.append(match[1])
                if not line.startswith("INSERT INTO `creature` VALUES "):
                    continue
                if not columns:
                    raise ValueError("Missing creature schema")
                batch = []
                for values in sql_rows(line.split(" VALUES ", 1)[1]):
                    if len(values) != len(columns):
                        raise ValueError("Creature schema/value count mismatch")
                    row = dict(zip(columns, values))
                    xyz = [float(row[f"position_{axis}"]) for axis in "xyz"]
                    if not all(math.isfinite(v) for v in xyz):
                        raise ValueError("Non-finite spawn position")
                    context = {key: row.get(key) for key in (
                        "PhaseId", "PhaseGroup", "phaseUseFlags", "terrainSwapMap",
                        "spawnDifficulties", "MovementType", "wander_distance", "VerifiedBuild")}
                    batch.append((int(row["guid"]), int(row["id"]), int(row["map"]),
                                  *xyz, json.dumps(context)))
                connection.executemany("INSERT INTO spawns VALUES (?,?,?,?,?,?,?)", batch)
                count += len(batch)
        if not count:
            raise ValueError("No creature spawns found")
        connection.execute("INSERT INTO provenance VALUES (?,?,?)", (source.name, digest.hexdigest(), count))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {"count": count, "sha256": digest.hexdigest(), "catalog": str(destination)}


def import_quest_relations(source: Path, destination: Path = DEFAULT_CATALOG):
    """Add quest role evidence to an existing spawn catalog.

    The dump is parsed as inert data.  Its digest must match the dump which
    produced the spawn catalog, preventing relations from a different TDB
    release from being silently combined with its coordinates.
    """
    if not destination.is_file():
        raise FileNotFoundError(destination)
    digest = hashlib.sha256()
    relations = {"creature_queststarter": [], "creature_questender": []}
    with source.open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            line = raw.decode("utf-8")
            for table in relations:
                prefix = f"INSERT INTO `{table}` VALUES "
                if not line.startswith(prefix):
                    continue
                for values in sql_rows(line[len(prefix):]):
                    if len(values) != 3:
                        raise ValueError(f"{table} schema/value count mismatch")
                    relations[table].append(tuple(map(int, values)))
    source_hash = digest.hexdigest()
    connection = sqlite3.connect(destination)
    try:
        provenance = connection.execute("SELECT sha256 FROM provenance").fetchone()
        if not provenance or provenance[0] != source_hash:
            raise ValueError("Quest relations and spawn catalog come from different TDB dumps")
        connection.execute("CREATE TABLE IF NOT EXISTS quest_roles (npc_id INTEGER, quest_id INTEGER, role TEXT, verified_build INTEGER, PRIMARY KEY(npc_id,quest_id,role))")
        connection.execute("CREATE INDEX IF NOT EXISTS quest_role_lookup ON quest_roles(role,npc_id)")
        connection.execute("DELETE FROM quest_roles")
        for table, role in (("creature_queststarter", "QUEST_STARTER"),
                            ("creature_questender", "QUEST_ENDER")):
            connection.executemany("INSERT INTO quest_roles VALUES (?,?,?,?)",
                                   ((npc, quest, role, build) for npc, quest, build in relations[table]))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {"starters": len(relations["creature_queststarter"]),
            "enders": len(relations["creature_questender"]),
            "sha256": source_hash, "catalog": str(destination)}


def candidates(world_map_id, npc_id=None, path=DEFAULT_CATALOG):
    if world_map_id is None or not Path(path).is_file():
        return []
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        provenance = connection.execute("SELECT source,sha256 FROM provenance").fetchone()
        if not provenance:
            return []
        query = "SELECT * FROM spawns WHERE world_map_id=?"
        args = [world_map_id]
        if npc_id is not None:
            query += " AND npc_id=?"
            args.append(npc_id)
        return [{"spawn_id": r[0], "npc_id": r[1], "world_map_id": r[2],
                 "x": r[3], "y": r[4], "z": r[5], "context": json.loads(r[6]),
                 "coordinate_space": "WORLD_YARDS", "source": "TDB_REFERENCE",
                 "source_file": provenance[0], "source_sha256": provenance[1],
                 "belief": "CANDIDATE", "confirmed": False, "navigation_trusted": False}
                for r in connection.execute(query, args)]
    finally:
        connection.close()


def quest_role_candidates(world_map_id, role="QUEST_STARTER", path=DEFAULT_CATALOG):
    """Return DB-backed role hypotheses; never confirmed live entities."""
    if world_map_id is None or not Path(path).is_file():
        return []
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='quest_roles'").fetchone():
            return []
        provenance = connection.execute("SELECT source,sha256 FROM provenance").fetchone()
        rows = connection.execute(
            "SELECT s.spawn_id,s.npc_id,s.world_map_id,s.x,s.y,s.z,s.context,"
            "GROUP_CONCAT(q.quest_id),MAX(q.verified_build) "
            "FROM spawns s JOIN quest_roles q ON q.npc_id=s.npc_id "
            "WHERE s.world_map_id=? AND q.role=? GROUP BY s.spawn_id",
            (world_map_id, role))
        return [{"spawn_id": r[0], "npc_id": r[1], "world_map_id": r[2],
                 "x": r[3], "y": r[4], "z": r[5], "context": json.loads(r[6]),
                 "quest_ids": [int(v) for v in r[7].split(",")], "verified_build": r[8],
                 "role_hypothesis": role, "coordinate_space": "WORLD_YARDS",
                 "source": "TDB_REFERENCE", "source_file": provenance[0],
                 "source_sha256": provenance[1], "belief": "CANDIDATE",
                 "confirmed": False, "navigation_trusted": False}
                for r in rows]
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    print(json.dumps(import_dump(args.source, args.output)))
