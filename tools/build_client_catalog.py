"""Import local decoded DB2 data to a new indexed SQLite reference catalog.

The C# exporter uses pinned DBCD plus WoWDBDefs layouts. No script is ever
executed: simple pathID assignments are parsed as data and ambiguous scenes
are retained as unresolved. Inventory does not mean every table is decoded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import struct
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from wowbot.quests.scene_resolver import index_relations


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def source_metadata(path):
    with path.open("rb") as stream:
        raw = stream.read(204)
    if len(raw) < 204 or raw[:4] != b"WDC5":
        return {"format": raw[:4].decode("ascii", "replace"), "schema_label": None,
                "header_rows": None, "layout_hash": None}
    values = struct.unpack_from("<9IHH7I", raw, 136)
    return {"format": "WDC5", "schema_label": raw[8:136].split(b"\0")[0].decode("ascii"),
            "header_rows": values[0], "layout_hash": f"{values[5]:08X}"}


def rows(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line in stream:
            item = json.loads(line)
            if item.get("type") == "row":
                yield item["id"], item["values"]


def build(output, source, decoded_dirs, definitions, definition_revision, associations, world_reference):
    """Publish only a completed new catalog; failed imports leave no usable file."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    temporary = output.with_name(output.name + ".partial-" + uuid4().hex)
    try:
        _build(temporary, source, decoded_dirs, definitions, definition_revision, associations, world_reference)
        if output.exists():
            raise FileExistsError(output)
        temporary.rename(output)
    finally:
        temporary.unlink(missing_ok=True)


