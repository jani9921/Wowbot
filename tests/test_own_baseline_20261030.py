"""Own UnitData create baseline: conditional owner fields and no other players."""
from dataclasses import replace
import struct

import pytest

from wowbot.agent.models import Observation
from wowbot.packetio.pkt import _decode_update_object
from wowbot.packetio.validation import normalize_event
from wowbot.session_context import ProcessIdentity, SessionContextProvider
from test_own_health_packets_20261030 import RAW_ME, own_event
from test_packet_codecs import packed_guid
from test_packet_agent_bridge import addon, bridge, deliver
from test_unit_fields_20261027 import unit_tail_bytes, bits


def create_payload(*, low=0x1234, object_type=7, owner=True):
    # ThisIsYou, Stationary, PlayerCreateData, with neither scenes nor runes.
    flags = [(int(i in {4, 7, 16}), 1) for i in range(21)]
    movement = bits(flags)+struct.pack('<IffffB', 0, 1., 2., 3., 0., 0)
    fields = bytes((int(owner), 3, 255, 1))+struct.pack('<iIfiII', 0, 0, 1., 0, 0, 0)
    fields += unit_tail_bytes(health=40, max_health=100, owner=owner, identity=bytes((1, 1, 1, 0, 0, 1)))
    block = bytes((2,))+packed_guid(low=low)+bytes((object_type,))+movement+struct.pack('<I', len(fields))+fields
    return struct.pack('<HI', 2175, 1)+bytes((0,))+struct.pack('<I', len(block))+block


@pytest.mark.parametrize('kind', [6, 7])
@pytest.mark.parametrize('owner', [False, True])
def test_selected_own_create_establishes_hp_without_waiting_for_a_delta(kind, owner):
    rows = _decode_update_object(create_payload(object_type=kind, owner=owner), {}, own_character_guid='Player-1602-00001234')
    assert rows[0][0] == 'OWN_INVENTORY_INVALIDATED'  # this fixture ends before the inventory prefix
    assert rows[1][0] == 'OWN_QUEST_LOG_INVALIDATED'  # no quest baseline in this prefix fixture
    rows = rows[2:]
    assert rows[0] == ('OWN_PROFILE_UPDATE', {'mover_guid': RAW_ME, 'world_map_id': 2175,
                      'sample_kind': 'CREATE', 'race_id': 1, 'class_id': 1, 'player_class_id': 1,
                      'power_type': 1, 'level': 70})
    assert rows[1:] == [('OWN_UNIT_UPDATE', {'mover_guid': RAW_ME, 'world_map_id': 2175,
                    'sample_kind': 'CREATE', 'health': 40, 'max_health': 100})]


def test_other_player_create_never_reads_or_forwards_private_unit_prefix(monkeypatch):
    from wowbot.packetio import update_object
    def forbidden(*args): pytest.fail('other player unit fields were read')
    monkeypatch.setattr(update_object, '_unit_tail', forbidden)
    assert _decode_update_object(create_payload(low=0x9999), {}, own_character_guid='Player-1602-00001234') == []
    assert _decode_update_object(create_payload(), {}) == []


def test_corrupt_or_partial_own_create_never_claims_complete():
    decoder, record = own_event()
    for body in (create_payload()[:-1], create_payload()+b'unknown'):
        assert len(decoder.decode_all(replace(record, payload=body))) == 1
    event = decoder.decode_all(replace(record, payload=create_payload()))[-1].to_dict()
    event['provenance']['payload_layout'] = 'WPP_12_1_OWN_UNIT_REVIEWED_V1'
    with pytest.raises(ValueError): normalize_event(event)


def test_baseline_metadata_does_not_grant_input_liveness_or_need_a_health_change(bridge):
    bridge.world.ingest(Observation.create(addon(game_build='70575', health=100, max_health=100), 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)
    decoder, record = own_event()
    deliver(bridge, decoder.decode_all(replace(record, payload=create_payload()))[-1])
    assert bridge.world.state['health'] == 40
    assert bridge.world.state['packet_own_health']['coverage'] == 'COMPLETE'
    assert bridge.world.last_received == 9.1


def test_coverage_scope_rejects_other_identity_resets_on_phase_but_not_ui_map():
    provider = SessionContextProvider(ProcessIdentity(77, '0000000000000001'))
    state = addon(game_build='70575')
    provider.observe_addon(state)
    context = provider.expected(77)
    assert not provider.observe_field_coverage('own_health', 'COMPLETE', 10., context={**context, 'selected_pid': 78})
    assert provider.observe_field_coverage('own_health', 'COMPLETE', 10., context=context)
    revision = provider.revision
    assert provider.diagnostics()['coverage']['own_health'] == 'COMPLETE'
    assert provider.revision == revision
    provider.observe_addon({**state, 'map_id': 1410})
    assert provider.diagnostics()['coverage']['own_health'] == 'COMPLETE'
    provider.observe_addon({**state, 'phase': 'new-phase'})
    assert provider.diagnostics()['coverage']['own_health'] == 'UNKNOWN'


def test_loading_clears_baseline_even_after_short_lived_health_cache_expired(bridge):
    from wowbot.agent.packet_own_health import project
    from wowbot.packetio.context import addon_context
    bridge.world.ingest(Observation.create(addon(game_build='70575', health=100, max_health=100), 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)
    decoder, record = own_event()
    deliver(bridge, decoder.decode_all(replace(record, payload=create_payload()))[-1])
    context = addon_context(bridge.world.addon_state, 77)
    project(bridge.world, {}, 15., lambda pid: context)
    assert '_packet_own_health' not in bridge.world.__dict__
    assert '_packet_health_baseline' in bridge.world.__dict__
    project(bridge.world, {'loading': True}, 16., lambda pid: None)
    assert '_packet_health_baseline' not in bridge.world.__dict__
