"""Invalidate current packet projections after an explicit stream discontinuity.

Old immutable observations/history stay available for diagnostics. They cannot
survive as current state or a field baseline across a provider gap/restart.
"""
from .models import json_copy


def accepts_event(model, event):
    provider = getattr(model, 'session_context_provider', None)
    expected = getattr(provider, 'capture_epoch', None)
    return (expected is None or event.get('semantic_status') != 'CONFIRMED'
            or event.get('provenance', {}).get('capture_epoch') == expected)


def current(model):
    provider = getattr(model, 'session_context_provider', None)
    if provider is None or not hasattr(provider, 'continuity_generation'):
        return True
    token = (provider.process.generation, provider.capture_epoch, provider.continuity_generation)
    return (model.__dict__.get('_packet_continuity_token') == token
            and provider.expected(provider.process.selected_pid) is not None)


def eligible_evidence(model, entries):
    return entries if current(model) else [e for e in entries if e.source != 'PACKET_TELEMETRY']


def refresh(model, state=None):
    provider = getattr(model, 'session_context_provider', None)
    if provider is None or not hasattr(provider, 'continuity_generation'):
        return False
    token = (provider.process.generation, provider.capture_epoch, provider.continuity_generation)
    if model.__dict__.get('_packet_continuity_token') == token:
        return False
    discard_fields(model, state)
    model.__dict__['_packet_continuity_token'] = token
    return True


# Live 2026-10-31 09:40 and 09:54 (logins, Westfall): the server answered the
# client's quest POI queries ~1.5 s before the login's NEW_WORLD; the world
# step bumped the continuity generation and every POI was discarded.  The
# client queries POIs only at login and on accept, so they never came back
# and the turn-in and objective search fell to TDB.  A POI is quest geometry
# for this player identity, not a world or stream field: it survives a
# continuity step and is read only under the same identity
# (world_packet_reducer._poi_scope).
IDENTITY_SCOPED = frozenset({'_packet_quest_pois', '_packet_poi_context', '_packet_poi_active_quests'})


def discard_fields(model, state=None):
    """Drop current native fields, retaining immutable source history/dedup."""
    for key in tuple(model.__dict__):
        if (key.startswith('_packet_') and key not in {'_packet_continuity_token', '_packet_event_ids'}
                and key not in IDENTITY_SCOPED
                or key in {'_power_context', '_entity_raw_maps'}):
            model.__dict__.pop(key, None)
    model.source_latest.pop('PACKET_TELEMETRY', None)
    # This is eviction from current evidence, not deletion of the source trace.
    for key, entries in tuple(model.evidence.items()):
        retained = [e for e in entries if e.source != 'PACKET_TELEMETRY']
        if retained:
            entries.clear()
            entries.extend(retained)
        else:
            model.evidence.pop(key, None)
    if state is not None:
        for key in tuple(state):
            if key.startswith('packet_'):
                state.pop(key, None)
        for key in ('health','max_health','power','max_power','power_type','class_id','player_class_id',
                    'race_id','level','orientation','player_world_position','target','movement_rooted'):
            if key in model.addon_state:
                state[key] = json_copy(model.addon_state[key])
            else:
                state.pop(key, None)
