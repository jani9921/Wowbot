"""Own quest-slot evidence only; QuestModel remains the quest-state owner.

Membership and storage counters do not supply objective definitions, UI row
order, reward receipts, accept actions or a reason for a quest disappearing.
"""
from wowbot.context_contracts import SessionContext
from .models import json_copy

FIELDS = ('quest_id', 'state_flags', 'end_time', 'objective_flags', 'enabled_objectives_mask')
MAX_AGE = 2.


def _record(model, sampled, context):
    scope = SessionContext.from_mapping(context).entity_scope()
    record = model.__dict__.get('_packet_quest_log')
    if record is None or record['scope'] != scope:
        record = {'scope':scope, 'slots':{}, 'baseline_observed_at':None,
                  'baseline_sample_kind':None, 'observed_at':sampled, 'invalidated_at':float('-inf')}
        model.__dict__['_packet_quest_log'] = record
    return record


def invalidate(model, observation, sampled, context):
    record = _record(model,sampled,context)
    if sampled <= record['invalidated_at']:
        return
    record['invalidated_at'] = sampled
    for index, slot in tuple(record['slots'].items()):
        for group in ('fields','progress'):
            slot[group] = {key:fact for key,fact in slot[group].items() if fact['observed_at'] > sampled}
        if not slot['fields'] and not slot['progress']:
            del record['slots'][index]
    if record['baseline_observed_at'] is not None and record['baseline_observed_at'] <= sampled:
        record['baseline_observed_at'] = record['baseline_sample_kind'] = None
    record['observed_at'] = max(record['observed_at'],sampled)
    model.add_evidence('quest_log_invalidated',True,observation,confidence=1.,ttl=MAX_AGE)
    provider = getattr(model,'session_context_provider',None)
    if provider is not None:
        provider.observe_field_coverage('questlog','PARTIAL' if record['slots'] else 'UNKNOWN',
                                        sampled,context=context)


def remember(model, body, observation, sampled, context):
    record = _record(model,sampled,context)
    if sampled <= record['invalidated_at']:
        return
    for raw in body['slots']:
        index, quest_id = raw[:2]
        old = record['slots'].get(index)
        if old and sampled < old['observed_at']:
            continue
        known_id = (old or {}).get('fields', {}).get('quest_id', {}).get('value')
        if old is None or quest_id is not None and quest_id != known_id:
            old = {'slot':index, 'fields':{}, 'progress':{}, 'observed_at':sampled}
            record['slots'][index] = old
        def fact(value):
            return {'value':value, 'observed_at':sampled, 'observation_id':observation.observation_id}
        for key, value in zip(FIELDS, raw[1:6]):
            if value is not None: old['fields'][key] = fact(value)
        for storage, value in enumerate(raw[6]):
            if value is not None: old['progress'][str(storage)] = fact(value)
        old['observed_at'] = sampled
    if (len(body['slots']) == 175 and all(row[1] is not None for row in body['slots'])
            and sampled >= (record['baseline_observed_at'] if record['baseline_observed_at'] is not None else float('-inf'))):
        record['baseline_observed_at'] = sampled
        record['baseline_sample_kind'] = body.get('sample_kind') or 'VALUES'
    record['observed_at'] = max(sampled, record['observed_at'])
    model.add_evidence('quest_log_slots', body['slots'], observation, confidence=1., ttl=MAX_AGE)
    provider = getattr(model, 'session_context_provider', None)
    if provider is not None:
        # Complete slot membership is not a complete quest definition baseline.
        provider.observe_field_coverage('questlog', 'PARTIAL', sampled, context=context)


def view(model, state, now, current_context, *, quest_id=None, include_slots=True):
    from .packet_continuity import current
    record = model.__dict__.get('_packet_quest_log')
    result = {'membership':'UNKNOWN', 'definitions':'UNKNOWN', 'objective_alignment':'UNKNOWN',
              'baseline_observed_at':None, 'baseline_sample_kind':None, 'known_slots':0, 'slots':[]}
    if record is None or not current(model):
        return result
    context = SessionContext.from_mapping(current_context(record['scope']['selected_pid']))
    if (context is None or context.entity_scope() != record['scope']
            or state.get('loading') or state.get('player_present') is False):
        return result
    from .runtime_packet_progress import retained
    def current_at(sampled):
        return 0 <= now-sampled <= MAX_AGE or retained(model, sampled, now)
    def fresh(fact):
        return fact is not None and current_at(fact['observed_at'])
    ids = [slot['fields'].get('quest_id') for slot in record['slots'].values()]
    complete = (record['baseline_observed_at'] is not None and len(ids) == 175 and all(fresh(f) for f in ids))
    result.update(membership='COMPLETE' if complete else 'PARTIAL',
                  baseline_observed_at=record['baseline_observed_at'],
                  baseline_sample_kind=record['baseline_sample_kind'],
                  known_slots=sum(current_at(s['observed_at']) for s in record['slots'].values()))
    if not result['known_slots']:
        result['membership'] = 'UNKNOWN'
    if not include_slots:
        return result
    for slot in record['slots'].values():
        identity = slot['fields'].get('quest_id')
        if quest_id is not None and (not fresh(identity) or identity['value'] != quest_id):
            continue
        value = {'slot':slot['slot'], 'fields':{k:v for k,v in slot['fields'].items() if fresh(v)},
                 'progress':{k:v for k,v in slot['progress'].items() if fresh(v)}}
        if value['fields'] or value['progress']:
            result['slots'].append(json_copy(value))
    return result


def project(model, state, now, current_context):
    # Hot-loop status contains counts only, never copies all 175 slot bodies.
    result = view(model, state, now, current_context, include_slots=False)
    if result['membership'] == 'UNKNOWN':
        record = model.__dict__.get('_packet_quest_log')
        if record:
            context = SessionContext.from_mapping(current_context(record['scope']['selected_pid']))
            if (state.get('loading') or state.get('player_present') is False
                    or context is None or context.entity_scope() != record['scope']):
                model.__dict__.pop('_packet_quest_log', None)
        return
    state['packet_quest_log'] = {k:v for k,v in result.items() if k != 'slots'}
