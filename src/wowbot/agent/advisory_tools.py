"""Read-only, bounded snapshots for a slow text advisor, never live mutators."""
from .models import json_copy


class AdvisoryReadTools:
    def __init__(self, world, now):
        self.data = {}
        state = world.state
        for quest in (state.get('active_quests') or ())[:16]:
            if not isinstance(quest, dict) or quest.get('quest_id') is None:
                continue
            qid = str(quest['quest_id'])
            self.data[('quest', qid)] = {k: json_copy(quest[k]) for k in
                ('quest_id', 'title', 'is_complete', 'is_campaign') if k in quest}
            for index, row in enumerate((quest.get('objectives') or ())[:16]):
                if not isinstance(row, dict):
                    continue
                oid = str(row.get('objective_id', f'{qid}:{index}'))
                self.data[('objective', oid)] = {k: json_copy(row[k]) for k in
                    ('objective_id', 'description', 'mechanism', 'type', 'current', 'required', 'is_complete') if k in row}
        entities = state.get('packet_entities') or {}
        for guid, row in list(entities.items())[:32]:
            if isinstance(row, dict) and not row.get('removed'):
                self.data[('entity', str(guid))] = {k: json_copy(row[k]) for k in ('guid', 'entry_id', 'kind', 'map_id') if k in row}
        target = state.get('target') or {}
        if (isinstance(target, dict) and target.get('guid') and target.get('is_player') is not True
                and not str(target['guid']).startswith('Player-')):
            self.data[('entity', str(target['guid']))] = {k: target[k] for k in
                ('guid', 'npc_id', 'object_id', 'name', 'attackable', 'dead') if k in target}
        for row in ((state.get('inventory') or {}).get('items') or ())[:32]:
            if isinstance(row, dict) and type(row.get('item_id')) is int:
                self.data[('item', str(row['item_id']))] = {k: row[k] for k in ('item_id', 'count', 'is_quest_item') if k in row}
        # Native ownership is separate from a client-visible carried stack.
        # An advisor can inspect the lower bound, never use it as UI readiness
        # or an absence proof. A single copied snapshot avoids per-item scans.
        native_query = getattr(world.query,'native_inventory',None)
        if callable(native_query):
            native = native_query(now)
            owned = {}
            for row in native.get('items') or ():
                item = str(row['item_id'])
                if item not in owned and len(owned)>=32:continue
                fact = owned.setdefault(item,{'count_lower_bound':0,'sample_times':[],
                    'evidence':[],'identity_evidence':[],'identity_sample_times':[],
                    'carried':None,'complete':False,'source':'PACKET_OWN_INVENTORY'})
                fact['count_lower_bound'] += row['stack_count']
                if len(fact['evidence'])<4:
                    fact['evidence'].append(row['observation_id']);fact['sample_times'].append(row['sample_time'])
                    fact['identity_evidence'].append(row['identity_evidence'])
                    fact['identity_sample_times'].append(row['identity_sample_time'])
            for item,fact in owned.items():
                row = self.data.setdefault(('item',item),{'item_id':int(item)})
                row['native_ownership'] = fact
            wanted = {ref for fact in owned.values() for ref in fact['evidence']}
            for entry in world.query.evidence('packet_event:OWN_ITEM_UPDATE',now)[:32]:
                if entry.observation_id in wanted:
                    self.data[('evidence',entry.observation_id)] = {
                        'field':'native_inventory_item','source':entry.source,
                        'observed_at':entry.observed_at,'completeness':'PARTIAL',
                        'confidence':entry.confidence,
                        'lineage':entry.lineage.as_dict(limit=4) if entry.lineage else None}
        for key in ('target', 'active_quests', 'inventory', 'player_world_position'):
            for entry in world.query.evidence(key, now)[:4]:
                self.data[('evidence', entry.observation_id)] = {
                    'field': key, 'source': entry.source, 'observed_at': entry.observed_at,
                    'completeness': entry.completeness.value, 'confidence': entry.confidence,
                    'lineage': entry.lineage.as_dict(limit=4) if entry.lineage else None}

    def call(self, request):
        if not isinstance(request, dict) or set(request) != {'tool', 'ref'}:
            raise ValueError('read_tool_schema')
        key = request['tool'], request['ref']
        if any(not isinstance(v, str) for v in key) or key not in self.data:
            raise ValueError('read_tool_reference_not_available')
        return json_copy(self.data[key])

    def context(self):
        import json
        groups = {'entity': 'entities', 'objective': 'objectives', 'item': 'items', 'evidence': 'evidence', 'quest': 'quests'}
        allowed = {group: [] for group in groups.values()}
        results = []
        budget = 24000
        for (tool, ref) in self.data:
            result = self.call({'tool': tool, 'ref': ref})
            cost = len(json.dumps(result, ensure_ascii=False))
            if cost > budget:
                continue
            budget -= cost
            allowed[groups[tool]].append(ref)
            results.append({'tool': tool, 'ref': ref, 'result': result})
        return {'allowed_refs': allowed, 'read_only_results': results}
