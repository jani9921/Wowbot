"""Build-time structural quest -> spell/SmartAI -> scene -> path resolution.

Only explicit data edges are followed. Server scripts and imported Lua are
never executed. A reference association is not current scene/input authority.
The existing TDB stays open read-only; only derived links enter the DB2 DB.
"""
from __future__ import annotations

from collections import defaultdict, deque
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import sqlite3

MAX_SPELL_DEPTH = 12
MAX_NODES = 4096
CAST_ACTIONS = frozenset({11, 85, 86, 134})
PHASES = {47: "ON_ACCEPT", 48: "ON_OBJECTIVE_COMPLETE", 49: "ON_COMPLETE", 50: "ON_REWARD", 51: "ON_FAIL"}


def _literal_path_table(text, name):
    """Read numeric [PlayerCondition] = {pathID=N} entries, never Lua code."""
    match = re.search(r'\b'+re.escape(name)+r'\s*=\s*\{',text)
    if not match:
        return {}
    start, depth, quote, index = match.end(), 1, None, match.end()
    while index < len(text) and depth:
        char=text[index]
        if quote:
            if char=='\\':
                index+=2
                continue
            if char==quote:
                quote=None
        elif char in {'"',"'"}:
            quote=char
        elif char=='{':
            depth+=1
        elif char=='}':
            depth-=1
        index+=1
    if depth:
        return {}  # A truncated table cannot establish its entries.
    result=defaultdict(set)
    for condition,path in re.findall(r'\[\s*(\d+)\s*\]\s*=\s*\{\s*pathID\s*=\s*(\d+)\s*,?\s*\}',text[start:index-1]):
        if int(condition)>0 and int(path)>0:
            result[int(condition)].add(int(path))
    return result


def _client_condition_references(db, store):
    texts={sid:re.sub(r'--[^\r\n]*','',re.sub(r'--\[\[.*?\]\]','',json.loads(raw).get('Script',''),flags=re.S))
           for sid,raw in db.execute("SELECT id,record_json FROM db2_rows WHERE table_name='SceneScriptText'")}
    selectors=defaultdict(lambda:defaultdict(set))
    loop=r'\bfor\s+([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s+in\s+pairs\s*\(\s*([A-Za-z_]\w*)\s*\)\s*do'
    for sid,text in texts.items():
        for match in re.finditer(loop,text):
            key,value,table=match.groups()
            rest=text[match.end():]
            if (re.search(r'EvalPlayerCondition\s*\(\s*'+re.escape(key)+r'\s*\)',rest)
                    and re.search(r'\bpathID\s*=\s*'+re.escape(value)+r'\s*\.\s*pathID\b',rest)):
                for (owner,) in db.execute('SELECT package_id FROM scene_scripts WHERE script_id=?',(sid,)):
                    selectors[owner][table].add(sid)
    for sid,text in texts.items():
        direct={int(n) for n in re.findall(r'\bEvalPlayerCondition\s*\(\s*(\d+)\b',text)}
        literals={int(n) for n in re.findall(r'(?:\bpathID\s*=\s*|\bLoadPath\s*\(\s*)(\d+)\b',text) if int(n)>0}
        if not direct and not literals:
            continue
        owners=[r[0] for r in db.execute('SELECT package_id FROM scene_scripts WHERE script_id=?',(sid,))]
        tables={name:_literal_path_table(text,name) for name in {name for owner in owners for name in selectors[owner]}}
        condition_ids=direct | {cid for bindings in tables.values() for cid in bindings}
        for owner in owners:
            db.executemany('INSERT OR IGNORE INTO scene_path_candidates VALUES (?,?,?,?,?)',(
                (owner,path,sid,0,'UNSCOPED_LITERAL') for path in literals))
            for name,bindings in tables.items():
                if name not in selectors[owner]:
                    continue
                for cid,paths in bindings.items():
                    db.executemany('INSERT OR IGNORE INTO scene_path_candidates VALUES (?,?,?,?,?)',(
                        (owner,path,sid,cid,'PLAYER_CONDITION_TABLE') for path in paths))
        for cid,path in re.findall(r'\b(?:if|elseif)\s*\(?\s*scene:EvalPlayerCondition\s*\(\s*(\d+)\s*\)\s*\)?\s*then\s*pathID\s*=\s*(\d+)\b',text):
            for owner in owners:
                db.execute('INSERT OR IGNORE INTO scene_path_candidates VALUES (?,?,?,?,?)',(
                    owner,int(path),sid,int(cid),'CONDITIONAL_LITERAL'))
        for cid in condition_ids:
            row=db.execute("SELECT record_json FROM db2_rows WHERE table_name='PlayerCondition' AND id=?",(cid,)).fetchone()
            if not row:
                continue
            condition=json.loads(row[0])
            for field,phase in (('CurrQuestID','CONDITIONAL'),('CurrentCompletedQuestID','ON_COMPLETE'),
                                ('PrevQuestID','AFTER_QUEST'),('QuestKillID','OBJECTIVE_REFERENCE')):
                values=condition.get(field,[])
                values=values if isinstance(values,list) else [values]
                for quest in {q for q in values if type(q) is int and q>0}:
                    count=0
                    for owner in owners:
                        binding_paths=set()
                        proof=[]
                        for name,bindings in tables.items():
                            if cid in bindings and name in selectors[owner]:
                                binding_paths.update(bindings[cid])
                                proof.append({'table_name':name,'data_script_id':sid,'selector_script_ids':sorted(selectors[owner][name])})
                        if cid not in direct and not binding_paths:
                            continue
                        candidate={'package_id':owner,'scene_id':None,'status':'RESOLVED',
                                   'condition_id':cid,'script_id':sid}
                        if binding_paths:
                            candidate.update(path_ids=sorted(binding_paths),path_table_proof=proof)
                        store(quest,phase,candidate,{'table':'PlayerCondition','id':cid,'field':field,
                            'record':condition,'reference':'SceneScriptText.EvalPlayerCondition'},True)
                        count+=1
                    if count:
                        db.execute('INSERT INTO quest_scene_seeds VALUES (?,1) ON CONFLICT(quest_id) DO UPDATE SET seed_count=seed_count+1',(quest,))


