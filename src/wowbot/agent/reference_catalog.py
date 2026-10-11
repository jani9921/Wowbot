"""Versioned offline knowledge. Imported records are never live entity facts.

The world and DB2 hotfix namespaces are deliberately separate: identically
named tables in the two dumps do not necessarily describe the same thing.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
import uuid


WORLD_TABLES = frozenset({
    "creature", "creature_template", "creature_template_model",
    "creature_queststarter", "creature_questender", "quest_template",
    "quest_template_addon", "quest_objectives", "quest_request_items",
    "quest_offer_reward", "gossip_menu", "gossip_menu_option", "creature_text",
    "gameobject", "gameobject_template", "gameobject_queststarter",
    "gameobject_questender", "phase_name",
})
HOTFIX_TABLES = frozenset({
    "broadcast_text", "spell_name", "spell_effect", "spell_range",
    "spell_cast_times", "spell_cooldowns", "spell_duration", "spell_misc",
    "item", "item_sparse", "item_effect", "item_x_item_effect",
    "creature", "creature_display_info", "creature_display_info_extra",
    "creature_model_data", "map", "ui_map", "ui_map_assignment", "area_table",
    "quest_v2", "quest_line_x_quest", "campaign", "campaign_x_quest_line",
    "gossip_npc_option", "phase", "phase_x_phase_group",
})


def default_reference_path() -> Path:
    explicit = os.environ.get("AIPC_REFERENCE_CATALOG", "").strip()
    if explicit:
        return Path(explicit).resolve()
    root = Path(__file__).resolve().parents[3]
    config = root / "config" / "reference_catalog.local.json"
    if config.is_file():
        try:
            configured = json.loads(config.read_text(encoding="utf-8")).get("path")
            if configured:
                return Path(configured).expanduser().resolve()
        except (OSError, ValueError, TypeError):
            logging.getLogger(__name__).warning("Invalid local reference catalogue config", exc_info=True)
    paths = [root / "data" / "world_reference.sqlite3",
             root.parent / "data" / "world_reference.sqlite3"]
    return next((path for path in paths if path.is_file()), paths[0])


def dump_rows(text: str):
    """Parse MySQL VALUES as data, including escaped newlines and SQL NULL.

    Never execute source SQL, commands, triggers or functions. The selected
    source tables contain only literal strings, numbers, NULL and hex data.
    """
    row, chars, quoted, escaped, active, string = [], [], False, False, False, False
    escapes = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a"}
    for char in text:
        if escaped:
            chars.append(escapes.get(char, char)); escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == "'":
            quoted = not quoted; string = True
        elif quoted:
            chars.append(char)
        elif char == "(" and not active:
            active = True; row, chars, string = [], [], False
        elif active and char in ",)":
            raw = "".join(chars) if string else "".join(chars).strip()
            if string:
                value = raw
            elif raw == "NULL":
                value = None
            elif re.fullmatch(r"[-+]?\d+", raw):
                value = int(raw)
            elif re.fullmatch(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", raw):
                value = float(raw)
            elif re.fullmatch(r"0x[0-9a-fA-F]*", raw):
                value = raw  # Opaque data is not decoded or treated as executable.
            else:
                raise ValueError(f"Unsupported SQL literal: {raw[:60]}")
            row.append(value); chars, string = [], False
            if char == ")":
                yield row; active = False
        elif active and (string or not char.isspace()):
            chars.append(char)
    if quoted or active or escaped:
        raise ValueError("Incomplete SQL VALUES")


def build_reference(world: Path, hotfixes: Path | None, destination: Path) -> dict:
    """Build a NEW catalogue atomically; never replace learned databases."""
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".building-" + uuid.uuid4().hex)
    db = sqlite3.connect(temporary)
    counts: dict[str, int] = {}
    try:
        db.executescript("""
            CREATE TABLE sources(kind TEXT PRIMARY KEY, filename TEXT, sha256 TEXT);
            CREATE TABLE import_tables(kind TEXT, table_name TEXT, row_count INTEGER,
                PRIMARY KEY(kind,table_name));
            CREATE TABLE npc_templates(npc_id INTEGER PRIMARY KEY, name TEXT, data TEXT);
            CREATE INDEX npc_name ON npc_templates(name COLLATE NOCASE);
            CREATE TABLE quests(quest_id INTEGER PRIMARY KEY, title TEXT, description TEXT,
                objectives_text TEXT, completion_text TEXT, data TEXT);
            CREATE TABLE quest_objectives(objective_id INTEGER PRIMARY KEY, quest_id INTEGER,
                objective_order INTEGER, raw_type INTEGER, credit_object_id INTEGER,
                amount INTEGER, description TEXT, data TEXT);
            CREATE INDEX objective_quest ON quest_objectives(quest_id,objective_order);
            CREATE TABLE spawns(spawn_id INTEGER PRIMARY KEY,npc_id INTEGER,world_map_id INTEGER,
                x REAL,y REAL,z REAL,context TEXT);
            CREATE INDEX spawn_lookup ON spawns(world_map_id,npc_id);
            CREATE INDEX spawn_npc ON spawns(npc_id);
            CREATE TABLE quest_roles(npc_id INTEGER,quest_id INTEGER,role TEXT,verified_build INTEGER,
                PRIMARY KEY(npc_id,quest_id,role));
            CREATE INDEX quest_role_lookup ON quest_roles(role,npc_id);
            CREATE INDEX role_quest ON quest_roles(quest_id);
            CREATE TABLE records(kind TEXT,table_name TEXT,record_id TEXT,row_key TEXT,
                verified_build INTEGER,data TEXT,PRIMARY KEY(kind,table_name,row_key));
            CREATE INDEX record_lookup ON records(kind,table_name,record_id);
            CREATE TABLE provenance(source TEXT,sha256 TEXT,count INTEGER);
            PRAGMA user_version=1;
        """)
        for kind, source, selected in (("WORLD", world, WORLD_TABLES),
                                       ("HOTFIX", hotfixes, HOTFIX_TABLES)):
            if source is None:
                continue
            digest = hashlib.sha256()
            schemas, current = {}, None
            with source.open("rb") as stream:
                for raw in stream:
                    digest.update(raw)
                    line = raw.decode("utf-8")
                    match = re.match(r"CREATE TABLE `([^`]+)`", line)
                    if match:
                        current = match[1]; schemas[current] = []; continue
                    if current:
                        column = re.match(r"\s*`([^`]+)`", line)
                        if column:
                            schemas[current].append(column[1])
                        if line.startswith(")"):
                            current = None
                    match = re.match(r"INSERT INTO `([^`]+)` VALUES ", line)
                    if not match or match[1] not in selected:
                        continue
                    table = match[1]
                    if not schemas.get(table):
                        raise ValueError(f"Missing schema: {kind}.{table}")
                    batch = []
                    for values in dump_rows(line[match.end():]):
                        if len(values) != len(schemas[table]):
                            raise ValueError(f"Schema mismatch: {kind}.{table}")
                        row = dict(zip(schemas[table], values))
                        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                        counts[f"{kind}.{table}"] = counts.get(f"{kind}.{table}", 0) + 1
                        if kind == "WORLD" and table == "creature_template":
                            db.execute("INSERT INTO npc_templates VALUES (?,?,?)", (row["entry"], row["name"], encoded))
                        elif kind == "WORLD" and table == "quest_template":
                            db.execute("INSERT INTO quests VALUES (?,?,?,?,?,?)", (row["ID"], row.get("LogTitle"),
                                row.get("QuestDescription"), row.get("LogDescription"), row.get("QuestCompletionLog"), encoded))
                        elif kind == "WORLD" and table == "quest_objectives":
                            db.execute("INSERT INTO quest_objectives VALUES (?,?,?,?,?,?,?,?)", (row["ID"], row["QuestID"],
                                row.get("Order"), row.get("Type"), row.get("ObjectID"), row.get("Amount"), row.get("Description"), encoded))
                        elif kind == "WORLD" and table == "creature":
                            context = {k: row.get(k) for k in ("PhaseId", "PhaseGroup", "phaseUseFlags",
                                "terrainSwapMap", "spawnDifficulties", "MovementType", "wander_distance", "VerifiedBuild")}
                            db.execute("INSERT INTO spawns VALUES (?,?,?,?,?,?,?)", (row["guid"], row["id"], row["map"],
                                row["position_x"], row["position_y"], row["position_z"], json.dumps(context)))
                        elif kind == "WORLD" and table in {"creature_queststarter", "creature_questender"}:
                            role = "QUEST_STARTER" if table.endswith("starter") else "QUEST_ENDER"
                            db.execute("INSERT INTO quest_roles VALUES (?,?,?,?)", (row["id"], row["quest"], role, row.get("VerifiedBuild")))
                        else:
                            record_id = next((row[k] for k in ("CreatureID", "CreatureId", "QuestID", "ID", "Id", "id", "entry", "MenuID", "guid") if k in row), values[0])
                            row_key = hashlib.sha256(encoded.encode()).hexdigest()
                            batch.append((kind, table, str(record_id), row_key, row.get("VerifiedBuild"), encoded))
                    db.executemany("INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?)", batch)
            db.execute("INSERT INTO sources VALUES (?,?,?)", (kind, source.name, digest.hexdigest()))
            if kind == "WORLD":
                db.execute("INSERT INTO provenance VALUES (?,?,?)", (source.name, digest.hexdigest(), counts.get("WORLD.creature", 0)))
        db.executemany("INSERT INTO import_tables VALUES (?,?,?)", [(key.split(".")[0], key.split(".")[1], value) for key,value in counts.items()])
        db.commit()
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Catalogue integrity check failed")
        db.close()
        # No implicit overwrite even if another builder completed meanwhile.
        if destination.exists():
            raise FileExistsError(destination)
        temporary.rename(destination)
        return {"path": str(destination), "rows": counts}
    except BaseException:
        db.close()
        temporary.unlink(missing_ok=True)
        raise


class ReferenceCatalog:
    """Small cached queries over an immutable imported catalogue."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_reference_path()
        self.lock = threading.RLock()
        self.db = None
        self.available = False
        self.status = "MISSING"
        self.sources = []
        self.raw = None
        try:
            if not self.path.is_file():
                return
            self.db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True,
                                      check_same_thread=False)
            self.db.execute("PRAGMA query_only=ON")
            tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {"quest_template", "creature_template", "quest_objectives", "creature"} <= tables:
                from .reference_world_sqlite import WorldSqliteReference
                self.raw = WorldSqliteReference(self.db, self.lock, self.path, tables)
                self.available, self.status = True, "READY"
                self.sources = self.raw.sources
                return
            if self.db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Unsupported reference catalogue schema")
            for table in ("npc_templates", "quests", "quest_objectives", "spawns", "quest_roles", "records"):
                self.db.execute(f"SELECT * FROM {table} LIMIT 0")
            self.sources = [{"kind": k, "filename": f, "sha256": s} for k,f,s in
                            self.db.execute("SELECT kind,filename,sha256 FROM sources")]
            self.available = True
            self.status = "READY"
        except (sqlite3.Error, OSError, ValueError):
            logging.getLogger(__name__).warning("Reference catalogue unavailable: %s", self.path, exc_info=True)
            if self.db is not None:
                self.db.close(); self.db = None
            self.status = "INVALID"

    def diagnostics(self):
        return {"status": self.status, "available": self.available, "path": str(self.path),
                "sources": [dict(source) for source in self.sources], "read_only": True,
                "policy": "TDB_PRIMARY_LIVE_VERIFIED"}

    def provenance(self, kind="WORLD"):
        return next(({"source_file": s["filename"], "source_sha256": s["sha256"]}
                     for s in self.sources if s["kind"] == kind), {})

    def _rows(self, query, parameters=()):
        if not self.available:
            return []
        with self.lock:
            return self.db.execute(query, parameters).fetchall()

    @lru_cache(maxsize=256)
    def find_by_name(self, name: str, limit=10) -> tuple[dict, ...]:
        if self.raw is not None:
            return self.raw.find_by_name(name, limit)
        return tuple({"identity_key": f"npc:{npc}", "npc_id": npc, "name": title,
                      "unit_type": "NPC", "seen_count": 0, "source": "TDB_REFERENCE",
                      "confirmed": False, **self.provenance()} for npc,title in self._rows(
            "SELECT npc_id,name FROM npc_templates WHERE name=? COLLATE NOCASE ORDER BY npc_id LIMIT ?", (name.strip(), limit)))

    @lru_cache(maxsize=128)
    def spawn_candidates(self, world_map_id, npc_id):
        if self.raw is not None:
            return self.raw.spawn_candidates(world_map_id, npc_id)
        if world_map_id is None or npc_id is None:
            return ()
        return tuple({"spawn_id": r[0], "npc_id": r[1], "world_map_id": r[2],
                      "x": r[3], "y": r[4], "z": r[5], "context": json.loads(r[6]),
                      "coordinate_space": "WORLD_YARDS", "source": "TDB_REFERENCE",
                      "confirmed": False, "navigation_trusted": False, "belief": "CANDIDATE",
                      **self.provenance()} for r in self._rows(
            "SELECT * FROM spawns WHERE world_map_id=? AND npc_id=? ORDER BY spawn_id", (world_map_id,npc_id)))

    @lru_cache(maxsize=8)
    def role_candidates(self, world_map_id, role="QUEST_STARTER"):
        if self.raw is not None:
            return self.raw.role_candidates(world_map_id, role)
        if world_map_id is None:
            return ()
        return tuple({"spawn_id": r[0], "npc_id": r[1], "world_map_id": r[2],
                      "x": r[3], "y": r[4], "z": r[5], "context": json.loads(r[6]),
                      "quest_ids": [int(q) for q in r[7].split(",")], "verified_build": r[8],
                      "role_hypothesis": role, "coordinate_space": "WORLD_YARDS",
                      "source": "TDB_REFERENCE", "confirmed": False,
                      "navigation_trusted": False, "belief": "CANDIDATE", **self.provenance()}
                     for r in self._rows(
            "SELECT s.*,GROUP_CONCAT(q.quest_id),MAX(q.verified_build) "
            "FROM spawns s JOIN quest_roles q ON q.npc_id=s.npc_id "
            "WHERE s.world_map_id=? AND q.role=? GROUP BY s.spawn_id ORDER BY s.spawn_id", (world_map_id,role)))

    @lru_cache(maxsize=128)
    def records(self, kind: str, table: str, record_id: int) -> tuple[dict, ...]:
        if self.raw is not None:
            return self.raw.records(kind, table, record_id)
        return tuple(json.loads(row[0]) for row in self._rows(
            "SELECT data FROM records WHERE kind=? AND table_name=? AND record_id=? ORDER BY verified_build DESC LIMIT 32",
            (kind, table, str(record_id))))

    @lru_cache(maxsize=128)
    def npc(self, npc_id: int) -> dict | None:
        if self.raw is not None:
            return self.raw.npc(npc_id)
        rows = self._rows("SELECT name,data FROM npc_templates WHERE npc_id=?", (npc_id,))
        if not rows:
            return None
        return {"npc_id": npc_id, "name": rows[0][0], "source": "TDB_REFERENCE", "confirmed": False,
                **self.provenance(),
                "template": json.loads(rows[0][1]),
                "models": list(self.records("WORLD", "creature_template_model", npc_id)),
                "quest_roles": [{"quest_id": q, "role": r} for q,r in self._rows(
                    "SELECT quest_id,role FROM quest_roles WHERE npc_id=?", (npc_id,))]}

    @lru_cache(maxsize=128)
    def quest(self, quest_id: int) -> dict | None:
        if self.raw is not None:
            return self.raw.quest(quest_id)
        rows = self._rows("SELECT title,description,objectives_text,completion_text FROM quests WHERE quest_id=?", (quest_id,))
        if not rows:
            return None
        title,description,objectives_text,completion_text = rows[0]
        return {"quest_id": quest_id, "title": title, "description": description,
                "objectives_text": objectives_text, "completion_text": completion_text,
                "source": "TDB_REFERENCE", "confirmed": False,
                **self.provenance(),
                "objectives": [{"objective_id": r[0], "order": r[1], "raw_type": r[2],
                    "credit_object_id": r[3], "amount": r[4], "description": r[5]}
                    for r in self._rows("SELECT objective_id,objective_order,raw_type,credit_object_id,amount,description FROM quest_objectives WHERE quest_id=? ORDER BY objective_order", (quest_id,))],
                "quest_roles": [{"npc_id": n, "role": r} for n,r in self._rows(
                    "SELECT npc_id,role FROM quest_roles WHERE quest_id=?", (quest_id,))],
                "details": list(self.records("WORLD", "quest_template_addon", quest_id))}

    def close(self):
        with self.lock:
            if self.db is not None:
                self.db.close(); self.db = None
            self.available = False
            self.status = "CLOSED"
            self.raw = None
        self.find_by_name.cache_clear(); self.records.cache_clear()
        self.npc.cache_clear(); self.quest.cache_clear()
        self.spawn_candidates.cache_clear(); self.role_candidates.cache_clear()
