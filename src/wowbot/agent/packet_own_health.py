"""Own health deltas feed the same per-field evidence policy as the addon."""
from wowbot.context_contracts import SessionContext
from .models import number


def remember(model, body, observation, sampled, context):
    scope = SessionContext.from_mapping(context).entity_scope()
    baseline = body.get('sample_kind') == 'CREATE' and {'health', 'max_health'}.issubset(body)
    if baseline:
        model.__dict__['_packet_health_baseline'] = {'scope': scope, 'observed_at': sampled}
    baseline_record = model.__dict__.get('_packet_health_baseline') or {}
    baseline = baseline_record.get('scope') == scope
    model.__dict__['_packet_own_health'] = {'scope': scope, 'observed_at': sampled,
                                           'baseline_complete': baseline,
                                           'fields': [k for k in ('health', 'max_health') if k in body]}
    provider = getattr(model, 'session_context_provider', None)
    if provider is not None:
        provider.observe_field_coverage('own_health', 'COMPLETE' if baseline else 'PARTIAL', sampled, context=context)
    for key in ('health', 'max_health'):
        if key in body:
            model.add_evidence(key, body[key], observation, confidence=1., ttl=2.)


def project(model, state, now, current_context):
    record = model.__dict__.get('_packet_own_health')
    baseline = model.__dict__.get('_packet_health_baseline')
    scope = (record or baseline or {}).get('scope')
    if scope is None:
        return
    context = SessionContext.from_mapping(current_context(scope['selected_pid']))
    if (context is None or context.entity_scope() != scope
            or state.get('loading') or state.get('player_present') is False):
        model.__dict__.pop('_packet_own_health', None)
        model.__dict__.pop('_packet_health_baseline', None)
        return
    if not record:
        return
    if not 0 <= now-record['observed_at'] <= 2.:
        model.__dict__.pop('_packet_own_health', None)
        return
    selected = {}
    for key in ('health', 'max_health'):
        result = model.query.field_resolution(key, now)
        if result.state == 'KNOWN' and number(result.value) is not None:
            state[key] = result.value
            selected[key] = result.diagnostic()
    state['packet_own_health'] = {'coverage': 'COMPLETE' if record.get('baseline_complete') else 'PARTIAL',
                                 'observed_at': record['observed_at'],
                                 'baseline_observed_at': (model.__dict__.get('_packet_health_baseline') or {}).get('observed_at'),
                                 'selected_fields': selected}
