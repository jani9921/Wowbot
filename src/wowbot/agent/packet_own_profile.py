"""Reviewed own UnitData profile fields, using the common field resolver."""
from wowbot.context_contracts import SessionContext


FIELDS = ('race_id', 'class_id', 'player_class_id', 'level', 'power_type')


def remember(model, body, observation, sampled, context):
    scope = SessionContext.from_mapping(context).entity_scope()
    model.__dict__['_packet_own_profile'] = {'scope': scope, 'observed_at': sampled}
    for key in FIELDS:
        if key in body and (key == 'power_type' or body[key] > 0):
            # A type enum of zero is mana. A zero class/race/level is unknown.
            model.add_evidence(key, body[key], observation, confidence=1., ttl=2.)


def project(model, state, now, current_context):
    record = model.__dict__.get('_packet_own_profile')
    if record is None:
        return
    context = SessionContext.from_mapping(current_context(record['scope']['selected_pid']))
    if (context is None or context.entity_scope() != record['scope']
            or state.get('loading') or state.get('player_present') is False
            or not 0 <= now-record['observed_at'] <= 2.):
        model.__dict__.pop('_packet_own_profile', None)
        return
    selected = {}
    for key in FIELDS:
        result = model.query.field_resolution(key, now)
        if result.state == 'KNOWN':
            state[key] = result.value
            selected[key] = result.diagnostic()
    # This is a known prefix, not specialization/talent/role or a full baseline.
    state['packet_own_profile'] = {'coverage': 'PARTIAL', 'selected_fields': selected}
