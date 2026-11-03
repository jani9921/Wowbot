"""Scoped native item evidence inside WorldModel, not an inventory UI owner.

Partial native counts never replace a complete client bag/UI snapshot, never
authorize clicking a button, and never prove a quest credit/reward receipt.
"""
from wowbot.context_contracts import SessionContext
from .models import json_copy

MAX_AGE = 2.
MAX_ITEMS = 2048


def remember(model, kind, body, observation, sampled, context):
    scope = SessionContext.from_mapping(context).entity_scope()
    record = model.__dict__.get('_packet_inventory')
    if record is None or record['scope'] != scope:
        record = {'scope':scope,'items':{},'invalidated':{},'roots':{},
                  'roots_time':float('-inf'),'root_barrier':float('-inf'),
                  'root_baseline_time':None,'observed_at':sampled}
        model.__dict__['_packet_inventory'] = record
    def fact(value):
        return {'value':json_copy(value),'observed_at':sampled,'observation_id':observation.observation_id}
    if kind in {'OWN_INVENTORY_ROOTS','OWN_INVENTORY_INVALIDATED'}:
        if sampled <= record['root_barrier']:
            return
        if kind == 'OWN_INVENTORY_INVALIDATED':
            record['root_barrier'] = sampled
            record['roots'] = {key:value for key,value in record['roots'].items()
                               if value['observed_at'] > sampled}
            if record['root_baseline_time'] is not None and record['root_baseline_time'] <= sampled:
                record['root_baseline_time'] = None
        elif body.get('sample_kind') == 'CREATE':
            if sampled < record['roots_time']:
                return  # an older whole snapshot cannot undo a newer delta
            record['roots'] = {}
            record['root_baseline_time'] = sampled
        if kind == 'OWN_INVENTORY_ROOTS':
            for index,item_guid in body['root_slots']:
                key = str(index)
                previous = record['roots'].get(key)
                if previous is None or sampled >= previous['observed_at']:
                    record['roots'][key] = fact(item_guid)
        record['roots_time'] = max(sampled,record['roots_time'])
    else:
        guid = body['item_guid']
        previous = record['items'].get(guid)
        barrier = record['invalidated'].get(guid,float('-inf'))
        if sampled < barrier or ((body.get('sample_kind')=='CREATE' or kind=='OWN_ITEM_REMOVED')
                                and previous and sampled < previous['observed_at']):
            return
        if kind == 'OWN_ITEM_REMOVED':
            record['items'].pop(guid,None)
            record['invalidated'][guid] = sampled
            while len(record['invalidated']) > MAX_ITEMS:
                record['invalidated'].pop(next(iter(record['invalidated'])))
        else:
            if body.get('sample_kind')=='VALUES' and previous is None:
                return  # a delta cannot manufacture its missing CREATE identity
            value = json_copy(previous['value']) if previous else {}
            clocks = json_copy(previous.get('fields',{})) if previous else {}
            positions = json_copy(previous.get('positions',{})) if previous else {}
            for key in ('item_guid','item_id','container_guid','stack_count','durability','max_durability','num_slots'):
                if key in body and sampled >= clocks.get(key,{}).get('observed_at',float('-inf')):
                    value[key]=body[key]
                    clocks[key]={'observed_at':sampled,'observation_id':observation.observation_id}
            for index,item_guid in body.get('container_slots',body.get('container_slots_delta',())):
                key=str(index)
                if sampled >= positions.get(key,{}).get('observed_at',float('-inf')):
                    positions[key]={'value':item_guid,'observed_at':sampled,
                                    'observation_id':observation.observation_id}
            record['items'][guid] = {**fact(value), 'fields':clocks,'positions':positions,
                                    'observed_at':max(sampled,(previous or {}).get('observed_at',sampled))}
            if len(record['items'])>MAX_ITEMS:
                oldest=min(record['items'],key=lambda key:record['items'][key]['observed_at'])
                del record['items'][oldest]
    record['observed_at'] = max(record['observed_at'],sampled)
    provider = getattr(model,'session_context_provider',None)
    if provider is not None:
        provider.observe_field_coverage('inventory','PARTIAL',sampled,context=context)