def _build(output, source, decoded_dirs, definitions, definition_revision, associations, world_reference):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(output)
    try:
        connection.executescript("""
        PRAGMA journal_mode=DELETE;
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE source_files(table_name TEXT PRIMARY KEY,path TEXT,sha256 TEXT,bytes INTEGER,
          format TEXT,schema_label TEXT,layout_hash TEXT,header_rows INTEGER,decoded_rows INTEGER,
          status TEXT NOT NULL,definition_sha256 TEXT);
        CREATE TABLE db2_rows(table_name TEXT,id INTEGER,record_json TEXT NOT NULL,
          PRIMARY KEY(table_name,id)) WITHOUT ROWID;
        CREATE TABLE locations(id INTEGER PRIMARY KEY,x REAL,y REAL,z REAL,rot_json TEXT);
        CREATE TABLE path_nodes(id INTEGER PRIMARY KEY,path_id INTEGER,sequence INTEGER,location_id INTEGER);
        CREATE INDEX ix_path_nodes_path ON path_nodes(path_id,sequence);
        CREATE TABLE scene_paths(package_id INTEGER,path_id INTEGER,script_id INTEGER,
          source_member_id INTEGER,PRIMARY KEY(package_id,path_id,script_id));
        CREATE INDEX ix_scene_path ON scene_paths(path_id);
        CREATE TABLE quest_routes(quest_id INTEGER PRIMARY KEY,status TEXT,route_json TEXT);
        CREATE TABLE quest_links(quest_id INTEGER,table_name TEXT,record_id INTEGER,
          PRIMARY KEY(quest_id,table_name,record_id)) WITHOUT ROWID;
        CREATE TABLE poi_blobs(id INTEGER PRIMARY KEY,quest_id INTEGER,map_id INTEGER,ui_map_id INTEGER);
        CREATE INDEX ix_poi_quest ON poi_blobs(quest_id);
        CREATE TABLE poi_points(id INTEGER PRIMARY KEY,blob_id INTEGER,x REAL,y REAL,z REAL);
        CREATE INDEX ix_poi_blob ON poi_points(blob_id,id);
        CREATE TABLE scene_scripts(package_id INTEGER,script_id INTEGER,source_member_id INTEGER,
          PRIMARY KEY(package_id,script_id)) WITHOUT ROWID;
        CREATE TABLE spell_effects(id INTEGER PRIMARY KEY,spell_id INTEGER,effect INTEGER,aura INTEGER,
          trigger_spell INTEGER,difficulty_id INTEGER,misc1 INTEGER,misc2 INTEGER);
        CREATE INDEX ix_spell_effect_spell ON spell_effects(spell_id);
        CREATE INDEX ix_spell_effect_kind ON spell_effects(effect,aura);
        """)
        meta = {"schema_version": 3, "source_kind": "LOCAL_EXTRACTED_CLIENT_DB2",
                "definitions_revision": definition_revision, "decoder": "DBCD 2.3.0",
                "schema_label_is_live_build": False, "live_build_validation": "NOT_VALIDATED",
                "network_runtime_dependency": False,
                "world_reference_sha256": sha256(world_reference),
                "reviewed_scene_exceptions_enabled": associations is not None}
        connection.executemany("INSERT INTO metadata VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
        for path in sorted(Path(source).glob("*.db2")):
            header = source_metadata(path)
            definition = Path(definitions) / (path.stem + ".dbd")
            connection.execute("INSERT INTO source_files VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                path.stem, str(path.resolve()), sha256(path), path.stat().st_size,
                header["format"], header["schema_label"], header["layout_hash"], header["header_rows"],
                None, "INVENTORIED_NOT_DECODED", sha256(definition) if definition.is_file() else None))
        decoded = {}
        for folder in decoded_dirs:
            for path in sorted(Path(folder).glob("*.jsonl")):
                # Last explicit export directory wins; never combine versions.
                if path.stat().st_size:
                    decoded[path.stem] = path
        for table, path in decoded.items():
            with path.open(encoding="utf-8-sig") as stream:
                table_meta = json.loads(stream.readline())
            if table_meta.get("type") != "table" or table_meta["name"] != table:
                raise ValueError("Invalid decoded table metadata")
            source_info = connection.execute(
                "SELECT layout_hash,sha256,definition_sha256 FROM source_files WHERE table_name=?", (table,)).fetchone()
            if (source_info is None or source_info != (
                    table_meta.get("layout_hash"), table_meta.get("source_sha256"), table_meta.get("definition_sha256"))):
                raise ValueError("DB2/DBD export provenance mismatch for " + table)
            count = 0
            for record_id, value in rows(path):
                connection.execute("INSERT INTO db2_rows VALUES (?,?,?)", (table, record_id, json.dumps(value, separators=(",", ":"))))
                quest_id = value.get("QuestID")
                if table in {"QuestV2", "QuestV2CliTask"}:
                    quest_id = record_id
                if type(quest_id) is int and quest_id > 0:
                    connection.execute("INSERT INTO quest_links VALUES (?,?,?)", (quest_id, table, record_id))
                if table == "Location":
                    point = value["Pos"]
                    if len(point) != 3 or not all(type(v) in {int, float} and math.isfinite(v) for v in point):
                        raise ValueError("Invalid Location XYZ")
                    connection.execute("INSERT INTO locations VALUES (?,?,?,?,?)", (record_id, *point, json.dumps(value["Rot"])))
                elif table == "PathNode":
                    connection.execute("INSERT INTO path_nodes VALUES (?,?,?,?)", (
                        record_id, value["PathID"], value["Sequence"], value["LocationID"]))
                elif table == "QuestPOIBlob":
                    connection.execute("INSERT INTO poi_blobs VALUES (?,?,?,?)", (
                        record_id, value["QuestID"], value["MapID"], value["UiMapID"]))
                elif table == "QuestPOIPoint":
                    connection.execute("INSERT INTO poi_points VALUES (?,?,?,?,?)", (
                        record_id, value["QuestPOIBlobID"], value["X"], value["Y"], value["Z"]))
                elif table == "SpellEffect":
                    misc = value["EffectMiscValue"]
                    connection.execute("INSERT INTO spell_effects VALUES (?,?,?,?,?,?,?,?)", (
                        record_id, value["SpellID"], value["Effect"], value["EffectAura"],
                        value["EffectTriggerSpell"], value["DifficultyID"], misc[0], misc[1]))
                count += 1
            if count != table_meta["row_count"]:
                raise ValueError("Decoded row count mismatch for " + table)
            connection.execute("UPDATE source_files SET decoded_rows=?,status='DECODED_AVAILABLE_ROWS' WHERE table_name=?", (count, table))
            connection.commit()
            print(json.dumps({"table": table, "imported": count}), flush=True)

        _index_scene_paths(connection)
        print(json.dumps({"automatic_scene_resolution": index_relations(connection, world_reference)}), flush=True)
        if associations is not None:
            _link_quests(connection, associations, world_reference)
        if sha256(world_reference) != meta["world_reference_sha256"]:
            raise ValueError("Existing TDB changed during read-only catalog construction")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        connection.commit()
    finally:
        connection.close()


def _table(connection, name):
    return {row_id: json.loads(value) for row_id, value in connection.execute(
        "SELECT id,record_json FROM db2_rows WHERE table_name=?", (name,))}


def _index_scene_paths(connection):
    scripts = _table(connection, "SceneScriptText")
    # Only plain assignments to pathID are supported. Player-condition
    # branches with several paths remain indexed raw, never picked at random.
    paths = {}
    for key, value in scripts.items():
        text = re.sub(r"--\[\[.*?\]\]", "", value.get("Script", ""), flags=re.S)
        text = re.sub(r"--[^\r\n]*", "", text)
        found = {int(x) for x in re.findall(r"(?:\bpathID\s*=\s*|\bLoadPath\s*\(\s*)(\d+)\b", text) if int(x) > 0}
        if len(found) == 1:
            paths[key] = found.pop()
    members = {}
    for member_id, value in _table(connection, "SceneScriptPackageMember").items():
        members.setdefault(value["SceneScriptPackageID"], []).append((member_id, value))
    chains = _table(connection, "SceneScript")
    packages = _table(connection, "SceneScriptPackage")
    for package_id in packages:
        pending, visited_packages, seen_scripts = [package_id], set(), set()
        while pending:
            current = pending.pop()
            if current in visited_packages:
                continue
            visited_packages.add(current)
            for member_id, value in members.get(current, ()):
                child = value.get("ChildSceneScriptPackageID")
                if child:
                    pending.append(child)
                chain = [value.get("SceneScriptID")]
                while chain:
                    script_id = chain.pop()
                    if not script_id or script_id in seen_scripts:
                        continue
                    seen_scripts.add(script_id)
                    connection.execute("INSERT INTO scene_scripts VALUES (?,?,?)", (package_id, script_id, member_id))
                    links = chains.get(script_id, {})
                    chain.extend(links.get(key) for key in ("FirstSceneScriptID", "NextSceneScriptID"))
                    path_id = paths.get(script_id)
                    if path_id is not None:
                        connection.execute("INSERT OR IGNORE INTO scene_paths VALUES (?,?,?,?)", (
                            package_id, path_id, script_id, member_id))


