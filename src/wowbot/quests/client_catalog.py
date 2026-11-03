"""Read-only indexed SQLite client DB2/reference catalog; no online fallback."""
from __future__ import annotations

from functools import lru_cache
from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3


def default_catalog_path():
    return Path(__file__).resolve().parents[3] / "data" / "client_reference.sqlite3"


class ClientCatalog:
    def __init__(self, path=None):
        self.path = Path(path or default_catalog_path()).resolve()
        from .client_supplement import ClientSupplement
        self.supplement = ClientSupplement(self.path.with_name("client_supplement.sqlite3"))

    def courses(self):
        if not self.path.is_file():
            return {}
        stamp = self.path.stat()
        return json.loads(_course_json(str(self.path), stamp.st_mtime_ns, stamp.st_size))

    def _query(self, kind, identifier=0, limit=128):
        if not self.path.is_file():
            return {}
        stamp = self.path.stat()
        return json.loads(_query_json(str(self.path), stamp.st_mtime_ns, stamp.st_size,
                                      kind, identifier, max(1, min(4096, int(limit)))))

    def quest(self, quest_id, *, details=False):
        """Any indexed client quest, supplementary to the existing TDB provider."""
        if type(quest_id) is not int or quest_id <= 0:
            return {}
        return self._query("quest_details" if details else "quest", quest_id)

    def scene_resolution(self, quest_id, *, details=False):
        return self._query("resolution_details" if details else "resolution", int(quest_id))

    def path_nodes(self, path_id, *, limit=4096):
        return self._query("path", int(path_id), limit)

    def scene(self, package_id):
        return self._query("scene", int(package_id))

    def record(self, table, record_id):
        # Table names are bound VALUES, never interpolated SQL identifiers.
        return self._query("record", (str(table), int(record_id)))

    def item_use(self, item_id):
        return self.supplement.item(item_id)

    def scene_course(self, package_id, start, quest_ids=()):
        """The ring course a running client scene flies, from the DB2 alone.

        User 2026-10-25 (the Skytop Observatory race, no hand binding): the
        server names the scene package live; its scene script must be the
        Checkpoint/RaceComplete ring mechanic, and one of its paths must be
        the one flown -- selected by a PlayerCondition on a quest in the log,
        else as the only path starting within SCENE_START_YARDS of where the
        scene began (the start line).  Easy/hard twins sharing a start are
        ambiguous: None, never a guess.  Returns (course | None, reason).
        """
        if not self.path.is_file() or type(package_id) is not int or package_id <= 0:
            return None, "no_catalog"
        try:
            sx, sy = float(start["x"]), float(start["y"])
        except (KeyError, TypeError, ValueError):
            return None, "no_scene_start_position"
        stamp = self.path.stat()
        data = json.loads(_scene_paths_json(str(self.path), stamp.st_mtime_ns, stamp.st_size, package_id))
        if not data.get("ring_mechanic"):
            return None, data.get("reason") or "unsupported_scene_mechanic"
        paths = data["paths"]
        quests = {int(q) for q in quest_ids if str(q).isdigit()}
        chosen = {p["path_id"] for p in paths if quests & set(p["condition_quests"])}
        reason = "PLAYER_CONDITION_CURRENT_QUEST"
        if len(paths) == 1:
            chosen, reason = {paths[0]["path_id"]}, "ONLY_PATH_OF_THE_SCENE"
        elif len(chosen) != 1:
            near = sorted((math.hypot(p["nodes"][0][0]-sx, p["nodes"][0][1]-sy), p["path_id"]) for p in paths)
            near = [row for row in near if row[0] <= SCENE_START_YARDS]
            if len({path_id for _d, path_id in near}) != 1:
                return None, "ambiguous_scene_path" if near else "no_scene_path_near_start"
            chosen, reason = {near[0][1]}, "ONLY_PATH_STARTING_AT_THE_SCENE_START"
        (path,) = [p for p in paths if p["path_id"] in chosen]
        nodes = path["nodes"]
        return {"scene_package": package_id, "path_id": path["path_id"], "rings": nodes[:-1], "target": nodes[-1],
                "selection": reason, "coordinate_source": "LOCAL_DB2_SCENE_PATH_LOCATION"}, "resolved"

    def scene_actor_spawns(self, package_id):
        """{creature id: [points]} a client scene spawns at DB2 path points.

        Live 2026-10-25 10:51 (Giant Boar, quest 55879): the eight Monstrous
        Cadavers (165150, ``CID_GIANTZOMBIE``) are scene ClientActors -- no
        server unit, no packet -- spawned by ``Spawn...(CID_GIANTZOMBIE,
        36040, ...)``; their places are those paths' nodes (world yards).
        Only literal or constant creature ids and literal path ids count."""
        if not self.path.is_file() or type(package_id) is not int or package_id <= 0:
            return {}
        stamp = self.path.stat()
        return {int(k): v for k, v in json.loads(
            _scene_actor_json(str(self.path), stamp.st_mtime_ns, stamp.st_size, package_id)).items()}

    def spell_effects(self, spell_id):
        """A spell's DB2 SpellEffect rows: effect, aura, trigger spell, implicit
        targets, radius indices (any difficulty), in effect-index order."""
        if type(spell_id) is not int or spell_id <= 0:
            return []
        return self._query("spell_effects", spell_id).get("effects") or []

    def kill_credit_spells(self, credit_entry):
        """Spells whose DB2 effect is KILL_CREDIT (90) or KILL_CREDIT2 (134)
        for this creature entry (EffectMiscValue[0])."""
        if type(credit_entry) is not int or credit_entry <= 0:
            return []
        return self._query("kill_credit_spells", credit_entry).get("spells") or []
    def diagnostics(self):
        result = self._query("stats")
        return {"status": "READY" if result else "MISSING_OR_INVALID", "path": str(self.path),
                "read_only": True, **result, "supplement": self.supplement.diagnostics()}


