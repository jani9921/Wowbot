"""Read the user's unmodified Trinity WORLD SQLite as primary static knowledge.

SQL identifiers below are code-owned allowlists, never imported commands.
POI points are geometry, not creature positions or a precomputed route.
"""
from __future__ import annotations

from functools import cached_property, lru_cache
import hashlib
from collections import Counter
from .tdb_builds import build_number, newest_rows


# Explicit schema contracts: callers cannot inject table/column/SQL identifiers.
RECORD_KEYS = {
    'creature_template_model': 'CreatureID', 'quest_template_addon': 'ID',
    'quest_request_items': 'ID', 'quest_offer_reward': 'ID', 'quest_details': 'ID',
    'gameobject_template': 'entry', 'creature_template_gossip': 'CreatureID',
    'gossip_menu': 'MenuID', 'gossip_menu_option': 'MenuID',
    'npc_spellclick_spells': 'npc_entry', 'npc_vendor': 'entry',
    'creature_trainer': 'CreatureID', 'trainer': 'Id', 'trainer_spell': 'TrainerId',
    'creature_template_difficulty': 'Entry', 'creature_template_spell': 'CreatureID',
    'creature_template_resistance': 'CreatureID', 'creature_immunities': 'ID',
    'quest_objectives_completion_effect': 'ObjectiveID',
    'quest_completion_log_conditional': 'QuestId', 'quest_description_conditional': 'QuestId',
    'quest_request_items_conditional': 'QuestId', 'quest_offer_reward_conditional': 'QuestId',
    'quest_reward_display_spell': 'QuestID', 'quest_treasure_pickers': 'QuestID',
    'quest_visual_effect': 'ID', 'spawn_tracking': 'SpawnTrackingId',
    'spawn_tracking_quest_objective': 'SpawnTrackingId', 'spawn_tracking_template': 'SpawnTrackingId',
    'spawn_tracking_state': 'SpawnId', 'ui_map_quest': 'UiMapId', 'ui_map_quest_line': 'UiMapId',
    'skill_fishing_base_level': 'entry', 'world_safe_locs': 'ID', 'areatrigger_teleport': 'ID',
    'phase_area': 'AreaId', 'phase_name': 'ID', 'terrain_swap_defaults': 'MapId',
    'terrain_worldmap': 'TerrainSwapMap',
}


