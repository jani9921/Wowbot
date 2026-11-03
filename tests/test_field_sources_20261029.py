from dataclasses import replace
import json

from wowbot.evidence_contracts import Evidence, EvidenceCompleteness as Complete, SourceLineage, EvidenceDirection
from wowbot.field_sources import FieldSourceResolver, FieldResolutionState as State
from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel
from wowbot.agent.objective_locator import ObjectiveLocator
from test_m1_objective_locator import objective
from types import SimpleNamespace


def claim(key, value, *, source='ADDON_TELEMETRY', at=10., direction=None, complete=Complete.UNKNOWN, token='a'):
    return Evidence(token, token, source, at, at+5., json.dumps(value), 1., 1.,
        json.dumps({'session_id': 's'}), token, 'GROUND_TRUTH', 4, key,
        lineage=SourceLineage(direction=direction or EvidenceDirection.UNKNOWN,
                              payload_layout='reviewed' if direction else None), completeness=complete)


def test_ui_recipient_is_local_even_when_a_server_entity_exists():
    resolver = FieldSourceResolver()
    server = claim('target', {'guid': 'other'}, source='PACKET_TELEMETRY',
                   direction=EvidenceDirection.SERVER_TO_CLIENT, token='p')
    local = claim('target', {'guid': 'selected'})
    assert resolver.resolve('target', [server, local], 11.).value == {'guid': 'selected'}


def test_sampled_movement_is_newest_and_outgoing_is_not_server_ack():
    from wowbot.field_sources import belief_projection
    packet = claim('orientation', 1., source='PACKET_TELEMETRY', at=11., token='p',
                   direction=EvidenceDirection.CLIENT_TO_SERVER)
    addon = claim('orientation', 2.)
    result = FieldSourceResolver().resolve('orientation', [addon, packet], 12.)
    assert result.value == 1. and result.diagnostic()['authority'] == 'CLIENT_FEEDBACK'
    assert belief_projection(result)['status'] == 'SUPPORTED'
    assert FieldSourceResolver().resolve('orientation', [replace(addon, at=12., sampled_at_monotonic=12.), packet], 12.).value == 2.


def test_empty_unknown_collection_does_not_prove_absence_or_replace_complete_baseline():
    complete = claim('active_quests', [{'quest_id': 7}], complete=Complete.COMPLETE)
    empty = claim('active_quests', [], at=11., token='b')
    resolver = FieldSourceResolver()
    assert resolver.resolve('active_quests', [complete, empty], 12.).value == [{'quest_id': 7}]
    assert resolver.resolve('active_quests', [empty], 12.).state is State.UNKNOWN
    assert resolver.resolve('active_quests', [replace(empty, completeness=Complete.COMPLETE)], 12.).value == []


def test_context_future_and_equal_sample_conflict_are_not_arbitrarily_resolved():
    a = claim('health', 10)
    b = claim('health', 20, token='b')
    resolver = FieldSourceResolver()
    assert resolver.resolve('health', [a, b], 11.).state is State.CONFLICT
    assert resolver.resolve('health', [a], 9.).state is State.UNKNOWN
    assert resolver.resolve('health', [a], 11., context={'session_id': 'other'}).state is State.UNKNOWN


def test_world_belief_really_uses_the_field_policy_and_is_read_only():
    world = WorldModel()
    world.ingest(Observation.create({'session_id': 's', 'frame_id': 'a', 'target': {'guid': 'selected'}}, 10.))
    world.evidence['target'].append(claim('target', {'guid': 'other'}, source='PACKET_TELEMETRY',
                                        direction=EvidenceDirection.SERVER_TO_CLIENT, token='p'))
    assert world.query.belief('target', 11.)['value'] == {'guid': 'selected'}
    assert world.query.field_resolution('target', 11.).value == {'guid': 'selected'}


def test_live_objective_pin_precedes_static_hypothesis():
    obj = objective(objective_id='7:0', description='Go', target_location={'map_id': 1, 'x': .2, 'y': .3})
    found = ObjectiveLocator().locate(obj, SimpleNamespace(quest_id=7, known_locations=[]), {'map_id': 1})
    assert found.evidence == ('objective_api_location',)


def test_server_objective_polygon_is_read_on_demand_and_preserves_unknown_z():
    from wowbot.agent.quest_poi_evidence import objective_destinations
    world = WorldModel()
    from test_packet_agent_bridge import addon
    world.ingest(Observation.create(addon(session_id='s'), 10.))
    from wowbot.packetio.context import addon_context
    from wowbot.context_contracts import SessionContext
    from wowbot.agent.world_packet_reducer import _poi_scope
    scope = _poi_scope(addon_context(world.addon_state, 77))     # identity scope (2026-10-31)
    world.__dict__['_packet_poi_context'] = scope
    world.__dict__['_packet_quest_pois'] = {'7': {'verified': True, 'sampled_at': 10., 'blobs': [
        {'objective_index': 0, 'objective_id': 99, 'world_map_id': 2175, 'ui_map_id': 1409,
         'blob_index': 2, 'group_index': 3, 'points': [{'x': 5., 'y': 6., 'z': 0.}]}]}}
    blobs = world.query.quest_pois(7, 11., objective_index=0, objective_id=99)
    assert len(blobs) == 1
    blobs[0]['points'][0]['x'] = 100.
    assert world.query.quest_pois(7, 11.)[0]['points'][0]['x'] == 5.
    assert not world.query.quest_pois(7, 11., objective_id=100)
    assert not world.query.quest_pois(7, 1811.)
    dest = objective_destinations(world.state, world.query.quest_pois(7, 11.))[0]
    assert dest['source'] == 'PACKET_QUEST_POI' and dest['z_known'] is False
    assert dest.get('z') in (None, 0.)
