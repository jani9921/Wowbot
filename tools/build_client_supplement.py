"""Verified, atomic DB2 supplement import; original client/TDB catalogues stay read-only."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_client_catalog import sha256, source_metadata

REQUIRED = {"ItemEffect", "ItemXItemEffect", "ItemSparse", "AreaTrigger", "ConversationLine",
            "SpellMisc", "SpellName", "SpellRange", "SpellTargetRestrictions"}
OPTIONAL = {"AreaTriggerSphere", "AreaTriggerBox", "AreaTriggerCylinder",
            "AreaTriggerDisk", "AreaTriggerBoundedPlane", "SpellRadius", "SpellDuration"}

SCHEMA = """
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE source_files(table_name TEXT PRIMARY KEY,path TEXT,sha256 TEXT,definition_sha256 TEXT,
 layout_hash TEXT,schema_label TEXT,decoded_rows INTEGER);
CREATE TABLE db2_rows(table_name TEXT,id INTEGER,record_json TEXT NOT NULL,
 PRIMARY KEY(table_name,id)) WITHOUT ROWID;
CREATE TABLE item_effects(id INTEGER PRIMARY KEY,spell_id INTEGER,trigger_type INTEGER,
 slot INTEGER,charges INTEGER,cooldown_ms INTEGER,category_cooldown_ms INTEGER,category_id INTEGER,
 specialization_id INTEGER,condition_id INTEGER);
CREATE TABLE item_effect_links(id INTEGER PRIMARY KEY,item_id INTEGER,effect_id INTEGER);
CREATE INDEX item_links_item ON item_effect_links(item_id);
CREATE TABLE items(id INTEGER PRIMARY KEY,name TEXT,description TEXT,start_quest_id INTEGER);
CREATE TABLE spell_misc(id INTEGER PRIMARY KEY,spell_id INTEGER,difficulty_id INTEGER,range_id INTEGER);
CREATE INDEX spell_misc_spell ON spell_misc(spell_id,difficulty_id);
CREATE TABLE spell_names(id INTEGER PRIMARY KEY,name TEXT);
CREATE TABLE spell_targets(id INTEGER PRIMARY KEY,spell_id INTEGER,difficulty_id INTEGER,
 target_mask INTEGER,creature_mask INTEGER);
CREATE INDEX spell_targets_spell ON spell_targets(spell_id,difficulty_id);
CREATE TABLE spell_effects(id INTEGER PRIMARY KEY,spell_id INTEGER,difficulty_id INTEGER,
 effect INTEGER,aura INTEGER,trigger_spell INTEGER,misc1 INTEGER,item_type INTEGER,target_a INTEGER,target_b INTEGER);