def _rows(db, table):
    # Identifiers are a code-owned allowlist, never imported SQL.
    assert table in {"scene_template", "smart_scripts", "quest_template_addon", "spell_area",
                     "conditions", "quest_template", "quest_objectives", "quest_poi", "spell_linked_spell"}
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return []
    return [dict(row) for row in db.execute('SELECT * FROM "'+table+'"')]


def _schema(db):
    db.executescript("""
    CREATE TABLE spell_scene_edges(effect_id INTEGER PRIMARY KEY,spell_id INTEGER,scene_id INTEGER,
        package_id INTEGER,kind TEXT,status TEXT,details_json TEXT);
    CREATE INDEX ix_spell_scene_spell ON spell_scene_edges(spell_id);
    CREATE TABLE quest_scene_candidates(id INTEGER PRIMARY KEY,quest_id INTEGER,package_id INTEGER,
        scene_id INTEGER,phase TEXT,conditional INTEGER,status TEXT,evidence_json TEXT);
    CREATE INDEX ix_quest_scene_quest ON quest_scene_candidates(quest_id);
    CREATE TABLE quest_scene_resolution(quest_id INTEGER PRIMARY KEY,status TEXT,reason TEXT,
        packages_json TEXT,path_ids_json TEXT,route_status TEXT);
    CREATE TABLE quest_scene_seeds(quest_id INTEGER PRIMARY KEY,seed_count INTEGER);
    CREATE TABLE scene_path_candidates(package_id INTEGER,path_id INTEGER,script_id INTEGER,
        condition_id INTEGER,kind TEXT,PRIMARY KEY(package_id,path_id,script_id,condition_id));
    CREATE INDEX ix_scene_path_candidates_package ON scene_path_candidates(package_id);
    CREATE INDEX IF NOT EXISTS ix_scene_scripts_script ON scene_scripts(script_id);
    """)


