"""Selected own UnitData profile, including primary-resource identity."""
from dataclasses import replace
import json
import struct

import pytest

from wowbot.agent.models import Observation
from wowbot.combat_contracts import CharacterProfile
from wowbot.packetio.pkt import _decode_update_object
from wowbot.packetio.ipc import canonical, envelope
from wowbot.packetio.models import AgentPacketEvent
from wowbot.packetio.validation import normalize_event, verified_semantics
from test_own_baseline_20261030 import create_payload
from test_own_health_packets_20261030 import RAW_ME, own_event
from test_own_power_20261030 import power_events
from test_packet_agent_bridge import addon, bridge, deliver
from test_packet_codecs import packed_guid
from test_unit_fields_20261027 import bits


def profile_event(*, low=0x1234, map_id=2175, power_type=1):
    decoder, record = own_event()
    mask0, mask1 = 1 | (1 << 30) | (1 << 31), 1 | (1 << 1) | (1 << 4) | (1 << 8)
    values = bits([(3, 8), (mask0, 32), (mask1, 32)]) + bytes((1, 11, 1, power_type)) + struct.pack('<i', 70)
    fields = bytes((0, 0, 3))+struct.pack('<I', 0x20)+values
    block = bytes((0,))+packed_guid(low=low)+struct.pack('<I', len(fields))+fields
    body = struct.pack('<HI', map_id, 1)+bytes((0,))+struct.pack('<I', len(block))+block
    return decoder, replace(record, payload=body)


def test_values_mask_names_class_race_display_power_without_power_array_index_guess():
    decoder, record = profile_event()
    event = decoder.decode_all(record)[-1]
    assert event.event_type == 'OWN_PROFILE_UPDATE'
    assert event.payload == {'mover_guid': RAW_ME, 'world_map_id': 2175, 'sample_kind': 'VALUES',
        'race_id': 1, 'class_id': 11, 'player_class_id': 1, 'power_type': 1, 'level': 70}
    assert verified_semantics(normalize_event(event.to_dict()))
    assert event.provenance['payload_layout'] == 'WPP_12_1_OWN_PROFILE_REVIEWED_V1'


def test_create_profile_and_health_have_separate_completeness():
    decoder, record = own_event()
    events = decoder.decode_all(replace(record, payload=create_payload()))
    assert [e.event_type for e in events] == ['PACKET_OPCODE_OBSERVED', 'OWN_INVENTORY_INVALIDATED',
                                             'OWN_QUEST_LOG_INVALIDATED', 'OWN_PROFILE_UPDATE', 'OWN_UNIT_UPDATE']
    assert all(verified_semantics(normalize_event(e.to_dict())) for e in events[1:])


def test_other_player_values_are_not_read_even_with_known_fragments(monkeypatch):
    from wowbot.packetio import update_object
    decoder, record = profile_event(low=0x9999)
    other = f'{(2<<58)|(1602<<42):016X}{0x9999:016X}'
    def forbidden(*args): pytest.fail('another player profile was read')
    monkeypatch.setattr(update_object, '_values_unit', forbidden)
    assert _decode_update_object(record.payload, {other: (3,)}, own_character_guid='Player-1602-00001234') == []
    assert _decode_update_object(record.payload, {other: (3,)}) == []


def test_login_intent_or_unknown_unit_fragments_cannot_create_profile():
    decoder, record = profile_event()
    decoder._verified_player_guids.clear()
    assert len(decoder.decode_all(record)) == 1
    decoder, record = profile_event()
    decoder.entity_fragments.clear()
    assert len(decoder.decode_all(record)) == 1