@lru_cache(maxsize=8)
def _course_json(path, modified, size):
    try:
        with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute("SELECT quest_id, route_json FROM quest_routes WHERE status='REFERENCE_READY'")
            return json.dumps({str(key): json.loads(value) for key, value in rows})
    except (sqlite3.Error, ValueError):
        return "{}"


SCENE_START_YARDS = 60.
# The ring mechanic shape ring_course() (scene_resolver) recognizes.
RING_MECHANIC = (r'\bRingHitDistance\s*=\s*\d+', r'TriggerServerEvent\s*\(\s*["\']Checkpoint["\']',
                 r'TriggerServerEvent\s*\(\s*["\']RaceComplete["\']', r'\blaps\s*=\s*1\b',
                 r'SetRelativeCoords\s*\(\s*false', r'LoadPath\s*\(\s*pathID\s*\)', r'\bmaxCheckpoints\s*=\s*#rings')


@lru_cache(maxsize=64)
def _scene_paths_json(path, modified, size, package_id):
    """Every candidate path of one scene package with its nodes and the
    current-quest PlayerConditions that select it (read-only, cached)."""
    try:
        with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            text = "\n".join(re.sub(r"--[^\r\n]*", "", json.loads(raw).get("Script", "")) for (raw,) in db.execute(
                """SELECT r.record_json FROM scene_scripts s JOIN db2_rows r
                   ON r.table_name='SceneScriptText' AND r.id=s.script_id WHERE s.package_id=?""", (package_id,)))
            if not text:
                return json.dumps({"ring_mechanic": False, "reason": "unknown_scene_package"})
            if (not all(re.search(pattern, text) for pattern in RING_MECHANIC)
                    or re.search(r'SetRelativeCoords\s*\(\s*true', text)
                    or {int(n) for n in re.findall(r'\blaps\s*=\s*(\d+)\b', text)} != {1}):
                return json.dumps({"ring_mechanic": False, "reason": "unsupported_scene_mechanic"})
            ids = [r[0] for r in db.execute("""SELECT path_id FROM scene_paths WHERE package_id=?
                UNION SELECT path_id FROM scene_path_candidates WHERE package_id=?""", (package_id, package_id))]
            paths = []
            for path_id in ids[:256]:
                nodes = [list(row) for row in db.execute(
                    """SELECT l.x,l.y,l.z FROM path_nodes n LEFT JOIN locations l ON l.id=n.location_id
                       WHERE n.path_id=? ORDER BY n.sequence,n.id""", (path_id,))]
                if not 2 <= len(nodes) <= 129 or not all(
                        type(v) in {int, float} and math.isfinite(v) for node in nodes for v in node):
                    continue
                quests = set()
                for (condition,) in db.execute("""SELECT condition_id FROM scene_path_candidates
                        WHERE package_id=? AND path_id=? AND kind='PLAYER_CONDITION_TABLE'""", (package_id, path_id)):
                    row = db.execute("SELECT record_json FROM db2_rows WHERE table_name='PlayerCondition' AND id=?",
                                     (condition,)).fetchone()
                    values = (json.loads(row[0]).get("CurrQuestID") if row else None) or []
                    quests.update(q for q in (values if isinstance(values, list) else [values]) if type(q) is int and q > 0)
                paths.append({"path_id": path_id, "nodes": nodes, "condition_quests": sorted(quests)})
            return json.dumps({"ring_mechanic": True, "paths": paths})
    except (sqlite3.Error, ValueError, TypeError):
        return json.dumps({"ring_mechanic": False, "reason": "catalog_error"})


