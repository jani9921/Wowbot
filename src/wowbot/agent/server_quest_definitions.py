"""Observed quest structure owned by QuestModel, never quest/action state.

World/phase changes do not change a quest's definition. Character/session,
process lifetime and build changes do; a stream gap temporarily suspends its
use. Original source times and evidence remain attached to every binding.
"""
from dataclasses import asdict

from wowbot.context_contracts import SessionContext
from .models import json_copy
from .quest_reference_matching import objective_text_key

MAX_AGE = 1800.
MAX_DEFINITIONS = 128
BINDING_KEYS = ('server_objective_id', 'server_storage_index', 'server_credit_object_id',
                'server_raw_type', 'server_required_amount', 'server_objective_visible',
                'server_definition_evidence', 'server_definition_sample_time')


def scope(context, process_generation=None):
    parsed = SessionContext.from_mapping(context)
    return ({**asdict(parsed.identity), 'process_generation': process_generation}
            if parsed is not None else None)


def available(row, selected_scope, now):
    return (row is not None and selected_scope is not None and row['scope'] == selected_scope
            and 0 <= now-row['sample_time'] <= MAX_AGE)


def select_context(owner, selected_scope, now):
    previous = owner.__dict__.get('_server_definition_active_scope')
    stored = owner.__dict__.get('_server_definition_scope')
    if selected_scope is not None and stored != selected_scope:
        owner.__dict__['_server_definitions'] = {}
        owner.__dict__['_server_definition_scope'] = json_copy(selected_scope)
    owner.__dict__['_server_definition_active_scope'] = json_copy(selected_scope)
    if (previous != selected_scope
            or now > owner.__dict__.get('_server_definition_expiry', float('-inf'))):
        apply_bindings(owner, now)


def remember(owner, kind, body, selected_scope, observation, sampled, provenance):
    select_context(owner, selected_scope, observation.received_at)
    rows = owner.__dict__.setdefault('_server_definitions', {})
    key = str(body['quest_id'])
    previous = rows.get(key)
    if previous is not None and sampled < previous['sample_time']:
        return
    rows[key] = {'status': 'OBSERVED_REFERENCE' if kind == 'QUEST_DEFINITION' else 'UNAVAILABLE',
                 'definition': json_copy(body.get('definition')), 'scope':json_copy(selected_scope),
                 'sample_time':sampled, 'received_at':observation.received_at,
                 'observation_id':observation.observation_id,
                 'source':'SMSG_QUERY_QUEST_INFO_RESPONSE',
                 'lineage':{k:provenance[k] for k in ('payload_layout','capture_epoch','semantic_record_id')
                            if k in provenance}}
    if len(rows) > MAX_DEFINITIONS:
        oldest = min(rows, key=lambda q: rows[q]['sample_time'])
        del rows[oldest]
    apply_bindings(owner, observation.received_at)


def view(owner, quest_id, selected_scope, now):
    row = owner.__dict__.get('_server_definitions', {}).get(str(quest_id))
    if not available(row, selected_scope, now):
        return {'status':'UNKNOWN', 'quest_id':quest_id}
    return json_copy({'quest_id':quest_id, **row})


def _matches(objective, rows):
    # An explicit global ID is a constraint. Its disagreement cannot be
    # repaired with a similarly worded, different objective or a UI ordinal.
    explicit = objective.raw.get('quest_objective_id')
    if explicit is None and str(objective.objective_id).isdigit():
        explicit = objective.objective_id
    if explicit is not None:
        return [r for r in rows if str(r['objective_id']) == str(explicit)]
    key = objective_text_key(objective.description)
    return [r for r in rows if key and objective_text_key(r['description']) == key]


def apply_bindings(owner, now):
    selected = owner.__dict__.get('_server_definition_active_scope')
    definitions = owner.__dict__.get('_server_definitions', {})
    expiries = [r['sample_time']+MAX_AGE for r in definitions.values() if available(r, selected, now)]
    owner.__dict__['_server_definition_expiry'] = min(expiries, default=float('inf'))
    for qid, record in owner.records.items():
        definition = definitions.get(str(qid))
        eligible = (available(definition, selected, now)
                    and definition['status'] == 'OBSERVED_REFERENCE')
        candidates = definition['definition']['objectives'] if eligible else ()
        matches = [_matches(o, candidates) for o in record.objectives]
        unique = [m[0]['objective_id'] for m in matches if len(m) == 1]
        for objective, matched in zip(record.objectives, matches):
            for key in BINDING_KEYS:
                objective.raw.pop(key, None)
            if len(matched) != 1 or unique.count(matched[0]['objective_id']) != 1:
                continue
            source = matched[0]
            objective.raw.update(server_objective_id=source['objective_id'],
                server_storage_index=source['storage_index'], server_credit_object_id=source['object_id'],
                server_raw_type=source['raw_type'], server_required_amount=source['amount'],
                server_objective_visible=source['visible'],
                server_definition_evidence=definition['observation_id'],
                server_definition_sample_time=definition['sample_time'])


def project(model, state, now, current_context):
    state.pop('server_quest_objectives', None)
    owner = getattr(model, 'quest_model', None)
    if owner is None or not owner.__dict__.get('_server_definition_scope'):
        return
    stored = owner.__dict__.get('_server_definition_scope')
    provider = getattr(model, 'session_context_provider', None)
    generation = provider.process.generation if provider is not None else None
    context = current_context(stored['selected_pid']) if stored else None
    if state.get('loading') or state.get('player_present') is False:
        context = None
    select_context(owner, scope(context, generation), now)
    if owner.__dict__.get('_server_definition_active_scope') is None:
        return
    # A compact, derived identity-role view for the existing shared skill
    # boundary. No second definition/quest-progress owner is introduced.
    bindings = {str(qid):{o.objective_id:{k:o.raw[k] for k in BINDING_KEYS if k in o.raw}
                         for o in record.objectives if 'server_objective_id' in o.raw}
                for qid, record in owner.records.items() if record.current_state == 'ACTIVE'}
    bindings = {qid:rows for qid,rows in bindings.items() if rows}
    if bindings:
        state['server_quest_objectives'] = bindings