def view(model, state, now, current_context, *, item_id=None, include_items=True):
    from .packet_continuity import current
    record = model.__dict__.get('_packet_inventory')
    result = {'coverage':'UNKNOWN','root_membership':'UNKNOWN','root_sample_time':None,
              'root_baseline_time':None,'root_known_slots':0,
              'source':'PACKET_OWN_INVENTORY','known_items':0,'items':[]}
    if not record or not current(model):return result
    context = SessionContext.from_mapping(current_context(record['scope']['selected_pid']))
    if (context is None or context.entity_scope() != record['scope']
            or state.get('loading') or state.get('player_present') is False):
        return result
    from .runtime_packet_progress import retained
    def current_at(sampled):
        # Field clock within MAX_AGE, or a progress-witnessed retained lease.
        return 0 <= now-sampled <= MAX_AGE or retained(model, sampled, now)
    roots = {int(index):value for index,value in record['roots'].items()
             if current_at(value['observed_at'])}
    result['root_baseline_time'] = record['root_baseline_time']
    if roots:
        from wowbot.packetio.own_inventory_codec import ZERO,ROOT_COUNT
        identities = [row['value'] for row in roots.values() if row['value'] != ZERO]
        contradiction = len(identities) != len(set(identities))
        result.update(coverage='PARTIAL',root_known_slots=len(roots),
                      root_sample_time=min(row['observed_at'] for row in roots.values()),
                      root_membership='UNKNOWN' if contradiction else
                          'COMPLETE' if len(roots)==ROOT_COUNT else 'PARTIAL')
        if include_items and not contradiction:
            result['root_slots'] = [[index,roots[index]['value']] for index in sorted(roots)]
            result['root_slot_evidence'] = {str(index):{key:row[key] for key in ('observed_at','observation_id')}
                                            for index,row in roots.items()}
            observations = {row['observation_id'] for row in roots.values()}
            if len(observations)==1:
                result['root_observation_id'] = next(iter(observations))
    for row in record['items'].values():
        count_clock=row['fields'].get('stack_count')
        if count_clock is None or not current_at(count_clock['observed_at']):continue
        result['coverage']='PARTIAL'
        result['known_items']+=1
        if include_items and (item_id is None or row['value']['item_id']==item_id):
            # ItemGUID -> entry binding is retained only within this known
            # lifecycle/scope. It is not resampled by quantity/durability.
            entry=row['fields']['item_id']
            item={k:row['value'][k] for k in ('item_guid','item_id','stack_count')}
            for key in ('container_guid','durability','max_durability','num_slots'):
                clock=row['fields'].get(key)
                if clock is not None and current_at(clock['observed_at']):
                    item[key]=row['value'][key]
            positions=[[int(index),position['value']] for index,position in row['positions'].items()
                       if current_at(position['observed_at'])]
            if positions:
                from wowbot.packetio.own_inventory_codec import ZERO
                known_guids=[g for _,g in positions if g!=ZERO]
                contradiction=(len(set(known_guids))!=len(known_guids)
                    or 'num_slots' in item and any(i>=item['num_slots'] and g!=ZERO for i,g in positions))
                item['container_slots_coverage']=('UNKNOWN' if contradiction else
                    'COMPLETE' if len(positions)==98 and 'num_slots' in item else 'PARTIAL')
                if not contradiction:item['container_slots']=positions
            result['items'].append({**item,'sample_time':count_clock['observed_at'],
                'observation_id':count_clock['observation_id'],'identity_sample_time':entry['observed_at'],
                'identity_evidence':entry['observation_id'],'carried':None})
    return result


def project(model, state, now, current_context):
    state.pop('packet_inventory',None)
    result = view(model,state,now,current_context,include_items=False)
    if result['coverage']!='UNKNOWN':
        state['packet_inventory'] = {k:v for k,v in result.items() if k!='items'}