_SPAWN_CALL = re.compile(r'\bSpawnActor\w*\s*\(\s*([A-Za-z_]\w*|\d+)\s*,\s*(\d+)\b')
_CONSTANT = re.compile(r'^\s*([A-Z][A-Z0-9_]*)\s*=\s*(\d+)\s*(?:--.*)?$', re.M)


@lru_cache(maxsize=64)
def _scene_actor_json(path, modified, size, package_id):
    try:
        with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            text = "\n".join(re.sub(r"--[^\r\n]*", "", json.loads(raw).get("Script", "")) for (raw,) in db.execute(
                """SELECT r.record_json FROM scene_scripts s JOIN db2_rows r
                   ON r.table_name='SceneScriptText' AND r.id=s.script_id WHERE s.package_id=?""", (package_id,)))
            constants = {name: int(value) for name, value in _CONSTANT.findall(text)}
            result: dict[str, list] = {}
            for token, path_id in _SPAWN_CALL.findall(text):
                creature = int(token) if token.isdigit() else constants.get(token)
                if creature is None or creature <= 0:
                    continue
                for x, y, z in db.execute("""SELECT l.x,l.y,l.z FROM path_nodes n LEFT JOIN locations l
                        ON l.id=n.location_id WHERE n.path_id=? ORDER BY n.sequence,n.id LIMIT 256""", (int(path_id),)):
                    if all(type(v) in {int, float} and math.isfinite(v) for v in (x, y, z)):
                        result.setdefault(str(creature), []).append({"x": x, "y": y, "z": z, "path_id": int(path_id)})
            return json.dumps(result)
    except (sqlite3.Error, ValueError, TypeError):
        return "{}"


@lru_cache(maxsize=256)
def _query_json(path, modified, size, kind, identifier, limit):
    try:
        with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            result = _query(connection, kind, identifier, limit)
            return json.dumps(result)
    except (sqlite3.Error, ValueError, TypeError):
        return "{}"