@lru_cache(maxsize=4)
def _digest(path, size, modified_ns):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class WorldSqliteReference:
    def __init__(self, db, lock, path, tables):
        self.db, self.lock, self.path, self.tables = db, lock, path, tables
        self._build_columns = {}
        stat = path.stat()
        digest = _digest(path, stat.st_size, stat.st_mtime_ns)
        versions = self.rows("SELECT * FROM version LIMIT 1") if "version" in tables else []
        self.sources = [{"kind": "WORLD", "filename": path.name, "sha256": digest,
                         "version": versions[0].get("db_version") if versions else None}]
        # Warm the unindexed name lookup at startup, never during a MOVE tick.
        self.names

    def rows(self, sql, args=()):
        with self.lock:
            cursor = self.db.execute(sql, args)
            keys = [c[0] for c in cursor.description]
            return [dict(zip(keys, row)) for row in cursor]

    def hint(self):
        return {"source": "TDB_REFERENCE", "source_file": self.path.name,
                "source_sha256": self.sources[0]["sha256"], "source_version": self.sources[0]["version"],
                "knowledge_priority": "PRIMARY_STATIC", "confirmed": False, "navigation_trusted": False}

    @cached_property
    def names(self):
        # No name index in many SQL conversions. Build one read-only in-memory
        # index on the first request, never scan 227k templates each agent tick.
        result = {}
        for row in self.rows("SELECT entry,name FROM creature_template ORDER BY entry"):
            result.setdefault(str(row["name"] or "").casefold(), []).append(row)
        return result

    def find_by_name(self, name, limit):
        return tuple({"identity_key": f"npc:{r['entry']}", "npc_id": r["entry"],
                      "name": r["name"], "unit_type": "NPC", "seen_count": 0, **self.hint()}
                     for r in self.names.get(name.strip().casefold(), ())[:limit])

    def _has_build_column(self, table):
        # The WORLD schema is immutable for this read-only connection. Avoid
        # repeating PRAGMA table_info in every bounded provider lookup.
        with self.lock:
            if table not in self._build_columns:
                self._build_columns[table] = any(row[1] == 'VerifiedBuild' for row in
                    self.db.execute(f'PRAGMA table_info("{table}")'))
            return self._build_columns[table]

    def records(self, kind, table, record_id):
        if kind != "WORLD" or table not in RECORD_KEYS or table not in self.tables:
            return ()
        order = ' ORDER BY ABS("VerifiedBuild") DESC' if self._has_build_column(table) else ''
        return tuple(self.rows(f'SELECT * FROM "{table}" WHERE "{RECORD_KEYS[table]}"=?{order} LIMIT 256', (record_id,)))

    def gameobject(self, entry):
        rows = self.records('WORLD', 'gameobject_template', entry)
        return ({'object_id': entry, 'name': rows[0]['name'], 'template': rows[0], **self.hint()}
                if rows else None)

    @lru_cache(maxsize=128)
    def object_spawns(self, world_map_id, entry):
        if 'gameobject' not in self.tables:
            return ()
        return tuple({**self.spawn(r), 'object_id': r['id'], 'npc_id': None} for r in self.rows(
            'SELECT * FROM gameobject WHERE map=? AND id=? ORDER BY guid', (world_map_id, entry)))

    def roles(self, *, npc_id=None, quest_id=None):
        result = []
        for table, role in (("creature_queststarter", "QUEST_STARTER"), ("creature_questender", "QUEST_ENDER")):
            if table not in self.tables:
                continue
            key, value = ("id", npc_id) if npc_id is not None else ("quest", quest_id)
            for row in self.rows(f'SELECT id,quest,VerifiedBuild FROM {table} WHERE {key}=?', (value,)):
                result.append({"npc_id": row["id"], "quest_id": row["quest"],
                               "role": role, "verified_build": row["VerifiedBuild"]})
        return sorted(result, key=lambda row: -build_number(row['verified_build']))

    def object_roles(self, quest_id):
        result = []
        for table, role in (('gameobject_queststarter', 'QUEST_STARTER'), ('gameobject_questender', 'QUEST_ENDER')):
            if table in self.tables:
                result.extend({'object_id': r['id'], 'quest_id': r['quest'], 'role': role,
                               'verified_build': r.get('VerifiedBuild')} for r in self.rows(
                    f'SELECT * FROM {table} WHERE quest=?', (quest_id,)))
        return sorted(result, key=lambda row: -build_number(row['verified_build']))

    def spawn(self, row):
        return {"spawn_id": row["guid"], "npc_id": row["id"], "world_map_id": row["map"],
                "x": row["position_x"], "y": row["position_y"], "z": row["position_z"],
                "verified_build": row.get("VerifiedBuild"),
                "context": {k: row.get(k) for k in ("PhaseId", "PhaseGroup", "phaseUseFlags", "spawnDifficulties", "terrainSwapMap")},
                "coordinate_space": "WORLD_YARDS", "belief": "CANDIDATE", **self.hint()}

    def spawn_candidates(self, world_map_id, npc_id):
        return tuple(self.spawn(r) for r in self.rows(
            "SELECT * FROM creature WHERE map=? AND id=? ORDER BY guid", (world_map_id,npc_id)))

    def role_candidates(self, world_map_id, role):
        table = {"QUEST_STARTER": "creature_queststarter", "QUEST_ENDER": "creature_questender"}.get(role)
        if table not in self.tables:
            return ()
        rows = self.rows(f"SELECT c.*,GROUP_CONCAT(q.quest) AS quest_ids,MAX(q.VerifiedBuild) AS role_build "
                         f"FROM creature c JOIN {table} q ON q.id=c.id WHERE c.map=? GROUP BY c.guid", (world_map_id,))
        return tuple({**self.spawn(r), "quest_ids": [int(q) for q in r["quest_ids"].split(",")],
                      "role_hypothesis": role, "verified_build": r["role_build"]} for r in rows)

    def npc(self, npc_id):
        rows = self.rows("SELECT * FROM creature_template WHERE entry=?", (npc_id,))
        if not rows:
            return None
        return {"npc_id": npc_id, "name": rows[0]["name"], "template": rows[0],
                "verified_build": rows[0].get('VerifiedBuild'),
                "models": list(self.records("WORLD", "creature_template_model", npc_id)),
                "quest_roles": self.roles(npc_id=npc_id), **self.hint()}

    def quest(self, quest_id):
        rows = self.rows("SELECT * FROM quest_template WHERE ID=?", (quest_id,))
        if not rows:
            return None
        q = rows[0]
        objectives = self.rows('SELECT * FROM quest_objectives WHERE QuestID=? ORDER BY "Order"', (quest_id,))
        pois, metadata, selected = [], [], []
        if {"quest_poi", "quest_poi_points"} <= self.tables:
            points = self.rows("SELECT * FROM quest_poi_points WHERE QuestID=? ORDER BY Idx1,Idx2", (quest_id,))
            metadata = self.rows("SELECT * FROM quest_poi WHERE QuestID=? ORDER BY Idx1", (quest_id,))
            # A legacy and a newer POI can have different BlobIndex/Idx1 for
            # the same objective and map. Prefer the newest revision for that
            # semantic target, retaining all same-build blobs in the region.
            # Distinct conditions/phase tracking remain separate candidates.
            selected = newest_rows(metadata, lambda p: (
                p['ObjectiveIndex'], p['QuestObjectiveID'], p.get('QuestObjectID'),
                p['MapID'], p['UiMapID'], p.get('PlayerConditionID'),
                p.get('NavigationPlayerConditionID'), p.get('SpawnTrackingID')))
            # Superseded metadata must not make the surviving point group look
            # semantically ambiguous merely because an older blob reused Idx1.
            shared = Counter(p['Idx1'] for p in selected)
            for poi in selected:
                group = [p for p in points if p['Idx1'] == poi['Idx1']]
                # The points table has no BlobIndex. Preserve shared geometry,
                # never collapse distinct metadata or invent a three-key JOIN.
                semantics = {(p['MapID'], p['UiMapID'], p['ObjectiveIndex'], p['QuestObjectiveID'])
                             for p in selected if p['Idx1'] == poi['Idx1']}
                pois.append({"poi_id": f"{quest_id}:{poi.get('BlobIndex', 0)}:{poi['Idx1']}",
                             "blob_index": poi.get('BlobIndex', 0), "point_group_id": f"{quest_id}:{poi['Idx1']}",
                             "shared_geometry_count": shared[poi['Idx1']],
                             "geometry_ambiguous": len(semantics) > 1,
                             "geometry_kind": 'POINT' if len(group)==1 else 'POLYGON_CANDIDATE' if len(group)>=3 else 'INCOMPLETE',
                             "point_builds": sorted({p.get('VerifiedBuild') for p in group}, key=build_number),
                             "geometry_mixed_build": len({build_number(p.get('VerifiedBuild')) for p in group}) > 1,
                             "verified_build": poi.get('VerifiedBuild'), "metadata": poi,
                             "objective_id": poi["QuestObjectiveID"],
                             "objective_index": poi["ObjectiveIndex"], "world_map_id": poi["MapID"],
                             "ui_map_id": poi["UiMapID"], "conditions": {k: poi.get(k) for k in
                             ("PlayerConditionID", "NavigationPlayerConditionID")},
                             "spawn_tracking_id": poi.get("SpawnTrackingID"),
                             "points": [{"x": p["X"], "y": p["Y"], "z": p["Z"],
                                         "point_index": p['Idx2'], "verified_build": p.get('VerifiedBuild')} for p in group],
                             "coordinate_space": "TDB_WORLD_REFERENCE", **self.hint()})
        return {"quest_id": quest_id, "title": q.get("LogTitle"), "description": q.get("QuestDescription"),
                "objectives_text": q.get("LogDescription"), "completion_text": q.get("QuestCompletionLog"),
                "allowable_races": q.get("AllowableRaces"), "verified_build": q.get('VerifiedBuild'), "template": q,
                "objectives": [{"objective_id": o["ID"], "order": o["Order"], "raw_type": o["Type"],
                    "credit_object_id": o["ObjectID"], "amount": o["Amount"], "description": o.get("Description"),
                    "storage_index": o.get('StorageIndex'), "parent_objective_id": o.get('ParentObjectiveID'),
                    "verified_build": o.get('VerifiedBuild'), "metadata": o} for o in objectives],
                "quest_roles": self.roles(quest_id=quest_id), "object_roles": self.object_roles(quest_id), "pois": pois,
                "poi_catalogue_count": len(metadata), "poi_superseded_count": len(metadata)-len(selected),
                "details": list(self.records("WORLD", "quest_template_addon", quest_id)), **self.hint()}
