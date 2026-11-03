"""Bounded cast facts within WorldModel. This module never dispatches input."""
from .models import json_copy, number
from wowbot.context_contracts import SessionContext
from wowbot.packetio.context import addon_entity_guid


def _scope(context):
    parsed = SessionContext.from_mapping(context)
    return parsed.entity_scope() if parsed else None


def remember(model, kind, body, sampled, context):
    scope = _scope(context)
    if scope != model.__dict__.get('_packet_combat_context') or kind == 'MAP_CHANGED':
        model.__dict__['_packet_casts'] = {}
        model.__dict__['_packet_combat_context'] = scope
    casts = model.__dict__.setdefault('_packet_casts', {})
    guid = addon_entity_guid(body.get('caster_guid', body.get('entity_guid')))
    if not guid:
        return
    current = casts.get(guid)
    if kind == 'ENTITY_REMOVED':
        casts.pop(guid, None)
    elif kind == 'SPELL_CAST_STARTED':
        if current and sampled < current['observed_at']:
            return
        casts[guid] = {'caster_guid': guid, 'cast_id': body['cast_id'], 'spell_id': body['spell_id'],
                       'started_at': sampled, 'ends_at': sampled+body['cast_time_ms']/1000.,
                       'observed_at': sampled, 'interruptible': None, 'source': 'SMSG_SPELL_START'}
        while len(casts) > 128:
            casts.pop(next(iter(casts)))
    elif (kind in {'SPELL_CAST_RELEASED', 'SPELL_CAST_RESULT'} and current
          and current['cast_id'] == body.get('cast_id') and current['spell_id'] == body.get('spell_id')
          and sampled >= current['observed_at']):
        casts.pop(guid, None)
    # INTERRUPT_LOG has no CastID. Retain its discrete event, but do not bind
    # it to a particular cast through an inferred ID or mark our action done.


def project(model, state, now, current_context):
    scope = model.__dict__.get('_packet_combat_context')
    casts = model.__dict__.get('_packet_casts', {})
    if scope is not None and (_scope(current_context(scope['selected_pid'])) != scope
                              or state.get('loading') or state.get('player_present') is False):
        model.__dict__['_packet_casts'] = casts = {}
        model.__dict__.pop('_packet_combat_context', None)
    expired = [guid for guid, cast in casts.items() if not cast['observed_at'] <= now < cast['ends_at']]
    for guid in expired:
        casts.pop(guid, None)
    target = state.get('target')
    if isinstance(target, dict):
        known = casts.get(target.get('guid'))
        old = target.get('cast')
        old_at = number(old.get('observed_at')) if isinstance(old, dict) else None
        if known and (old_at is None or old_at <= known['observed_at']):
            target['cast'] = json_copy(known)
        elif isinstance(old, dict) and old.get('source') == 'SMSG_SPELL_START':
            target.pop('cast', None)
    state['packet_combat'] = {'active_casts': len(casts), 'cast_lifecycle': 'PARTIAL',
                              'interruptibility': 'UNKNOWN', 'hazard_coverage': 'UNKNOWN'}
