"""Own UnitData requires a correlated login; other players stay excluded."""
import struct

import pytest

from wowbot.agent.models import Observation
from wowbot.packetio.pkt import PktRecord, _decode_update_object
from wowbot.packetio.opcodes_12_1 import FAMILY_OPCODES
from wowbot.packetio.validation import normalize_event, verified_semantics
from test_packet_agent_bridge import addon, bridge, deliver
from test_packet_codecs import packed_guid
from test_session_bootstrap_20261029 import session_events
from test_unit_fields_20261027 import bits


RAW_ME = f'{(2<<58)|(1602<<42):016X}{0x1234:016X}'


def own_payload(*, low=0x1234, health=40, maximum=100, map_id=2175):
    mask = 1 | (1 << 6) | (1 << 7)  # block 32, Health 38, MaxHealth 39
    fields = bytes((0, 0, 3))+struct.pack('<I', 0x20)+bits([(2, 8), (mask, 32)])+struct.pack('<qq', health, maximum)
    block = bytes((0,))+packed_guid(low=low)+struct.pack('<I', len(fields))+fields
    return struct.pack('<HI', map_id, 1)+bytes((0,))+struct.pack('<I', len(block))+block


def own_event(**changes):
    decoder, verify = session_events(build=70575)
    decoder.capture_epoch = 'e'*32  # coherent stream across own-state fixture calls
    decoder.decode_all(verify)
    decoder.entity_fragments[RAW_ME] = (3,)
    record = PktRecord(2, 'SERVER_TO_CLIENT', verify.connection_index, 3, 1000.,
                       FAMILY_OPCODES[70340]['SMSG_UPDATE_OBJECT'], own_payload(**changes), b'', 0)
    return decoder, record


def test_known_unit_mask_only_exports_selected_own_health_not_private_player_fields():
    data = own_payload()
    assert _decode_update_object(data, {RAW_ME: (3,)}) == []
    assert _decode_update_object(data, {RAW_ME: (3,)}, own_character_guid='Player-1602-99999999') == []
    rows = _decode_update_object(data, {RAW_ME: (3,)}, own_character_guid='Player-1602-00001234')
    assert rows == [('OWN_UNIT_UPDATE', {'mover_guid': RAW_ME, 'world_map_id': 2175,
                                       'sample_kind': 'VALUES', 'health': 40, 'max_health': 100})]


def test_decoder_requires_server_verified_login_not_just_intent_and_known_fragments():
    decoder, record = own_event()
    event = decoder.decode_all(record)[-1]
    assert event.event_type == 'OWN_UNIT_UPDATE'
    assert verified_semantics(normalize_event(event.to_dict()))
    assert event.provenance['payload_layout'] == 'WPP_12_1_OWN_UNIT_REVIEWED_V2'
    decoder._verified_player_guids.clear()
    assert len(decoder.decode_all(record)) == 1


def test_own_identity_without_known_fragment_layout_does_not_guess_offsets():
    decoder, record = own_event()
    decoder.entity_fragments.clear()
    assert len(decoder.decode_all(record)) == 1


def test_packet_hp_and_newer_fast_hp_share_field_policy_without_input_liveness(bridge):
    bridge.world.ingest(Observation.create(addon(game_build='70575', health=100, max_health=100), 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)
    decoder, record = own_event()
    deliver(bridge, decoder.decode_all(record)[-1])
    assert bridge.world.state['health'] == 40 and bridge.world.state['max_health'] == 100
    assert bridge.world.last_received == 9.1
    assert bridge.world.state['packet_own_health']['coverage'] == 'PARTIAL'
    bridge.world.ingest(Observation.create({'session_id': 'live-s', 'frame_id': 'health-fast-11',
        'monotonic_time': 11., 'transport_kind': 'FAST', 'health': 80, 'max_health': 100}, 11.))
    assert bridge.world.state['health'] == 80
    assert bridge.world.query.field_resolution('health', 11.).diagnostic()['authority'] == 'ADDON_STATE'


def test_wrong_player_or_map_cannot_replace_own_hp(bridge):
    bridge.world.ingest(Observation.create(addon(game_build='70575', health=100, max_health=100), 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)
    decoder, record = own_event(map_id=1)
    deliver(bridge, decoder.decode_all(record)[-1])
    assert bridge.world.state['health'] == 100
    decoder, record = own_event(low=0x9999)
    decoder.entity_fragments[f'{(2<<58)|(1602<<42):016X}{0x9999:016X}'] = (3,)
    assert len(decoder.decode_all(record)) == 1


def test_delayed_full_health_keeps_source_age_and_does_not_overwrite_newer_packet(bridge):
    bridge.world.ingest(Observation.create(addon(game_build='70575', health=100, max_health=100), 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)
    decoder, record = own_event()
    deliver(bridge, decoder.decode_all(record)[-1])
    bridge.world.ingest(Observation.create(addon(game_build='70575', frame_id='old-full',
        monotonic_time=11., health=70, max_health=100, health_sample_time=9.), 11.))
    assert bridge.world.state['health'] == 40
    assert bridge.world.evidence['health'][-1].observed_at == 9.


def test_assembler_preserves_health_origin_for_full_and_bounded_fast():
    from adapters.telemetry_packets import normalize, _complete_fast_sample
    full = normalize({'monotonic_time': 1009., 'health': 70})
    fast = {'monotonic_time': 1011., 'health': 80}
    _complete_fast_sample(fast)
    assert full['health_sample_time'] == 1009. and fast['health_sample_time'] == 1011.


def test_field_age_override_cannot_rejuvenate_declared_origin_or_repair_future_time():
    from wowbot.agent.world import WorldModel
    model = WorldModel()
    obs = Observation.create({'session_id': 's', 'provenance': {'observed_at_monotonic': 9.}}, 11.)
    model.add_evidence('health', 40, obs, observed_at=10.)
    assert model.evidence['health'][-1].observed_at == 9.
    future = Observation.create({'session_id': 's', 'frame_id': 'future',
                                 'provenance': {'observed_at_monotonic': 9.}}, 11.)
    model.add_evidence('health', 40, future, observed_at=12.)
    assert not model.evidence['health'][-1].is_fresh(11.)


@pytest.mark.parametrize('changes', [{'health': None}, {'max_health': None}, {'health': True},
                                   {'health': 101}, {'max_health': 0}])
def test_invalid_own_health_is_not_an_authoritative_delta(changes):
    decoder, record = own_event()
    event = decoder.decode_all(record)[-1].to_dict()
    event['payload'].update(changes)
    with pytest.raises(ValueError): normalize_event(event)
