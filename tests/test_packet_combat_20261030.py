"""Reviewed NPC cast fields, no input or guessed interrupt authority."""
from dataclasses import replace
import struct

import pytest

from wowbot.agent.models import Observation
from wowbot.agent.packet_combat import remember
from wowbot.combat_contracts import CastReference, CombatArbitrator
from wowbot.packetio.context import addon_entity_guid, addon_context
from wowbot.packetio.pkt import OpcodeManifest, PktEventDecoder, PktV31StreamParser
from wowbot.packetio.validation import normalize_event, verified_semantics
from test_packet_agent_bridge import addon, bridge, deliver
from test_packet_codecs import packed_guid, pkt_bytes, decoded


NPC_HIGH = (8 << 58) | (2175 << 29) | (1234 << 6)
NPC_LOW = 0xABC
RAW_NPC = f'{NPC_HIGH:016X}{NPC_LOW:016X}'
NPC = addon_entity_guid(RAW_NPC)
CAST_HIGH = 30 << 58


def unit():
    return packed_guid(high=NPC_HIGH, low=NPC_LOW)


def cast(number=1):
    return packed_guid(high=CAST_HIGH, low=number)


def body(name='SMSG_SPELL_START', *, cast_number=1, time=3000):
    if name in {'SMSG_SPELL_START', 'SMSG_SPELL_GO'}:
        return unit()+unit()+cast(cast_number)+packed_guid(high=0, low=0)+struct.pack('<IiiIIII', 9876, 0, 0, 1, 2, 3, time)
    if name == 'SMSG_SPELL_INTERRUPT_LOG':
        return packed_guid()+unit()+struct.pack('<IIB', 6552, 9876, 0)
    return unit()+cast(cast_number)+struct.pack('<Iii', 9876, 0, 0)+(
        struct.pack('<h', 23) if name == 'SMSG_SPELL_FAILURE' else bytes((23,)))+packed_guid(high=0, low=0)


@pytest.mark.parametrize('build', [69587, 70448, 70575])
@pytest.mark.parametrize('name,kind', [('SMSG_SPELL_START', 'SPELL_CAST_STARTED'),
    ('SMSG_SPELL_GO', 'SPELL_CAST_RELEASED'), ('SMSG_SPELL_FAILURE', 'SPELL_CAST_RESULT'),
    ('SMSG_SPELL_FAILED_OTHER', 'SPELL_CAST_RESULT'), ('SMSG_SPELL_INTERRUPT_LOG', 'SPELL_INTERRUPT_OBSERVED')])
def test_exact_reviewed_opcode_family_exports_only_cast_facts(build, name, kind):
    event = decoded(name, body(name), build=build)[-1]
    safe = normalize_event(event.to_dict())
    assert event.event_type == kind and verified_semantics(safe)
    assert safe['payload']['caster_guid'] == RAW_NPC and safe['payload']['spell_id'] == 9876
    assert safe['provenance']['payload_layout'] == 'WPP_12_1_SPELL_REVIEWED_V1'
    assert not {'interruptible', 'raw_payload', 'name', 'interruptor_guid'} & safe['payload'].keys()
    if name == 'SMSG_SPELL_INTERRUPT_LOG':
        assert 'cast_id' not in safe['payload']


def test_start_duration_and_release_server_clock_are_not_interchangeable():
    start = decoded('SMSG_SPELL_START', body())[-1].payload
    release = decoded('SMSG_SPELL_GO', body('SMSG_SPELL_GO', time=2**32-1))[-1].payload
    assert start['cast_time_ms'] == 3000 and 'server_cast_time_ms' not in start
    assert release['server_cast_time_ms'] == 2**32-1 and 'cast_time_ms' not in release


@pytest.mark.parametrize('name', ['SMSG_SPELL_FAILURE', 'SMSG_SPELL_FAILED_OTHER', 'SMSG_SPELL_INTERRUPT_LOG'])
def test_exact_record_codecs_reject_truncated_or_unknown_trailing_bytes(name):
    for data in (body(name)[:-1], body(name)+b'private-tail'):
        assert len(decoded(name, data)) == 1


def test_prefix_codec_rejects_every_truncated_prefix_and_does_not_export_unknown_tail():
    complete = body()
    assert all(len(decoded('SMSG_SPELL_START', complete[:i])) == 1 for i in range(len(complete)))
    event = decoded('SMSG_SPELL_START', complete+b'not-forwarded').pop()
    assert 'not-forwarded' not in str(event.payload)


def test_client_direction_and_player_caster_do_not_produce_npc_casts():
    parser = PktV31StreamParser()
    record = parser.feed(pkt_bytes('SMSG_SPELL_START', body()))[0]
    decoder = PktEventDecoder(selected_pid=77, header=parser.header, manifest=OpcodeManifest.reviewed(69587))
    assert len(decoder.decode_all(replace(record, direction='CLIENT_TO_SERVER'))) == 1
    player_body = packed_guid()+packed_guid()+cast()+packed_guid(high=0, low=0)+struct.pack('<IiiIIII', 9876, 0, 0, 1, 2, 3, 3000)
    assert len(decoded('SMSG_SPELL_START', player_body)) == 1


def test_signed_packet_cast_reaches_only_the_selected_exact_npc_without_refreshing_addon(bridge):
    bridge.world.ingest(Observation.create(addon(frame_id='npc', target={'guid': NPC, 'npc_id': 1234}), 9.1))
    deliver(bridge, decoded('SMSG_SPELL_START', body())[-1])
    observed = bridge.world.state['target']['cast']
    assert observed['caster_guid'] == NPC and observed['spell_id'] == 9876
    assert observed['ends_at'] == 13. and observed['observed_at'] == 10.
    assert bridge.world.last_received == 9.1
    assert CastReference.from_state(bridge.world.state, 10.) is None  # interruptibility unknown
    deliver(bridge, decoded('SMSG_SPELL_GO', body('SMSG_SPELL_GO'))[-1])
    assert 'cast' not in bridge.world.state['target']


def test_late_result_for_old_cast_cannot_end_new_cast_and_map_change_clears_it(bridge):
    context = addon_context(addon(), 77)
    remember(bridge.world, 'SPELL_CAST_STARTED', decoded('SMSG_SPELL_START', body(cast_number=2))[-1].payload, 11., context)
    remember(bridge.world, 'SPELL_CAST_RESULT', decoded('SMSG_SPELL_FAILURE', body('SMSG_SPELL_FAILURE'))[-1].payload, 12., context)
    assert bridge.world.__dict__['_packet_casts'][NPC]['cast_id'].endswith('0002')
    remember(bridge.world, 'MAP_CHANGED', {}, 13., context)
    assert bridge.world.__dict__['_packet_casts'] == {}


def test_interrupt_log_cannot_invent_exact_cast_success():
    event = decoded('SMSG_SPELL_INTERRUPT_LOG', body('SMSG_SPELL_INTERRUPT_LOG'))[-1]
    reference = CastReference(NPC, 'cast-unknown-to-log', 9876, 10., 13., 10., True)
    assert CombatArbitrator.verify_interrupt(reference, [event.to_dict()]) is None


@pytest.mark.parametrize('change', [{'caster_guid': None}, {'cast_id': None}, {'spell_id': True},
                                    {'cast_time_ms': float('nan')}, {'cast_time_ms': -1}])
def test_malformed_semantic_cast_data_never_becomes_authority(change):
    event = decoded('SMSG_SPELL_START', body())[-1].to_dict()
    event['payload'].update(change)
    with pytest.raises(ValueError):
        normalize_event(event)
