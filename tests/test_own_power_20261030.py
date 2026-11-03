"""Build-specific own power packets, verified display units and resource isolation."""
from dataclasses import replace
import json
import struct

import pytest

from wowbot.agent.models import Observation
from wowbot.character_resources import display_power, resource_reference
from wowbot.packetio.builds import opcode_family
from wowbot.packetio.ipc import canonical, envelope
from wowbot.packetio.opcodes_12_1 import FAMILY_OPCODES
from wowbot.packetio.pkt import PktRecord
from wowbot.packetio.validation import normalize_event, verified_semantics
from wowbot.skills.ability_rules import AbilityRuleEngine
from test_packet_agent_bridge import addon, bridge, deliver
from test_packet_codecs import packed_guid, decoded
from test_session_bootstrap_20261029 import session_events


def power_events(values=((1, 750),), *, build=70575, low=0x1234, verified=True, tail=b''):
    decoder, world = session_events(build=build)
    decoder.capture_epoch = 'e'*32  # one synthetic producer, not a restart per sample
    if verified: decoder.decode_all(world)
    body = packed_guid(low=low)+struct.pack('<i', len(values))
    body += b''.join(struct.pack('<Bi', kind, raw) for kind, raw in values)+tail
    record = PktRecord(2, 'SERVER_TO_CLIENT', world.connection_index, 3, 1000.,
                       FAMILY_OPCODES[opcode_family(build).defining_build]['SMSG_POWER_UPDATE'], body, b'', 0)
    return decoder, record


@pytest.mark.parametrize('build,opcode', [(69587, 0x45017E), (70448, 0x45017D), (70575, 0x45017D)])
def test_exact_build_family_exports_own_power_type_before_raw_value(build, opcode):
    decoder, record = power_events(build=build)
    event = decoder.decode_all(record)[-1]
    assert event.opcode == opcode and event.event_type == 'OWN_POWER_UPDATE'
    assert event.payload['power_type'] == 1 and event.payload['raw_power'] == 750
    assert verified_semantics(normalize_event(event.to_dict()))


@pytest.mark.parametrize('options', [{'low': 0x9999}, {'verified': False}, {'tail': b'extra'}])
def test_no_other_player_intent_only_or_unreviewed_tail_becomes_own_power(options):
    decoder, record = power_events(**options)
    assert len(decoder.decode_all(record)) == 1


def test_wrong_direction_truncated_count_and_duplicate_conflict_fail_closed():
    decoder, record = power_events()
    assert len(decoder.decode_all(replace(record, direction='CLIENT_TO_SERVER'))) == 1
    assert len(decoder.decode_all(replace(record, payload=record.payload[:-1]))) == 1
    decoder, record = power_events(((1, 100), (1, 200)))
    assert len(decoder.decode_all(record)) == 1


@pytest.mark.parametrize('kind,raw,expected', [(0, 1500, 1500), (1, 750, 75), (3, 75, 75),
                                             (6, 500, 50), (7, 30, 3), (13, 7500, 75)])
def test_resource_units_come_from_decoded_db2_not_a_global_divisor(kind, raw, expected):
    profile = resource_reference(kind)
    assert display_power(raw, profile) == expected
    assert len(profile['source_sha256']) == 64 and not profile['live_build_verified']