def index_relations(db, world_path):
    """Populate automatic associations before reviewed exceptions are applied."""
    _schema(db)
    world = sqlite3.connect(Path(world_path).resolve().as_uri()+"?mode=ro", uri=True)
    world.row_factory = sqlite3.Row
    world.execute("PRAGMA query_only=ON")
    try:
        templates = {row["SceneId"]: row for row in _rows(world, "scene_template")}
        packages = {row[0] for row in db.execute("SELECT id FROM db2_rows WHERE table_name='SceneScriptPackage'")}
        scenes_by_spell = defaultdict(list)
        effects = db.execute("""SELECT id,spell_id,effect,aura,misc1,difficulty_id FROM spell_effects
            WHERE effect IN (195,198) OR aura=430""")
        for effect_id, spell, effect, aura, misc, difficulty in effects:
            scene = None if effect == 195 else misc
            template = templates.get(scene) if scene is not None else None
            package = misc if effect == 195 else (template or {}).get("ScriptPackageID")
            status = "RESOLVED" if package in packages else "MISSING_SCENE_TEMPLATE" if package is None else "MISSING_CLIENT_PACKAGE"
            kind = "PLAY_SCENE_PACKAGE" if effect == 195 else "PLAY_SCENE" if effect == 198 else "AURA_PLAY_SCENE"
            detail = {"effect_id": effect_id, "spell_id": spell, "effect": effect, "aura": aura,
                      "misc_value": misc, "difficulty_id": difficulty, "kind": kind,
                      "scene_template_id": scene, "source": "LOCAL_DB2_AND_EXISTING_TDB"}
            db.execute("INSERT INTO spell_scene_edges VALUES (?,?,?,?,?,?,?)", (
                effect_id, spell, scene, package, kind, status, json.dumps(detail)))
            scenes_by_spell[spell].append({"package_id": package, "scene_id": scene,
                "status": status, "edge": detail, "conditional": difficulty != 0})
        triggers = defaultdict(list)
        for effect_id, spell, target, difficulty in db.execute(
                "SELECT id,spell_id,trigger_spell,difficulty_id FROM spell_effects WHERE trigger_spell>0"):
            triggers[spell].append((target, {"table": "SpellEffect", "effect_id": effect_id,
                "spell_id": spell, "trigger_spell": target, "difficulty_id": difficulty}))
        for row in _rows(world, "spell_linked_spell"):
            if row.get("spell_trigger", 0) > 0 and row.get("spell_effect", 0) > 0:
                triggers[row["spell_trigger"]].append((row["spell_effect"], {"table": "spell_linked_spell", **row}))

        @lru_cache(maxsize=4096)
        def spell_scenes(spell):
            queue, seen, result = deque([(spell, [], False)]), set(), []
            truncated = False
            while queue:
                current, chain, conditional = queue.popleft()
                if current in seen:
                    continue
                if len(seen) >= MAX_NODES:
                    truncated = True
                    break
                seen.add(current)
                for scene in scenes_by_spell.get(current, ()):
                    result.append({**scene, "spell_chain": chain,
                                   "conditional": conditional or scene["conditional"]})
                edges = triggers.get(current, ())
                if len(chain) >= MAX_SPELL_DEPTH:
                    truncated |= bool(edges)
                    continue
                for target, edge in edges:
                    queue.append((target, [*chain, edge], True))
            return result, truncated

        smart = _rows(world, "smart_scripts")
        smart_by_key = {(r["source_type"], r["entryorguid"], r["id"]): r for r in smart}
        action_lists = defaultdict(list)
        for row in smart:
            if row["source_type"] == 9:
                action_lists[row["entryorguid"]].append(row)
        seeds = []
        for row in _rows(world, "quest_template_addon"):
            if row.get("SourceSpellID", 0) > 0:
                seeds.append((row["ID"], "ON_ACCEPT", "spell", row["SourceSpellID"],
                              {"table": "quest_template_addon", "id": row["ID"], "field": "SourceSpellID"}, False))
        for row in _rows(world, "spell_area"):
            if row.get("quest_start", 0) > 0:
                seeds.append((row["quest_start"], "WHILE_ACTIVE", "spell", row["spell"],
                              {"table": "spell_area", "record": row}, True))
        for row in smart:
            quest, phase = 0, "UNKNOWN"
            if row["event_type"] in {19, 20}:
                quest, phase = row["event_param1"], "ON_ACCEPT" if row["event_type"] == 19 else "ON_REWARD"
            elif row["source_type"] == 5 and row["event_type"] in PHASES:
                quest, phase = row["entryorguid"], PHASES[row["event_type"]]
            if quest > 0:
                seeds.append((quest, phase, "smart", row,
                    {"table": "smart_scripts", "source_type": row["source_type"],
                     "entryorguid": row["entryorguid"], "id": row["id"]}, False))
        world_conditions = _rows(world, "conditions")
        guarded_smart_sources = {(row.get("SourceId",0), row.get("SourceEntry",0))
            for row in world_conditions if row.get("SourceTypeOrReferenceId") == 22}
        for row in world_conditions:
            if row.get("NegativeCondition") or row.get("ConditionTypeOrReference") not in {9, 28}:
                continue
            quest = row.get("ConditionValue1", 0)
            if quest <= 0:
                continue
            source = row.get("SourceTypeOrReferenceId")
            if source == 17 and row.get("SourceEntry", 0) > 0:
                seeds.append((quest, "CONDITIONAL", "spell", row["SourceEntry"],
                              {"table": "conditions", "record": row}, True))

        seen_candidates = set()
        seed_counts = defaultdict(int)
        for quest, *_ in seeds:
            seed_counts[quest] += 1
        db.executemany("INSERT INTO quest_scene_seeds VALUES (?,?)", seed_counts.items())
        def store(quest, phase, candidate, evidence, conditional):
            witness = {"root": evidence, **{k:v for k,v in candidate.items() if k not in {"conditional"}}}
            encoded = json.dumps(witness, sort_keys=True)
            key = (quest, phase, encoded)
            if key in seen_candidates:
                return
            seen_candidates.add(key)
            db.execute("INSERT INTO quest_scene_candidates(quest_id,package_id,scene_id,phase,conditional,status,evidence_json) VALUES (?,?,?,?,?,?,?)", (
                quest, candidate["package_id"], candidate["scene_id"], phase,
                int(conditional or candidate.get("conditional", False)), candidate["status"], encoded))

        _client_condition_references(db,store)

        for quest, phase, kind, value, evidence, conditional in seeds:
            if kind == "spell":
                candidates, truncated = spell_scenes(value)
                for candidate in candidates:
                    store(quest, phase, candidate, evidence, conditional or truncated)
                continue
            queue, seen = deque([(value, [], conditional)]), set()
            while queue and len(seen) < MAX_NODES:
                row, chain, branch = queue.popleft()
                key = (row["source_type"], row["entryorguid"], row["id"])
                if key in seen:
                    continue
                seen.add(key)
                branch |= bool(row.get("event_phase_mask") or row.get("event_chance",100) != 100
                               or row.get("Difficulties") or row.get("event_flags")
                               or key[:2] in guarded_smart_sources)
                trace = [*chain, {"source_type":key[0], "entryorguid":key[1], "id":key[2],
                                 "action_type":row["action_type"], "action_param1":row["action_param1"],
                                 "target_type":row.get("target_type")}]
                if row.get("link"):
                    linked = smart_by_key.get((key[0], key[1], row["link"]))
                    if linked is not None:
                        queue.append((linked, trace, branch))
                action, argument = row["action_type"], row["action_param1"]
                if action == 80 and argument > 0:
                    for child in action_lists.get(argument, ()):
                        queue.append((child, trace, True))
                elif action in CAST_ACTIONS and argument > 0:
                    candidates, truncated = spell_scenes(argument)
                    for candidate in candidates:
                        player_cast = action in {85,134} and row.get("target_type") == 7
                        player_aura = candidate.get("edge",{}).get("kind") == "AURA_PLAY_SCENE" and row.get("target_type") == 7
                        store(quest, phase, {**candidate, "smart_chain":trace}, evidence,
                              branch or truncated or not (player_cast or player_aura))
                elif action == 129 and argument > 0:
                    template = templates.get(argument)
                    package = (template or {}).get("ScriptPackageID")
                    store(quest, phase, {"package_id":package, "scene_id":argument,
                        "status":"RESOLVED" if package in packages else "MISSING_SCENE_TEMPLATE" if package is None else "MISSING_CLIENT_PACKAGE",
                        "smart_chain":trace}, evidence, branch or row.get("target_type") != 7)

        quests = {r["ID"]:r for r in _rows(world, "quest_template")}
        objectives = defaultdict(list)
        for row in _rows(world, "quest_objectives"):
            objectives[row["QuestID"]].append(row)
        poi_maps = defaultdict(set)
        for row in _rows(world, "quest_poi"):
            if type(row.get("MapID")) is int and row["MapID"] >= 0:
                poi_maps[row["QuestID"]].add(row["MapID"])
        for quest, world_map in db.execute("SELECT quest_id,map_id FROM poi_blobs"):
            poi_maps[quest].add(world_map)
        for (quest,) in db.execute("SELECT DISTINCT quest_id FROM quest_scene_candidates").fetchall():
            rows = db.execute("SELECT package_id,status,phase,conditional,evidence_json FROM quest_scene_candidates WHERE quest_id=?", (quest,)).fetchall()
            resolved = sorted({r[0] for r in rows if r[1] == "RESOLVED"})
            path_ids=set()
            for row in rows:
                if row[1]!='RESOLVED':
                    continue
                evidence=json.loads(row[4])
                scoped=evidence.get('path_ids') or [r[0] for r in db.execute(
                    'SELECT path_id FROM scene_path_candidates WHERE package_id=? AND condition_id=?',(row[0],evidence.get('condition_id',-1)))]
                path_ids.update(scoped or [r[0] for r in db.execute('''SELECT path_id FROM scene_paths WHERE package_id=?
                    UNION SELECT path_id FROM scene_path_candidates WHERE package_id=?''',(row[0],row[0]))])
            paths=sorted(path_ids)
            incomplete = any(r[1] != "RESOLVED" for r in rows)
            status = "PARTIAL" if incomplete and resolved else "UNRESOLVED" if not resolved else "AMBIGUOUS" if len(resolved)>1 else "RESOLVED_REFERENCE"
            reason = ",".join(sorted({r[1] for r in rows})) if not resolved else "MULTIPLE_SCENE_PACKAGES" if len(resolved)>1 else "EXPLICIT_TDB_DB2_CHAIN"
            route_status = "NO_SUPPORTED_RING_MECHANIC"
            if len(resolved) == 1 and not incomplete:
                eligible = any(r[0] == resolved[0] and r[2] in {"ON_ACCEPT", "WHILE_ACTIVE"} and not r[3] for r in rows)
                if eligible:
                    course, route_status = ring_course(db, quest, resolved[0], quests.get(quest), objectives[quest], poi_maps[quest])
                    if course:
                        course["association_kind"] = "TDB_DB2_STRUCTURAL_REFERENCE"
                        course["association_evidence"] = "quest_scene_candidates: explicit source chain; no quest-ID rule"
                        db.execute("INSERT INTO quest_routes VALUES (?,?,?)", (quest,"REFERENCE_READY",json.dumps(course)))
                else:
                    route_status = "REQUIRES_LIVE_SCENE_OR_CONDITION_RESOLUTION"
            db.execute("INSERT INTO quest_scene_resolution VALUES (?,?,?,?,?,?)", (
                quest,status,reason,json.dumps(resolved),json.dumps(paths),route_status))
        return {"candidates":len(seen_candidates), "seed_count":db.execute("SELECT COALESCE(SUM(seed_count),0) FROM quest_scene_seeds").fetchone()[0]}
    finally:
        world.close()