def _link_quests(connection, associations, world_reference):
    manifest = json.loads(Path(associations).read_text(encoding="utf-8-sig"))
    world = sqlite3.connect(Path(world_reference).resolve().as_uri() + "?mode=ro", uri=True)
    world.row_factory = sqlite3.Row
    try:
        for relation in manifest["bindings"]:
            existing = connection.execute("SELECT route_json FROM quest_routes WHERE quest_id=?", (relation["quest_id"],)).fetchone()
            if existing:
                if json.loads(existing[0])["scene_package"] != relation["scene_package_id"]:
                    raise ValueError("Automatic/reviewed scene relation conflict")
                continue  # An automatic structural resolution owns this route.
            candidates = {r[0] for r in connection.execute(
                "SELECT DISTINCT package_id FROM quest_scene_candidates WHERE quest_id=? AND status='RESOLVED' AND conditional=0", (relation["quest_id"],))}
            if len(candidates)>1 or candidates and relation["scene_package_id"] not in candidates:
                raise ValueError("Reviewed exception conflicts with automatic scene candidates")
            quest = world.execute("SELECT ID,LogTitle FROM quest_template WHERE ID=?", (relation["quest_id"],)).fetchone()
            objectives = list(world.execute("SELECT * FROM quest_objectives WHERE QuestID=?", (relation["quest_id"],)))
            checkpoint = next((dict(r) for r in objectives if r["ObjectID"] == relation["checkpoint_object_id"]), None)
            arrival = next((dict(r) for r in objectives if r["ObjectID"] == relation["arrival_object_id"]), None)
            routes = list(connection.execute("SELECT DISTINCT path_id FROM scene_paths WHERE package_id=?", (relation["scene_package_id"],)))
            if quest is None or checkpoint is None or arrival is None or len(routes) != 1:
                raise ValueError("Unresolved quest/scene association: " + str(relation["quest_id"]))
            path_id = routes[0][0]
            points = list(connection.execute("""SELECT n.sequence,n.id,n.location_id,l.x,l.y,l.z,l.rot_json
              FROM path_nodes n JOIN locations l ON l.id=n.location_id WHERE n.path_id=? ORDER BY n.sequence""", (path_id,)))
            if len(points) != checkpoint["Amount"] + 1 or len({p[0] for p in points}) != len(points):
                raise ValueError("Quest amount does not match the scene path")
            route = {"quest_id": quest["ID"], "title": quest["LogTitle"], "scene_package": relation["scene_package_id"],
                     "path_id": path_id, "map_id": relation["instance_id"], "ring_objective_entry": checkpoint["ObjectID"],
                     "target_objective_entry": arrival["ObjectID"], "checkpoint_objective": checkpoint, "arrival_objective": arrival,
                     "rings": [[*p[3:6], *json.loads(p[6])[2:3]] for p in points[:-1]],
                     "target": [*points[-1][3:6], *json.loads(points[-1][6])[2:3]],
                     "association_kind": manifest["association_kind"], "association_evidence": relation["evidence"],
                     "coordinate_source": "LOCAL_DB2_SCENE_PATH_LOCATION", "live_validation": "NOT_VALIDATED",
                     "source_node_ids": [p[1] for p in points], "source_location_ids": [p[2] for p in points]}
            connection.execute("INSERT INTO quest_routes VALUES (?,?,?)", (quest["ID"], "REFERENCE_READY", json.dumps(route)))
            connection.execute("INSERT OR REPLACE INTO quest_scene_resolution VALUES (?,?,?,?,?,?)", (
                quest["ID"], "REVIEWED_EXCEPTION", "NO_COMPLETE_AUTOMATIC_CHAIN_REVIEWED_REFERENCE_USED",
                json.dumps([relation["scene_package_id"]]), json.dumps([path_id]), "REFERENCE_READY"))
        connection.execute("INSERT INTO metadata VALUES (?,?)", ("quest_association_sha256", json.dumps(sha256(associations))))
    finally:
        world.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--db2", required=True)
    parser.add_argument("--decoded", action="append", required=True)
    parser.add_argument("--definitions", required=True)
    parser.add_argument("--definition-revision", required=True)
    parser.add_argument("--associations", help="Optional reviewed exceptions; automatic resolution always runs")
    parser.add_argument("--world-reference", required=True)
    args = parser.parse_args()
    build(args.output, args.db2, args.decoded, args.definitions, args.definition_revision,
          args.associations, args.world_reference)
