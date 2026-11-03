"""Own resources use DB2 display units and isolated per-type evidence."""
from wowbot.character_resources import display_power, resource_reference
from wowbot.context_contracts import SessionContext


def remember(model, body, observation, sampled, context):
    scope = SessionContext.from_mapping(context).entity_scope()
    if model.__dict__.get('_power_context') != scope:
        model.__dict__['_packet_powers'] = {}
        model.__dict__['_power_context'] = scope
    kind = body['power_type']
    profile = resource_reference(kind)
    value = display_power(body['raw_power'], profile)
    records = model.__dict__.setdefault('_packet_powers', {})
    if sampled < records.get(kind, {}).get('observed_at', float('-inf')):
        return
    records[kind] = {'power_type': kind, 'raw_value': body['raw_power'], 'value': value,
                     'observed_at': sampled, 'display_modifier': profile['display_modifier'] if profile else None,
                     'reference_sha256': profile['source_sha256'] if profile else None}
    while len(records) > 32:
        records.pop(next(iter(records)))
    if value is not None:
        model.add_evidence('resource_power:'+str(kind), value, observation, confidence=1., ttl=2.)


def project(model, state, now, current_context):
    scope = model.__dict__.get('_power_context') or (model.__dict__.get('_packet_own_profile') or {}).get('scope')
    if scope is None:
        return
    context = SessionContext.from_mapping(current_context(scope['selected_pid']))
    if (context is None or context.entity_scope() != scope or state.get('loading')
            or state.get('player_present') is False):
        model.__dict__.pop('_packet_powers', None)
        model.__dict__.pop('_power_context', None)
        return
    rows = {str(k): dict(v) for k, v in (model.__dict__.get('_packet_powers') or {}).items()
            if 0 <= now-v['observed_at'] <= 2.}
    active = model.query.field_resolution('power_type', now)
    kind = active.value if active.state == 'KNOWN' and type(active.value) is int else None
    for key, prefix in (('power', 'resource_power:'), ('max_power', 'resource_max_power:')):
        selected = model.query.field_resolution(prefix+str(kind), now) if kind is not None else None
        state[key] = selected.value if selected is not None and selected.state == 'KNOWN' else None
    # Neither MaxBasePower nor another resource's newest value is the
    # current primary resource maximum. Actual max stays an explicit source.
    state['packet_own_resources'] = {'coverage': 'PARTIAL', 'active_power_type': kind, 'values': rows}
