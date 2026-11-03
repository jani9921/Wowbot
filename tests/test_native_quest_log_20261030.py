"""Actual own PlayerData slot masks; membership is not a reward receipt."""
from dataclasses import replace
import struct

import pytest

from wowbot.agent.models import Observation
from wowbot.packetio.ipc import canonical, envelope
from wowbot.packetio.validation import normalize_event, verified_semantics
from wowbot.packetio.player_quest_log import SLOT_COUNT, normalize_slots
from test_own_health_packets_20261030 import RAW_ME, own_event
from test_packet_agent_bridge import addon, bridge, deliver
from test_packet_codecs import packed_guid
from test_unit_fields_20261027 import bits


def slot(index, quest=55639, progress=None):
    return [index, quest, 0, 0, 0, 0, progress if progress is not None else [0]*24]


def player_data(rows, *, full=True, extra_bits=(), prefix=b''):
    changed = {53, *(54+r[0] for r in rows), *extra_bits}
    words = [sum(1 << (i % 32) for i in changed if i//32 == j) for j in range(11)]
    present = sum(1 << j for j,w in enumerate(words) if w)
    data = bits([(present, 11), *((w, 32) for w in words if w), (int(full), 1)])+prefix
    for row in sorted(rows, key=lambda r:r[0]):
        if full:
            data += struct.pack('<iH24hqII', row[1], row[2], *row[6], row[3], row[4], row[5])
        else:
            changed_fields = [i for i,v in enumerate(row[1:6], 1) if v is not None]
            mask = (1 if changed_fields else 0) | sum(1 << i for i in changed_fields)
            counters = [i for i,v in enumerate(row[6]) if v is not None]
            if counters: mask |= (1 << 6) | sum(1 << (7+i) for i in counters)
            data += bits([(1,1),(mask,32)])
            for i, format in enumerate(('i','H','q','I','I'), 1):
                if row[i] is not None: data += struct.pack('<'+format, row[i])
            for i in counters: data += struct.pack('<h', row[6][i])
    return data


def quest_event(rows=None, *, full=True, extra_bits=(), unit_tail=False, low=0x1234, at=10., private_prefix=b''):
    rows = [slot(3)] if rows is None else rows
    decoder, record = own_event()
    prefix = b''
    if unit_tail:
        mask = 1 | (1 << 6) | (1 << 24)  # health plus unsupported field 56
        prefix = bits([(2,8),(mask,32)])+struct.pack('<q', 80)+b'unknown'
    fields = bytes((0,0,3))+struct.pack('<I', 0x60 if unit_tail else 0x40)+prefix
    fields += player_data(rows, full=full, extra_bits=extra_bits, prefix=private_prefix)
    block = bytes((0,))+packed_guid(low=low)+struct.pack('<I', len(fields))+fields
    body = struct.pack('<HI',2175,1)+bytes((0,))+struct.pack('<I',len(block))+block
    return decoder, replace(record,payload=body,timestamp=1000.+at-10.)


def setup(bridge):
    bridge.world.ingest(Observation.create(addon(game_build='70575'),9.1))
    bridge.adapter.observations(None,bridge.world,10.)


def send(bridge, rows=None, *, at=10., **options):
    bridge.inbox._clock = lambda: at
    bridge.inbox._wall_clock = lambda: 1000.+at-10.
    decoder, record = quest_event(rows,at=at,**options)
    event = decoder.decode_all(record)[-1]
    assert event.event_type == 'OWN_QUEST_LOG_UPDATE'
    deliver(bridge,event,at=at)
    return event


def test_full_175_slot_update_round_trips_through_build_specific_decoder_and_schema():
    rows = [slot(i,55639 if i == 3 else 0) for i in range(SLOT_COUNT)]
    decoder, record = quest_event(rows)
    event = decoder.decode_all(record)[-1]
    assert event.event_type == 'OWN_QUEST_LOG_UPDATE' and event.payload['slots'] == rows
    assert verified_semantics(normalize_event(event.to_dict()))
    assert event.provenance['payload_layout'] == 'WPP_12_1_QUEST_LOG_REVIEWED_V1'


def test_partial_slot_presence_never_proves_other_quest_absent_or_completion(bridge):
    setup(bridge)
    send(bridge,[slot(3,progress=[2]*24)])
    assert bridge.world.query.quest_presence(55639,10.)['state'] == 'PRESENT'
    assert bridge.world.query.quest_presence(88719,10.)['state'] == 'UNKNOWN'
    assert bridge.world.quest_model.records[55639].current_state == 'ACTIVE'
    assert not any(e.event_type in {'QUEST_TURNED_IN','QUEST_ACCEPTED','QUEST_COMPLETED'} for e in bridge.world.event_records)
    assert bridge.world.last_received == 9.1


def test_complete_native_membership_has_owned_query_without_replacing_quest_definitions(bridge):
    setup(bridge)
    send(bridge,[slot(i,55639 if i == 3 else 0) for i in range(SLOT_COUNT)])
    assert bridge.world.query.quest_presence(88719,10.)['state'] == 'ABSENT'
    assert bridge.world.state['packet_quest_log']['membership'] == 'COMPLETE'
    assert bridge.world.state['packet_quest_log']['definitions'] == 'UNKNOWN'
    assert 'slots' not in bridge.world.state['packet_quest_log']
    result = bridge.world.query.quest_log_slots(10.,quest_id=55639)
    assert len(result['slots']) == 1
    result['slots'][0]['fields']['quest_id']['value'] = 88719
    assert bridge.world.query.quest_presence(55639,10.)['state'] == 'PRESENT'


def test_counter_delta_preserves_original_identity_clock_and_cannot_use_ui_ordinal(bridge):
    setup(bridge)
    send(bridge)
    progress = [None]*24
    progress[9] = 4
    send(bridge,[[3,None,None,None,None,None,progress]],full=False,at=10.1)
    value = bridge.world.query.quest_log_slots(10.1,quest_id=55639)['slots'][0]
    assert value['fields']['quest_id']['observed_at'] == 10.
    assert value['progress']['9']['value'] == 4 and value['progress']['9']['observed_at'] == 10.1
    assert value['progress']['8']['observed_at'] == 10.
    assert bridge.world.quest_model.records[55639].objectives[0].current_count == 0


def test_new_quest_in_same_slot_cannot_inherit_old_progress(bridge):
    setup(bridge)
    send(bridge,[slot(3,progress=[5]*24)])
    send(bridge,[[3,88719,None,None,None,None,[None]*24]],full=False,at=10.1)
    result = bridge.world.query.quest_log_slots(10.1,quest_id=88719)
    assert result['slots'][0]['progress'] == {}
    assert bridge.world.query.quest_presence(55639,10.1)['state'] == 'UNKNOWN'


def test_zero_slot_and_older_reordered_delta_do_not_restore_removed_identity(bridge):
    setup(bridge)
    send(bridge)
    send(bridge,[[3,0,None,None,None,None,[None]*24]],full=False,at=10.1)
    send(bridge,[slot(3)],at=9.9)
    assert bridge.world.query.quest_presence(55639,10.1)['state'] == 'UNKNOWN'
    assert bridge.world.query.quest_log_slots(10.1)['slots'][0]['fields']['quest_id']['value'] == 0


@pytest.mark.parametrize('change',[{'loading':True},{'phase':'elsewhere'},{'character_guid':'Player-1602-99999999'}])
def test_slot_baseline_does_not_cross_loading_phase_or_identity(bridge,change):
    setup(bridge)
    send(bridge)
    bridge.world.ingest(Observation.create(addon(game_build='70575',frame_id='next',**change),10.1))
    assert bridge.world.query.quest_presence(55639,10.1)['state'] == 'UNKNOWN'
    assert 'packet_quest_log' not in bridge.world.state


def test_native_membership_expires_without_rejuvenating_slot_ids(bridge):
    setup(bridge)
    send(bridge,[slot(i,55639 if i == 3 else 0) for i in range(SLOT_COUNT)])
    assert bridge.world.query.quest_presence(55639,13.)['state'] == 'UNKNOWN'
    assert bridge.world.query.quest_presence(88719,13.)['state'] == 'UNKNOWN'


def test_unknown_unit_tail_or_player_prefix_never_guesses_quest_offsets():
    decoder,record = quest_event(unit_tail=True)
    assert not any(e.event_type == 'OWN_QUEST_LOG_UPDATE' for e in decoder.decode_all(record))
    for extra in ((0,3),(0,25),(32,36),(32,47)):
        decoder,record = quest_event(extra_bits=extra)
        values = decoder.decode_all(record)
        assert [e.event_type for e in values] == ['PACKET_OPCODE_OBSERVED','OWN_QUEST_LOG_INVALIDATED']
        assert 'slots' not in values[-1].payload


def test_other_player_or_unverified_login_never_calls_private_quest_reader(monkeypatch):
    from wowbot.packetio import player_quest_log
    def forbidden(*args): pytest.fail('unselected player quest data read')
    monkeypatch.setattr(player_quest_log,'read_slots',forbidden)
    decoder,record = quest_event(low=0x9999)
    decoder.entity_fragments[f'{(2<<58)|(1602<<42):016X}{0x9999:016X}'] = (3,)
    assert len(decoder.decode_all(record)) == 1
    decoder,record = quest_event()
    decoder._verified_player_guids.clear()
    assert len(decoder.decode_all(record)) == 1


def test_truncated_slot_collection_is_not_partly_accepted():
    decoder,record = quest_event([slot(1),slot(2)])
    assert len(decoder.decode_all(replace(record,payload=record.payload[:-1]))) == 1


def test_preceding_account_and_guild_fields_are_skipped_and_never_exported():
    private_low, private_high = 0xDEADBEEF, 3 << 58
    prefix = packed_guid(private_low,private_high)*2+struct.pack('<Q',123456789)+packed_guid(private_low,private_high)
    decoder,record = quest_event(extra_bits=(0,10,11,12,13),private_prefix=prefix)
    event = decoder.decode_all(record)[-1]
    assert event.event_type == 'OWN_QUEST_LOG_UPDATE'
    assert set(event.payload) == {'mover_guid','world_map_id','slots'}
    assert event.payload['slots'] == [slot(3)]
    assert f'{private_high:016X}{private_low:016X}' not in str(event.to_dict())


@pytest.mark.parametrize('row',[
    [True,55639,0,0,0,0,[0]*24], [175,55639,0,0,0,0,[0]*24],
    [1,-1,0,0,0,0,[0]*24], [1,55639,0,0,0,0,[0]*23],
    [1,55639,0,0,0,0,[True]*24], [1,55639,0,0,0,0,[2**15]*24],
])
def test_invalid_slot_shapes_values_or_counters_fail_closed(row):
    with pytest.raises(ValueError): normalize_slots([row])


def test_duplicate_slots_rejected_and_maximum_compact_snapshot_fits_ipc(bridge):
    with pytest.raises(ValueError): normalize_slots([slot(1),slot(1)])
    setup(bridge)
    worst = [[i,2**31-1,2**16-1,2**63-1,2**32-1,2**32-1,[-2**15]*24] for i in range(SLOT_COUNT)]
    decoder,record = quest_event(worst)
    event = decoder.decode_all(record)[-1]
    import json
    descriptor = json.loads(bridge.path.read_text())
    assert len(canonical(envelope(event.to_dict(),descriptor))) < 60000
    assert bridge.inbox.ingest_datagram(canonical(envelope(event.to_dict(),descriptor)))
