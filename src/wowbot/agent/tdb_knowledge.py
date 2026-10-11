"""Primary static WORLD knowledge over the existing readonly catalog.

No new brain, action authority, database copy or write connection. Runtime
snapshots are bounded; larger service/condition data stays queryable on demand.
Live quest state and identity remain authoritative; credit IDs are not GUIDs.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import math


class TDBKnowledgeProvider:
    def __init__(self, catalog):
        self.catalog = catalog

    def lookup(self, table, record_id):
        """Allowlisted typed-key records; unknown/absent tables return empty."""
        return deepcopy(self.catalog.records('WORLD', table, record_id))

    @lru_cache(maxsize=128)
    def quest(self, quest_id):
        result = deepcopy(self.catalog.quest(quest_id))
        if not result:
            return None
        template = result.pop('template', {})
        result['verified_build'] = template.get('VerifiedBuild')
        details = (result.get('details') or [{}])[0]
        result['chain'] = {key: details.get(key) for key in
            ('PrevQuestID', 'NextQuestID', 'ExclusiveGroup', 'BreadcrumbForQuestId')}
        result['chain']['RewardNextQuest'] = template.get('RewardNextQuest')
        result['chain']['source_build'] = template.get('VerifiedBuild')
        result['eligibility'] = {'status': 'REQUIRES_LIVE_AVAILABILITY',
            'AllowableRaces': template.get('AllowableRaces', result.get('allowable_races')),
            **{key: details.get(key) for key in ('AllowableClasses', 'RequiredSkillID', 'RequiredSkillPoints',
                'RequiredMinRepFaction', 'RequiredMinRepValue', 'RequiredMaxRepFaction', 'RequiredMaxRepValue')}}
        result['items'] = {'start_item_id': template.get('StartItem'),
            'fixed_rewards': [{'item_id': template.get(f'RewardItem{i}'), 'count': template.get(f'RewardAmount{i}')}
                              for i in range(1,5) if template.get(f'RewardItem{i}')],
            'choice_rewards': [{'item_id': template.get(f'RewardChoiceItemID{i}'), 'count': template.get(f'RewardChoiceItemQuantity{i}')}
                               for i in range(1,7) if template.get(f'RewardChoiceItemID{i}')],
            'source_spell_id': details.get('SourceSpellID')}
        raw = self.catalog.raw
        result['faction_variants'] = (raw.rows('SELECT * FROM player_factionchange_quests WHERE alliance_id=? OR horde_id=?',
            (quest_id, quest_id)) if raw and 'player_factionchange_quests' in raw.tables else [])
        for objective in result.get('objectives', []):
            kind, entry = objective.get('raw_type'), objective.get('credit_object_id')
            objective['credit_kind'] = {0:'CREATURE_CREDIT', 1:'ITEM', 2:'GAMEOBJECT', 3:'TALK_CREDIT'}.get(kind, 'OTHER')
            # Only an explicit gameobject objective identifies a gameobject
            # template. Monster/talk IDs can be invisible proxy credit NPCs.
            if kind == 2 and raw:
                obj = raw.gameobject(entry)
                objective['object_template'] = ({'object_id':entry, 'name':obj['name'],
                    'type':obj['template'].get('type'), 'confirmed':False} if obj else None)
            if kind == 1:
                objective['item_sources'] = self.item_sources(entry)
            if kind == 0 and raw:
                # Live 2026-10-11 (56034): the credit entry 156722 is an
                # invisible proxy without spawns; the text names the real
                # creature ("... tested on Wandering Boars", 29 spawns).
                # Location knowledge only -- identity is still the tooltip.
                objective['named_creatures'] = self.named_creatures(
                    objective.get('description') or '', entry)
        return result

    @lru_cache(maxsize=256)
    def named_creatures(self, description, credit_entry=None):
        """Creature templates named in an objective text (longest names)."""
        raw = self.catalog.raw
        text = str(description or '').strip()
        if not raw or len(text) < 6 or 'creature_template' not in raw.tables:
            return []
        rows = raw.rows("SELECT entry, name FROM creature_template "
                        "WHERE length(name) >= 6 AND ? LIKE '%' || name || '%' LIMIT 64", (text,))
        names = {str(r['name']) for r in rows}
        longest = {name for name in names
                   if not any(name != other and name.casefold() in other.casefold() for other in names)}
        return [{'entry': r['entry'], 'name': r['name']} for r in rows
                if r['name'] in longest and r['entry'] != credit_entry][:6]

    @lru_cache(maxsize=128)
    def item_sources(self, item_id):
        raw = self.catalog.raw
        if not raw:
            return []
        result = []
        for table, field, kind in (('creature_questitem','CreatureEntry','CREATURE'),
                                   ('gameobject_questitem','GameObjectEntry','GAMEOBJECT')):
            if table in raw.tables:
                order = ' ORDER BY ABS(VerifiedBuild) DESC' if raw._has_build_column(table) else ''
                result.extend({'kind':kind, 'entry':r[field], 'item_id':item_id,
                    'metadata':r, 'relation':'QUEST_ITEM_ASSOCIATION', 'confirmed':False}
                    for r in raw.rows(f'SELECT * FROM {table} WHERE ItemId=?{order} LIMIT 64', (item_id,)))
        # These are acquisition candidates, not guaranteed drops or purchase permission.
        if 'npc_vendor' in raw.tables:
            order = ' ORDER BY ABS(VerifiedBuild) DESC' if raw._has_build_column('npc_vendor') else ''
            result.extend({'kind':'VENDOR', 'entry':r['entry'], 'item_id':item_id,
                'metadata':r, 'relation':'VENDOR_STOCK', 'confirmed':False}
                for r in raw.rows(f'SELECT * FROM npc_vendor WHERE item=? AND type=1{order} LIMIT 64', (item_id,)))
        return result

    @lru_cache(maxsize=64)
    def services(self, npc_id):
        menus = self.lookup('creature_template_gossip', npc_id)
        trainers = self.lookup('creature_trainer', npc_id)
        return {'npc_id': npc_id, 'source':'TDB_REFERENCE', 'confirmed':False,
            'gossip': [{'menu_id':m['MenuID'], 'options':self.lookup('gossip_menu_option', m['MenuID'])} for m in menus],
            'spellclick':self.lookup('npc_spellclick_spells', npc_id),
            'vendor':self.lookup('npc_vendor', npc_id),
            'trainers':[{'relation':t, 'trainer':self.lookup('trainer', t['TrainerID']),
                         'spells':self.lookup('trainer_spell', t['TrainerID'])} for t in trainers],
            'combat_context': {'spells':self.lookup('creature_template_spell', npc_id),
                               'resistances':self.lookup('creature_template_resistance', npc_id)}}

    def quest_locations(self, reference, state, learned=None):
        """Map-scoped spawns for explicit roles / object objectives / item sources.

        An unobserved phase/difficulty is kept in context and filtered at use.
        We never translate a monster credit into a creature to attack.
        """
        position = state.get('player_world_position') or {}
        world_map = position.get('instance_id')
        if world_map is None:
            return []
        wanted = []
        for r in reference.get('quest_roles', ()):
            wanted.append(('CREATURE', r['npc_id'], r['role'], None))
        for r in reference.get('object_roles', ()):
            wanted.append(('GAMEOBJECT', r['object_id'], r['role'], None))
        names = {}
        for o in reference.get('objectives', ()):
            if o.get('raw_type') == 2:
                wanted.append(('GAMEOBJECT', o['credit_object_id'], 'OBJECTIVE', o['objective_id']))
                names[('GAMEOBJECT', o['credit_object_id'])] = (o.get('object_template') or {}).get('name')
            for named in o.get('named_creatures') or ():
                wanted.append(('CREATURE', named['entry'], 'OBJECTIVE', o['objective_id']))
                names[('CREATURE', named['entry'])] = named.get('name')
            for source in o.get('item_sources') or ():
                wanted.append(('GAMEOBJECT' if source['kind']=='GAMEOBJECT' else 'CREATURE',
                               source['entry'], 'ITEM_SOURCE', o['objective_id']))
        candidates = []
        for kind, entry, role, oid in dict.fromkeys(wanted):
            spawns = (self.catalog.spawn_candidates(world_map, entry) if kind=='CREATURE' else
                      self.catalog.raw.object_spawns(world_map, entry) if self.catalog.raw else ())
            if learned is not None:
                # Live-verified places confirm TDB rows or fill their gaps
                # (script-summoned NPCs have no `creature` row at all).
                from .learned_world import merge_spawns
                spawns = merge_spawns(spawns, learned.spawns(world_map, kind, entry, names.get((kind, entry))))
            for spawn in spawns:
                candidates.append({**spawn, 'entity_kind':kind, 'entry':entry,
                                   'role':role, 'objective_id':oid})
        def distance(row):
            return math.hypot(float(row['x'])-float(position.get('x') or 0), float(row['y'])-float(position.get('y') or 0))
        return sorted(candidates, key=distance)[:32]