def setup_power(bridge, *, kind=1, value=7, maximum=150):
    bridge.world.ingest(Observation.create(addon(game_build='70575', power_type=kind,
        power=value, max_power=maximum, power_sample_time=9.), 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)


def test_power_reaches_combat_in_display_units_without_inventing_current_maximum(bridge):
    setup_power(bridge)
    decoder, record = power_events()
    deliver(bridge, decoder.decode_all(record)[-1])
    assert bridge.world.state['power'] == 75
    assert bridge.world.state['max_power'] == 150  # not static MaxBasePower=1000
    assert bridge.world.last_received == 9.1
    action = {'id': 123, 'kind': 'spell', 'action': '1', 'is_usable': True,
              'cooldown_remaining': 0., 'resource_cost': 80}
    engine = AbilityRuleEngine()
    ability = engine.definition(action)
    assert engine.runtime_state(action, bridge.world.state, ability).resource_available_belief == 0.


def test_secondary_resource_never_overwrites_primary_and_type_change_does_not_mix_values(bridge):
    setup_power(bridge)
    decoder, record = power_events(((1, 750), (0, 42)))
    for event in decoder.decode_all(record)[1:]: deliver(bridge, event)
    assert bridge.world.state['power'] == 75
    assert set(bridge.world.state['packet_own_resources']['values']) == {'0', '1'}
    bridge.world.ingest(Observation.create(addon(game_build='70575', frame_id='mana-mode',
        monotonic_time=11., power_type=0, power=20, max_power=100, power_sample_time=9.5), 11.))
    assert bridge.world.state['power'] == 42  # latest mana, never latest rage


def test_new_fast_value_wins_without_waiting_for_another_tick(bridge):
    setup_power(bridge)
    decoder, record = power_events()
    deliver(bridge, decoder.decode_all(record)[-1])
    bridge.world.ingest(Observation.create({'session_id': 'live-s', 'frame_id': 'power-fast',
        'transport_kind': 'FAST', 'monotonic_time': 11., 'power_sample_time': 11.,
        'power_type': 1, 'power': 80, 'max_power': 150}, 11.))
    assert bridge.world.state['power'] == 80


def test_unknown_conversion_keeps_raw_evidence_without_guessing_a_display_value(bridge):
    setup_power(bridge, kind=255, value=9)
    decoder, record = power_events(((255, 700),))
    deliver(bridge, decoder.decode_all(record)[-1])
    assert bridge.world.state['power'] == 9
    assert bridge.world.state['packet_own_resources']['values']['255']['value'] is None
    assert resource_reference(255) is None


def test_state_flood_coalesces_each_resource_and_preserves_discrete_events(bridge):
    setup_power(bridge)
    descriptor = json.loads(bridge.path.read_text())
    for amount in range(40):
        decoder, record = power_events(((1, amount*10), (0, amount)))
        for event in decoder.decode_all(record)[1:]:
            assert bridge.inbox.ingest_datagram(canonical(envelope(event.to_dict(), descriptor)))
    discrete = decoded('SMSG_QUEST_UPDATE_COMPLETE', struct.pack('<I', 55639)+b'\x80', build=70575)[-1]
    assert bridge.inbox.ingest_datagram(canonical(envelope(discrete.to_dict(), descriptor)))
    events = bridge.inbox.poll()
    assert len(events) == 3 and any(e['event_type'] == 'QUEST_COMPLETED' for e in events)
    assert sorted(e['payload']['raw_power'] for e in events if e['event_type'] == 'OWN_POWER_UPDATE') == [39, 390]
    assert bridge.inbox.peek_movement() == []


def test_health_coalescing_preserves_the_create_baseline_and_partial_field_groups(bridge):
    from test_own_baseline_20261030 import create_payload
    from test_own_health_packets_20261030 import own_event
    setup_power(bridge)
    descriptor = json.loads(bridge.path.read_text())
    decoder, record = own_event()
    created = decoder.decode_all(replace(record, payload=create_payload()))[-1]
    assert bridge.inbox.ingest_datagram(canonical(envelope(created.to_dict(), descriptor)))
    for value in range(30):
        decoder, record = own_event(health=value)
        delta = decoder.decode_all(record)[-1]
        assert bridge.inbox.ingest_datagram(canonical(envelope(delta.to_dict(), descriptor)))
    queued = bridge.inbox.poll()
    assert len(queued) == 2
    assert queued[0]['payload']['sample_kind'] == 'CREATE'
    assert queued[1]['payload']['health'] == 29


def test_resource_reference_returns_owned_values_and_rejects_missing_or_corrupt_scale(tmp_path):
    row = resource_reference(1)
    row['display_modifier'] = 1
    assert resource_reference(1)['display_modifier'] == 10
    missing = tmp_path/'missing.json'
    assert resource_reference(1, missing) is None
    broken = tmp_path/'broken.json'
    broken.write_text('{"schema":"aipc.power-reference.v1","rows":[]}', encoding='utf-8')
    assert resource_reference(1, broken) is None
    array = tmp_path/'array.json'
    array.write_text('[]', encoding='utf-8')
    assert resource_reference(1, array) is None


@pytest.mark.parametrize('changes', [{'power_type': True}, {'power_type': 256}, {'raw_power': None},
                                   {'raw_power': True}, {'raw_power': 2**32}])
def test_malformed_power_never_enters_own_state(changes):
    decoder, record = power_events()
    event = decoder.decode_all(record)[-1].to_dict()
    event['payload'].update(changes)
    with pytest.raises(ValueError): normalize_event(event)