def _query(db, kind, identifier, limit):
    if kind == "stats":
        counts = {"source_files": "SELECT COUNT(*) FROM source_files",
                  "decoded_tables": "SELECT COUNT(*) FROM source_files WHERE decoded_rows IS NOT NULL",
                  "quest_ids": "SELECT COUNT(DISTINCT quest_id) FROM quest_links",
                  "scene_packages": "SELECT COUNT(*) FROM db2_rows WHERE table_name='SceneScriptPackage'",
                  "scene_scripts": "SELECT COUNT(*) FROM db2_rows WHERE table_name='SceneScriptText'",
                  "path_ids": "SELECT COUNT(DISTINCT path_id) FROM path_nodes",
                  "scene_path_packages": "SELECT COUNT(DISTINCT package_id) FROM scene_paths",
                  "poi_blobs": "SELECT COUNT(*) FROM poi_blobs",
                  "poi_points": "SELECT COUNT(*) FROM poi_points",
                  "reviewed_quest_paths": "SELECT COUNT(*) FROM quest_routes WHERE json_extract(route_json,'$.association_kind')='REVIEWED_REFERENCE_RELATION'",
                  "automatic_ring_routes": "SELECT COUNT(*) FROM quest_routes WHERE json_extract(route_json,'$.association_kind')='TDB_DB2_STRUCTURAL_REFERENCE'",
                  "quest_scene_candidates": "SELECT COUNT(*) FROM quest_scene_candidates",
                  "quests_with_scene_candidates": "SELECT COUNT(DISTINCT quest_id) FROM quest_scene_candidates",
                  "automatic_scene_references": "SELECT COUNT(*) FROM quest_scene_resolution WHERE status='RESOLVED_REFERENCE'",
                  "ambiguous_scene_references": "SELECT COUNT(*) FROM quest_scene_resolution WHERE status IN ('AMBIGUOUS','PARTIAL')",
                  "missing_scene_templates": "SELECT COUNT(*) FROM spell_scene_edges WHERE status='MISSING_SCENE_TEMPLATE'"}
        counts["condition_table_path_bindings"]="SELECT COUNT(*) FROM scene_path_candidates WHERE kind='PLAYER_CONDITION_TABLE'"
        return {key: db.execute(sql).fetchone()[0] for key, sql in counts.items()}
    if kind == "record":
        row = db.execute("SELECT record_json FROM db2_rows WHERE table_name=? AND id=?", identifier).fetchone()
        return json.loads(row[0]) if row else {}
    if kind == "kill_credit_spells":
        return {"spells": [row[0] for row in db.execute(
            "SELECT DISTINCT spell_id FROM spell_effects WHERE effect IN (90,134) AND misc1=? "
            "ORDER BY spell_id LIMIT 32", (identifier,))]}
    if kind == "spell_effects":
        effects = []
        for (raw,) in db.execute("""SELECT r.record_json FROM spell_effects s JOIN db2_rows r
                ON r.table_name='SpellEffect' AND r.id=s.id WHERE s.spell_id=? ORDER BY s.id LIMIT 64""", (identifier,)):
            r = json.loads(raw)
            effects.append({"index": r.get("EffectIndex"), "effect": r.get("Effect"), "aura": r.get("EffectAura"),
                            "trigger_spell": r.get("EffectTriggerSpell"), "difficulty": r.get("DifficultyID"),
                            "targets": list(r.get("ImplicitTarget") or ()),
                            "radius_index": list(r.get("EffectRadiusIndex") or ())})
        return {"effects": sorted(effects, key=lambda e: (e["difficulty"] or 0, e["index"] or 0))}
    if kind in {"resolution", "resolution_details"}:
        row = db.execute("SELECT status,reason,packages_json,path_ids_json,route_status FROM quest_scene_resolution WHERE quest_id=?", (identifier,)).fetchone()
        seeds = db.execute("SELECT seed_count FROM quest_scene_seeds WHERE quest_id=?", (identifier,)).fetchone()
        if row:
            status, reason, packages, paths, route_status = row
        else:
            status, reason, packages, paths, route_status = (
                "UNRESOLVED", "NO_SCENE_EFFECT_REACHED" if seeds else "NO_EXPLICIT_QUEST_SOURCE_RELATION", "[]", "[]", "NO_ROUTE")
        maximum = limit if kind == "resolution_details" else 8
        rows = db.execute("SELECT package_id,scene_id,phase,conditional,status,evidence_json FROM quest_scene_candidates WHERE quest_id=? ORDER BY id LIMIT ?", (identifier,maximum)).fetchall()
        count = db.execute("SELECT COUNT(*) FROM quest_scene_candidates WHERE quest_id=?",(identifier,)).fetchone()[0]
        candidates = [{"package_id":r[0], "scene_id":r[1], "phase":r[2], "conditional":bool(r[3]), "status":r[4],
                       **({"evidence":json.loads(r[5])} if kind == "resolution_details" else {})} for r in rows]
        path_ids=json.loads(paths)
        unique=path_ids[0] if len(path_ids)==1 else None
        return {"quest_id":identifier,"status":status,"reason":reason,"package_ids":json.loads(packages),
                "path_ids":path_ids,"unique_path_id":unique,
                "path_reference":_query(db,"path",unique,limit) if unique is not None else None,
                "route_status":route_status,"seed_count":seeds[0] if seeds else 0,
                "candidate_count":count,"candidates":candidates,"candidates_omitted":max(0,count-len(rows)),
                "confirmed_live":False}
    if kind == "path":
        rows = db.execute("""SELECT n.id,n.sequence,n.location_id,l.x,l.y,l.z,l.rot_json
            FROM path_nodes n LEFT JOIN locations l ON l.id=n.location_id
            WHERE n.path_id=? ORDER BY n.sequence,n.id LIMIT ?""", (identifier, limit)).fetchall()
        count = db.execute("SELECT COUNT(*) FROM path_nodes WHERE path_id=?", (identifier,)).fetchone()[0]
        return {"path_id": identifier, "node_count": count, "omitted": max(0, count-len(rows)),
                "geometry_complete": bool(rows) and count == len(rows)
                    and len({r[1] for r in rows}) == count and all(r[3] is not None for r in rows),
                "nodes": [{"node_id": r[0], "sequence": r[1], "location_id": r[2],
                           "x": r[3], "y": r[4], "z": r[5], "rotation": json.loads(r[6]) if r[6] else None}
                          for r in rows], "source": "LOCAL_DB2", "navigation_trusted": False}
    if kind == "scene":
        package = _query(db, "record", ("SceneScriptPackage", identifier), limit)
        if not package:
            return {}
        scripts = [r[0] for r in db.execute(
            "SELECT script_id FROM scene_scripts WHERE package_id=? ORDER BY script_id LIMIT ?", (identifier, limit))]
        count = db.execute("SELECT COUNT(*) FROM scene_scripts WHERE package_id=?", (identifier,)).fetchone()[0]
        paths = [r[0] for r in db.execute(
            "SELECT DISTINCT path_id FROM scene_paths WHERE package_id=? ORDER BY path_id", (identifier,))]
        candidates = [{"path_id":p,"script_id":s,"condition_id":c,"kind":k} for p,s,c,k in db.execute(
            "SELECT path_id,script_id,condition_id,kind FROM scene_path_candidates WHERE package_id=? ORDER BY path_id,script_id,condition_id LIMIT ?",(identifier,limit))]
        return {"package_id": identifier, "package": package, "script_ids": scripts,
                "script_count": count, "scripts_omitted": max(0, count-len(scripts)),
                "path_ids": paths, "path_resolution": "UNIQUE_LITERAL" if len(paths) == 1
                    else "MULTIPLE_CANDIDATES" if paths else "NO_SUPPORTED_LITERAL",
                "path_candidates":candidates,"execution_supported": False, "source": "LOCAL_DB2"}
    if kind in {"quest", "quest_details"}:
        counts = dict(db.execute("SELECT table_name,COUNT(*) FROM quest_links WHERE quest_id=? GROUP BY table_name", (identifier,)))
        route = db.execute("SELECT route_json FROM quest_routes WHERE quest_id=? AND status='REFERENCE_READY'", (identifier,)).fetchone()
        resolution = _query(db,"resolution_details" if kind == "quest_details" else "resolution",identifier,limit)
        if not counts and not route and not resolution["candidate_count"]:
            return {}
        course = json.loads(route[0]) if route else None
        result = {"quest_id": identifier, "source": "LOCAL_DB2", "tables": counts,
                  "confirmed": False, "navigation_trusted": False,
                  "scene_association": course["association_kind"] if course else resolution["status"],
                  "scene_resolution": resolution, "ordered_path": course,
                  "runtime_policy": "SUPPLEMENTS_EXISTING_TDB_AND_SHARED_QUEST_PLANNER"}
        if kind == "quest_details":
            rows = db.execute("""SELECT l.table_name,l.record_id,r.record_json FROM quest_links l
                JOIN db2_rows r ON r.table_name=l.table_name AND r.id=l.record_id
                WHERE l.quest_id=? ORDER BY l.table_name,l.record_id LIMIT ?""", (identifier, limit)).fetchall()
            result["records"] = [{"table": t, "record_id": i, "data": json.loads(raw)} for t, i, raw in rows]
            result["records_omitted"] = max(0, sum(counts.values())-len(rows))
            points = db.execute("""SELECT p.id,p.blob_id,p.x,p.y,p.z,b.map_id,b.ui_map_id FROM poi_points p
                JOIN poi_blobs b ON b.id=p.blob_id WHERE b.quest_id=? ORDER BY p.blob_id,p.id LIMIT 4096""", (identifier,)).fetchall()
            result["poi_points"] = [dict(zip(("point_id", "blob_id", "x", "y", "z", "instance_id", "ui_map_id"), row))
                                    for row in points]
            result["poi_geometry_role"] = "REFERENCE_GEOMETRY_NOT_ORDERED_MOVEMENT_ROUTE"
        return result
    return {}