def setup(bridge):
    bridge.world.ingest(Observation.create(addon(game_build='70575', level=60), 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)


def test_native_profile_enables_typed_power_and_combat_class_without_addon_type(bridge):
    setup(bridge)
    assert 'power_type' not in bridge.world.addon_state
    decoder, record = profile_event()
    deliver(bridge, decoder.decode_all(record)[-1])
    decoder, record = power_events(((1, 750),))
    deliver(bridge, decoder.decode_all(record)[-1])
    state = bridge.world.state
    assert state['level'] == 70 and state['power_type'] == 1 and state['power'] == 75
    profile = CharacterProfile.from_state(state)
    assert profile.class_id == 1 and profile.resource_type == 1
    assert state['packet_own_profile']['coverage'] == 'PARTIAL'
    assert bridge.world.last_received == 9.1


def test_wrong_world_profile_does_not_overwrite_current_level_or_resource_type(bridge):
    setup(bridge)
    decoder, record = profile_event(map_id=1)
    deliver(bridge, decoder.decode_all(record)[-1])
    assert bridge.world.state['level'] == 60 and 'power_type' not in bridge.world.state


def test_native_type_change_cannot_relabel_old_addon_amount_or_maximum(bridge):
    bridge.world.ingest(Observation.create(addon(game_build='70575', power_type=1, power=75, max_power=150), 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)
    decoder, record = profile_event(power_type=0)
    deliver(bridge, decoder.decode_all(record)[-1])
    assert bridge.world.state['power_type'] == 0
    assert bridge.world.state['power'] is None and bridge.world.state['max_power'] is None
    decoder, record = power_events(((0, 42),))
    deliver(bridge, decoder.decode_all(record)[-1])
    assert bridge.world.state['power'] == 42 and bridge.world.state['max_power'] is None
    bridge.world.ingest(Observation.create(addon(game_build='70575', frame_id='mana-full',
        monotonic_time=10.2, power_type=0, power=40, max_power=1000), 10.2))
    assert bridge.world.state['power'] == 40 and bridge.world.state['max_power'] == 1000


def test_delayed_full_profile_does_not_hide_native_update_and_newer_full_wins(bridge):
    setup(bridge)
    decoder, record = profile_event()
    deliver(bridge, decoder.decode_all(record)[-1])
    bridge.world.ingest(Observation.create(addon(game_build='70575', frame_id='old-full',
        monotonic_time=11., state_sample_time=9., level=60), 11.))
    assert bridge.world.state['level'] == 70
    assert bridge.world.evidence['level'][-1].observed_at == 9.
    bridge.world.ingest(Observation.create(addon(game_build='70575', frame_id='new-full',
        monotonic_time=11.1, level=71), 11.1))
    assert bridge.world.state['level'] == 71
    assert bridge.world.query.field_resolution('level', 11.1).diagnostic()['authority'] == 'ADDON_STATE'


@pytest.mark.parametrize('change', [{'loading': True}, {'phase': 'other'}, {'character_guid': 'Player-1602-99999999'}])
def test_profile_does_not_cross_context_or_loading(bridge, change):
    setup(bridge)
    decoder, record = profile_event()
    deliver(bridge, decoder.decode_all(record)[-1])
    bridge.world.ingest(Observation.create(addon(game_build='70575', frame_id='next', **change), 10.1))
    assert 'packet_own_profile' not in bridge.world.state
    assert 'class_id' not in bridge.world.state


def test_profile_expiry_never_refreshes_source_measurement(bridge):
    setup(bridge)
    decoder, record = profile_event()
    deliver(bridge, decoder.decode_all(record)[-1])
    assert bridge.world.query.field_resolution('class_id', 13.).state == 'UNKNOWN'


@pytest.mark.parametrize('value', [True, -1, 256, None])
def test_invalid_numeric_profile_enum_is_rejected(value):
    decoder, record = profile_event()
    event = decoder.decode_all(record)[-1].to_dict()
    event['payload']['class_id'] = value
    with pytest.raises(ValueError): normalize_event(event)


def test_profile_fields_need_their_own_reviewed_layout():
    decoder, record = profile_event()
    event = decoder.decode_all(record)[-1].to_dict()
    event['provenance']['payload_layout'] = 'WPP_12_1_OWN_UNIT_REVIEWED_V2'
    assert not verified_semantics(normalize_event(event))


def test_resource_and_actual_class_change_the_profile_revision_without_guessing_names():
    base = {'class':'WARRIOR', 'player_class_id':0, 'class_id':1, 'power_type':1}
    first = CharacterProfile.from_state(base)
    assert first.class_id == 1
    assert first.revision != CharacterProfile.from_state({**base, 'power_type':0}).revision


def test_profile_mailbox_coalesces_matching_fields_without_losing_create_or_partial_delta(bridge):
    setup(bridge)
    descriptor = json.loads(bridge.path.read_text())
    decoder, record = own_event()
    created = next(e for e in decoder.decode_all(replace(record,payload=create_payload()))
                   if e.event_type=='OWN_PROFILE_UPDATE')
    assert bridge.inbox.ingest_datagram(canonical(envelope(created.to_dict(), descriptor)))
    def enqueue(event, fields):
        # Event IDs identify content: modifying a dataclass payload without
        # rebuilding its ID would correctly trip inbox replay rejection.
        base = {k:event.payload[k] for k in ('mover_guid', 'world_map_id', 'sample_kind')}
        partial = AgentPacketEvent.create(pid=event.selected_pid, flow_id=event.flow_id,
            direction=event.direction, event_type=event.event_type, timestamp=event.timestamp,
            semantic_status=event.semantic_status, opcode=event.opcode,
            payload={**base, **fields}, provenance=event.provenance)
        assert bridge.inbox.ingest_datagram(canonical(envelope(partial.to_dict(), descriptor)))
    for level in range(70, 80):
        decoder, record = profile_event()
        event = decoder.decode_all(record)[-1]
        enqueue(event, {'level':level})
    decoder, record = profile_event()
    event = decoder.decode_all(record)[-1]
    enqueue(event, {'class_id':11})
    rows = bridge.inbox.poll()
    assert len(rows) == 3
    assert len([r for r in rows if r['payload']['sample_kind'] == 'CREATE']) == 1
    assert [r['payload']['level'] for r in rows if r['payload'].get('sample_kind') == 'VALUES'
            and 'level' in r['payload']] == [79]
    assert any(r['payload'].get('class_id') == 11 and 'level' not in r['payload'] for r in rows)
