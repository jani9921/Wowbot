"""Read-only census of EVERY SQLite table; generated reports are not live validation."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3


# Dispositions describe this implementation, not aspirational feature coverage.
PRIMARY = set('''quest_template quest_template_addon quest_objectives quest_poi quest_poi_points
creature creature_template creature_queststarter creature_questender creature_template_model
gameobject gameobject_template gameobject_queststarter gameobject_questender
creature_questitem gameobject_questitem player_factionchange_quests'''.split())
LOOKUP = set('''creature_template_gossip gossip_menu gossip_menu_option npc_spellclick_spells
npc_vendor creature_trainer trainer trainer_spell creature_template_difficulty
quest_request_items quest_offer_reward quest_details quest_objectives_completion_effect
quest_completion_log_conditional quest_description_conditional quest_request_items_conditional
quest_offer_reward_conditional quest_reward_display_spell quest_treasure_pickers quest_visual_effect
spawn_tracking spawn_tracking_quest_objective spawn_tracking_template spawn_tracking_state
creature_template_spell creature_template_resistance creature_immunities
ui_map_quest ui_map_quest_line skill_fishing_base_level
world_safe_locs areatrigger_teleport phase_area phase_name terrain_swap_defaults terrain_worldmap'''.split())


def disposition(name):
    if name in PRIMARY:
        return 'RUNTIME_KNOWLEDGE', 'Quest/entity/geometry knowledge; current identity, availability and route still verified live.'
    if name in LOOKUP:
        return 'QUERYABLE_CONTEXT', 'Typed provider lookup; not an implemented autonomous service/profession capability.'
    if name in {'version', '_tdb_import_metadata', 'updates', 'updates_include'}:
        return 'PROVENANCE', 'Import/build history, not current-game validity.'
    if name.endswith('_locale'):
        return 'DEFERRED_LOCALE', 'Useful translated text; locale selection not yet integrated.'
    if name.endswith('loot_template'):
        return 'DEFERRED_LOOT_RULES', 'Server loot/reference/group/difficulty semantics; do not invent drop probabilities or owners.'
    if name in {'conditions', 'disables', 'access_requirement', 'race_unlock_requirement', 'class_expansion_requirement'}:
        return 'DEFERRED_CONDITIONS', 'Conditional/server rules need an explicit evaluator and observable inputs; unknown is not satisfied.'
    if name.startswith(('phase_', 'terrain_', 'spawn_', 'pool_', 'quest_pool_', 'game_event', 'instance_')):
        return 'DEFERRED_WORLD_CONTEXT', 'Phases/events/pools/difficulty constrain spawns; no inferred current visibility.'
    if name.startswith(('waypoint_', 'script_spline_', 'creature_movement', 'creature_formations', 'transports', 'vehicle_', 'jump_charge')):
        return 'NOT_PLAYER_ROUTES', 'NPC/vehicle motion is not a verified player navmesh route.'
    if 'script' in name or name.startswith(('serverside_', 'smart_', 'command', 'trinity_string')):
        return 'SERVER_ONLY', 'Server scripts/commands are never executed by the client agent.'
    if name.startswith(('spell_', 'skill_', 'item_', 'mount_', 'creature_', 'gameobject_', 'quest_', 'npc_', 'gossip_')):
        return 'DEFERRED_DOMAIN_CONTEXT', 'Potential context; typed semantics/consumer not implemented, not runtime authority.'
    if name.startswith(('areatrigger', 'graveyard', 'points_of_interest', 'scenario', 'scene_', 'conversation', 'page_text', 'world_')):
        return 'DEFERRED_SPATIAL_DIALOG', 'May guide search/dialog after map/condition/identity resolution; not a direct action.'
    return 'OUTSIDE_CURRENT_AGENT', 'Server balance, rewards, character creation, PvP, pets or other unimplemented domains.'


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def audit(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    result = {'file': path.name, 'sha256': digest, 'bytes': path.stat().st_size,
              'integrity': db.execute('PRAGMA quick_check').fetchone()[0], 'tables': []}
    try:
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            columns = [dict(zip(('cid','name','type','not_null','default','primary_key'), row))
                       for row in db.execute(f'PRAGMA table_info({quote(name)})')]
            count = db.execute(f'SELECT COUNT(*) FROM {quote(name)}').fetchone()[0]
            indexes = []
            for row in db.execute(f'PRAGMA index_list({quote(name)})').fetchall():
                indexes.append({'name': row[1], 'unique': bool(row[2]),
                    'columns': [i[2] for i in db.execute(f'PRAGMA index_info({quote(row[1])})')]})
            kind, reason = disposition(name)
            record = {'name': name, 'rows': count, 'columns': columns, 'indexes': indexes,
                      'foreign_keys': db.execute(f'PRAGMA foreign_key_list({quote(name)})').fetchall(),
                      'disposition': kind, 'reason': reason}
            if any(c['name'] == 'VerifiedBuild' for c in columns):
                record['builds'] = db.execute(f'SELECT VerifiedBuild,COUNT(*) FROM {quote(name)} GROUP BY VerifiedBuild ORDER BY VerifiedBuild').fetchall()
            # Inspect representative contents without putting megabytes of quest prose in the report.
            record['sample'] = [dict(zip((c['name'] for c in columns),
                               (v[:160]+'…' if isinstance(v,str) and len(v)>160 else v for v in row)))
                               for row in db.execute(f'SELECT * FROM {quote(name)} LIMIT 2')]
            result['tables'].append(record)
        result['summary'] = dict(Counter(t['disposition'] for t in result['tables']))
        result['empty_tables'] = sum(t['rows']==0 for t in result['tables'])
        result['total_rows'] = sum(t['rows'] for t in result['tables'])
        result['poi_shared_groups'] = db.execute('''SELECT QuestID,Idx1,COUNT(*),COUNT(DISTINCT BlobIndex)
            FROM quest_poi GROUP BY QuestID,Idx1 HAVING COUNT(*)>1 ORDER BY QuestID,Idx1''').fetchall()
        result['poi_orphan_points'] = db.execute('''SELECT COUNT(*) FROM quest_poi_points p WHERE NOT EXISTS
            (SELECT 1 FROM quest_poi q WHERE q.QuestID=p.QuestID AND q.Idx1=p.Idx1)''').fetchone()[0]
        result['poi_missing_geometry'] = db.execute('''SELECT COUNT(*) FROM quest_poi q WHERE NOT EXISTS
            (SELECT 1 FROM quest_poi_points p WHERE q.QuestID=p.QuestID AND q.Idx1=p.Idx1)''').fetchone()[0]
        return result
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = audit(args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = ['# TDB table audit — 2026-10-08', '',
             'Generated read-only schema/count/build/sample census. This is not a row-by-row proof of Retail accuracy.', '',
             f"Source: `{data['file']}`; SHA256 `{data['sha256']}`.", '',
             f"{len(data['tables'])} tables; {data['total_rows']:,} rows; {data['empty_tables']} empty; integrity: {data['integrity']}.", '',
             'RUNTIME_KNOWLEDGE means exposed to the shared WorldModel/provider, not every field drives an action. QUERYABLE_CONTEXT means on-demand only.', '',
             '| Table | Rows | Disposition | Rationale |', '|---|---:|---|---|']
    for t in data['tables']:
        lines.append(f"| `{t['name']}` | {t['rows']} | {t['disposition']} | {t['reason']} |")
    lines += ['', f"Shared POI point groups: {len(data['poi_shared_groups'])}; orphan points: {data['poi_orphan_points']}; metadata without points: {data['poi_missing_geometry']}.", '',
              'Full columns, indexes, build distributions and bounded sample rows are in the adjacent JSON report.']
    args.output.with_suffix('.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in data.items() if k not in {'tables','poi_shared_groups'}}, indent=2))


if __name__ == '__main__':
    main()