def ring_course(db, quest_id, package, quest, objectives, maps):
    """Recognize the supported Checkpoint/RaceComplete mechanic by data shape."""
    paths = [r[0] for r in db.execute("SELECT DISTINCT path_id FROM scene_paths WHERE package_id=?",(package,))]
    if len(paths) != 1:
        return None, "NO_UNIQUE_PATH"
    scripts = [json.loads(r[0]).get("Script", "") for r in db.execute("""SELECT r.record_json FROM scene_scripts s
        JOIN db2_rows r ON r.table_name='SceneScriptText' AND r.id=s.script_id WHERE s.package_id=?""",(package,))]
    text = "\n".join(re.sub(r"--[^\r\n]*", "", s) for s in scripts)
    required = (r'\bRingHitDistance\s*=\s*\d+', r'\bcurrentCheckpoint\s*=\s*1\b',
                r'TriggerServerEvent\s*\(\s*[\"\']Checkpoint[\"\']',
                r'TriggerServerEvent\s*\(\s*[\"\']RaceComplete[\"\']', r'\blaps\s*=\s*1\b',
                r'SetRelativeCoords\s*\(\s*false', r'LoadPath\s*\(\s*pathID\s*\)', r'\bmaxCheckpoints\s*=\s*#rings')
    if not all(re.search(pattern,text) for pattern in required) or re.search(r'SetRelativeCoords\s*\(\s*true',text):
        return None, "UNSUPPORTED_SCENE_MECHANIC"
    if {int(n) for n in re.findall(r'\blaps\s*=\s*(\d+)\b',text)} != {1}:
        return None, "AMBIGUOUS_LAP_CONFIGURATION"
    points = db.execute("""SELECT n.sequence,n.id,n.location_id,l.x,l.y,l.z,l.rot_json FROM path_nodes n
        LEFT JOIN locations l ON l.id=n.location_id WHERE path_id=? ORDER BY n.sequence,n.id""",(paths[0],)).fetchall()
    if (not 2 <= len(points) <= 129 or len({p[0] for p in points}) != len(points)
            or not all(type(v) in {int,float} and math.isfinite(v) for p in points for v in p[3:6])):
        return None, "INCOMPLETE_PATH_GEOMETRY"
    checkpoints = [r for r in objectives if r.get("Amount") == len(points)-1 and r.get("ObjectID",0)>0
                   and re.search(r'\brings?\b',str(r.get("Description","")),re.I)]
    arrivals = [r for r in objectives if r.get("Amount") == 1 and r.get("ObjectID",0)>0
                and re.search(r'\btarget\s+area\b',str(r.get("Description","")),re.I)]
    if len(checkpoints)!=1 or len(arrivals)!=1 or checkpoints[0]["ID"]==arrivals[0]["ID"]:
        return None, "NO_UNIQUE_LIVE_VERIFIABLE_OBJECTIVES"
    if len(maps) != 1 or not quest:
        return None, "NO_UNIQUE_WORLD_MAP"
    return {"quest_id":quest_id, "title":quest.get("LogTitle"),"scene_package":package,"path_id":paths[0],
        "map_id":next(iter(maps)),"checkpoint_objective":checkpoints[0],"arrival_objective":arrivals[0],
        "ring_objective_entry":checkpoints[0]["ObjectID"],"target_objective_entry":arrivals[0]["ObjectID"],
        "rings":[[*p[3:6],*json.loads(p[6])[2:3]] for p in points[:-1]],
        "target":[*points[-1][3:6],*json.loads(points[-1][6])[2:3]],
        "source_node_ids":[p[1] for p in points],"source_location_ids":[p[2] for p in points],
        "coordinate_source":"LOCAL_DB2_SCENE_PATH_LOCATION","live_validation":"NOT_VALIDATED"}, "REFERENCE_READY"