CREATE INDEX spell_effects_spell ON spell_effects(spell_id,difficulty_id);
CREATE INDEX spell_effects_credit ON spell_effects(effect,misc1);
CREATE TABLE area_triggers(id INTEGER PRIMARY KEY,map_id INTEGER,x REAL,y REAL,z REAL);
CREATE INDEX area_trigger_map ON area_triggers(map_id);
CREATE TABLE conversation_lines(id INTEGER PRIMARY KEY,next_line_id INTEGER,additional_duration_ms INTEGER);
"""


def index_row(db, table, key, row):
    def insert(name, fields):
        db.execute("INSERT INTO " + name + " VALUES (" + ",".join("?" for _ in range(len(fields)+1)) + ")",
                   [key, *(row.get(f) for f in fields)])
    if table == "ItemEffect":
        insert("item_effects", ["SpellID", "TriggerType", "LegacySlotIndex", "Charges", "CoolDownMSec",
                               "CategoryCoolDownMSec", "SpellCategoryID", "ChrSpecializationID", "PlayerConditionID"])
    elif table == "ItemXItemEffect":
        insert("item_effect_links", ["ItemID", "ItemEffectID"])
    elif table == "ItemSparse":
        insert("items", ["Display_lang", "Description_lang", "StartQuestID"])
    elif table == "SpellMisc":
        insert("spell_misc", ["SpellID", "DifficultyID", "RangeIndex"])
    elif table == "SpellName":
        insert("spell_names", ["Name_lang"])
    elif table == "SpellTargetRestrictions":
        insert("spell_targets", ["SpellID", "DifficultyID", "Targets", "TargetCreatureType"])
    elif table == "ConversationLine":
        insert("conversation_lines", ["NextConversationLineID", "AdditionalDuration"])
    elif table == "AreaTrigger":
        db.execute("INSERT INTO area_triggers VALUES (?,?,?,?,?)", (key, row["ContinentID"], *row["Pos"]))


def build(output, source, decoded, definitions, client_catalog, definition_revision):
    output, source, decoded, definitions = map(Path, (output, source, decoded, definitions))
    if output.exists():
        raise FileExistsError(output)
    available = {p.stem for p in decoded.glob("*.jsonl")}
    if REQUIRED - available:
        raise ValueError("Missing decoded tables: " + ", ".join(sorted(REQUIRED-available)))
    temporary = output.with_name(output.name + ".partial-" + uuid4().hex)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.executescript(SCHEMA)
            metadata = {"schema_version": 1, "decoder": "DBCD 2.3.0",
                        "definitions_revision": definition_revision, "source_kind": "LOCAL_EXTRACTED_CLIENT_DB2",
                        "live_build_validation": "NOT_VALIDATED", "schema_label_is_live_build": False}
            for table in sorted(REQUIRED | (OPTIONAL & available)):
                original, definition = source/(table+".db2"), definitions/(table+".dbd")
                header = source_metadata(original)
                source_hash, definition_hash = sha256(original), sha256(definition)
                with (decoded/(table+".jsonl")).open(encoding="utf-8-sig") as stream:
                    manifest = json.loads(next(stream))
                    if (manifest.get("type") != "table" or manifest.get("name") != table
                            or manifest.get("source_sha256") != source_hash
                            or manifest.get("definition_sha256") != definition_hash
                            or manifest.get("layout_hash") != header["layout_hash"]):
                        raise ValueError("DB2/DBD export provenance mismatch: " + table)
                    count = 0
                    for line in stream:
                        entry = json.loads(line)
                        row, key = entry["values"], entry["id"]
                        if entry.get("type") != "row" or entry.get("table") != table or row.get("ID") != key:
                            raise ValueError("Invalid DB2 row identity: " + table)
                        db.execute("INSERT INTO db2_rows VALUES (?,?,?)",
                                   (table, key, json.dumps(row, separators=(",", ":"), allow_nan=False)))
                        index_row(db, table, key, row)
                        count += 1
                    if count != manifest["row_count"]:
                        raise ValueError("Truncated DB2 export: " + table)
                db.execute("INSERT INTO source_files VALUES (?,?,?,?,?,?,?)",
                           (table, str(original.resolve()), source_hash, definition_hash,
                            header["layout_hash"], header["schema_label"], count))
                print(f"{table}: {count}", flush=True)
            # Copy only item-root/reachable SpellEffect records from the verified
            # existing export, preserving difficulty and implicit targets.
            with closing(sqlite3.connect(Path(client_catalog).resolve().as_uri()+"?mode=ro", uri=True)) as client:
                origin = client.execute("SELECT sha256 FROM source_files WHERE table_name='SpellEffect'").fetchone()
                if not origin or origin[0] != sha256(source/"SpellEffect.db2"):
                    raise ValueError("SpellEffect source version mismatch")
                metadata["spell_effect_source_sha256"] = origin[0]
                pending = {r[0] for r in db.execute("SELECT DISTINCT spell_id FROM item_effects WHERE spell_id>0")}
                seen = set()
                while pending:
                    spell = pending.pop()
                    if spell in seen:
                        continue
                    seen.add(spell)
                    for (raw,) in client.execute("""SELECT r.record_json FROM spell_effects s
                        JOIN db2_rows r ON r.table_name='SpellEffect' AND r.id=s.id WHERE s.spell_id=?""", (spell,)):
                        row = json.loads(raw)
                        targets = row["ImplicitTarget"]
                        db.execute("INSERT INTO db2_rows VALUES (?,?,?)", ("SpellEffect", row["ID"], raw))
                        db.execute("INSERT INTO spell_effects VALUES (?,?,?,?,?,?,?,?,?,?)",
                                   (row["ID"], spell, row["DifficultyID"], row["Effect"], row["EffectAura"],
                                    row["EffectTriggerSpell"], row["EffectMiscValue"][0],
                                    row["EffectItemType"], targets[0], targets[1]))
                        if row["EffectTriggerSpell"] > 0:
                            pending.add(row["EffectTriggerSpell"])
            metadata["orphan_effect_links"] = db.execute("""SELECT COUNT(*) FROM item_effect_links l
                LEFT JOIN item_effects e ON e.id=l.effect_id WHERE e.id IS NULL""").fetchone()[0]
            db.executemany("INSERT INTO metadata VALUES (?,?)", [(k, json.dumps(v)) for k,v in metadata.items()])
            db.execute("PRAGMA user_version=1")
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Supplement integrity check failed")
        if output.exists():
            raise FileExistsError(output)
        temporary.rename(output)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "db2", "decoded", "definitions", "client-catalog", "definition-revision"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    build(args.output, args.db2, args.decoded, args.definitions, args.client_catalog, args.definition_revision)
