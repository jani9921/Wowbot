"""Cold own CREATE produces numeric slots without account/player text export."""
from dataclasses import replace
import struct

import pytest

from wowbot.packetio.update_object import decode_update_object
from wowbot.packetio.validation import verified_semantics
from test_packet_agent_bridge import addon, bridge, deliver
from wowbot.agent.models import Observation
from test_packet_codecs import packed_guid
from test_unit_fields_20261027 import bits, unit_tail_bytes
from test_own_health_packets_20261030 import RAW_ME, own_event
from test_native_quest_log_20261030 import slot

PRIVATE=packed_guid(low=0xDEADBEEF,high=3<<58)


def remainder(flags, *, dynamic=True, assist=True):
    # Serialize each WPP field group, with nonzero landmarks around variable
    # bodies. The public fixture ends at CombatReach; this is its continuation.
    value=struct.pack('<fiBifii',1.,7,0,123,1.,456,789)
    if flags & 9:value+=struct.pack('<4f',1.,2.,3.,4.)
    value+=struct.pack('<4B4I',0,1,2,3,1234,1235,1236,1237)
    value+=struct.pack('<7f2i',1.,1.,1.,1.,1.,1.,1.,4321,10)
    if flags & 1:value+=struct.pack('<20i',*range(20))
    if flags & 9:value+=struct.pack('<7i',*range(7))
    if flags & 1:value+=struct.pack('<14i',*range(14))
    value+=struct.pack('<i',100)
    if flags & 1:value+=struct.pack('<i',500)
    value+=struct.pack('<4B',1,2,3,4)
    if flags & 1:value+=struct.pack('<18i',*range(18))
    value+=struct.pack('<2f14i',1.,2.,*range(100,114))+PRIVATE
    counts=(2,1,1) if dynamic else (0,0,0)
    value+=struct.pack('<3I',*counts)+struct.pack('<9i',*range(700,709))+PRIVATE
    if dynamic:value+=struct.pack('<4i',30,31,32,33)+struct.pack('<i',44)+PRIVATE
    value+=bits([(1,1),(int(assist),1)])
    if assist:
        text=b'PRIVATE_NAME_SENTINEL'
        value+=struct.pack('<BI',1,777)+bits([(len(text),6)])+text
    return value


def player_prefix(rows):
    value=PRIVATE*3+struct.pack('<Q',123456789)+PRIVATE
    value+=struct.pack('<5I',1,2,3,4,5)+struct.pack('<2I',3,2)
    value+=struct.pack('<6B2I',1,2,3,4,5,6,77,88)
    for row in rows:
        value+=struct.pack('<iH24hqII',row[1],row[2],*row[6],row[3],row[4],row[5])
    return value


def create_payload(rows=None, *, flags=3, low=0x1234, dynamic=True, assist=True, truncated=0, player_tail=b''):
    rows=[slot(i,55639 if i==3 else 0) for i in range(175)] if rows is None else rows
    movement=bits([(int(i in {4,7,16}),1) for i in range(21)])
    movement+=struct.pack('<IffffB',0,1.,2.,3.,0.,0)
    fields=bytes((flags,3,255,1))+struct.pack('<iIfiII',0,0,1.,0,0,0)
    prefix=unit_tail_bytes(health=40,max_health=100,owner=bool(flags&1),unit_all=bool(flags&4),
                           identity=bytes((1,1,1,0,0,1)))
    fields+=prefix+remainder(flags,dynamic=dynamic,assist=assist)+player_prefix(rows)+player_tail
    if truncated:fields=fields[:-truncated]
    block=bytes((2,))+packed_guid(low=low)+bytes((7,))+movement+struct.pack('<I',len(fields))+fields
    return struct.pack('<HI',2175,1)+b'\0'+struct.pack('<I',len(block))+block


@pytest.mark.parametrize('flags',[2,3,6,7,10,11,14,15])
@pytest.mark.parametrize('optional',[False,True])
def test_own_create_reaches_full_slot_baseline_across_conditional_unit_fields(flags,optional):
    rows=decode_update_object(create_payload(flags=flags,dynamic=optional,assist=optional),{},
                              own_character_guid='Player-1602-00001234')
    assert len(rows)==1 and len(rows[0]['quest_log_slots'])==175
    assert rows[0]['quest_log_slots'][3]==slot(3)
    assert 'PRIVATE_NAME_SENTINEL' not in str(rows)
    assert 'DEADBEEF' not in str(rows)


@pytest.mark.parametrize('cut',[1,70,175*70])
def test_incomplete_create_slots_do_not_become_partial_baseline(cut):
    decoder,record=own_event()
    events=decoder.decode_all(replace(record,payload=create_payload(truncated=cut)))
    assert not any(e.event_type=='OWN_QUEST_LOG_UPDATE' for e in events)
    assert any(e.event_type=='OWN_UNIT_UPDATE' for e in events)  # valid independent prefix remains


def test_only_selected_own_and_explicit_party_coverage_can_read_slot_prefix(monkeypatch):
    from wowbot.packetio import own_create_quest_log
    decoder,record=own_event()
    for flags in (0,1,0x83):
        events=decoder.decode_all(replace(record,payload=create_payload(flags=flags)))
        assert not any(e.event_type=='OWN_QUEST_LOG_UPDATE' for e in events)
    def forbidden(*args):pytest.fail('another player private prefix was read')
    monkeypatch.setattr(own_create_quest_log,'read_create_slots',forbidden)
    assert not any(e.event_type=='OWN_QUEST_LOG_UPDATE' for e in
        decoder.decode_all(replace(record,payload=create_payload(low=0x9999))))


def test_cold_create_baseline_reaches_same_canonical_slots_and_never_accepts_or_completes_quests(bridge):
    bridge.world.ingest(Observation.create(addon(game_build='70575'),9.1))
    bridge.adapter.observations(None,bridge.world,10.)
    decoder,record=own_event()
    event=next(e for e in decoder.decode_all(replace(record,payload=create_payload()))
               if e.event_type=='OWN_QUEST_LOG_UPDATE')
    assert verified_semantics(event.to_dict()) and event.payload['mover_guid']==RAW_ME
    assert set(event.payload)=={'mover_guid','world_map_id','slots','sample_kind'}
    assert event.payload['sample_kind']=='CREATE'
    assert event.provenance['payload_layout']=='WPP_12_1_QUEST_LOG_REVIEWED_V2'
    deliver(bridge,event)
    assert bridge.world.query.quest_presence(55639,10.)['state']=='PRESENT'
    assert bridge.world.query.quest_presence(99999,10.)['state']=='ABSENT'
    assert bridge.world.state['packet_quest_log']['membership']=='COMPLETE'
    assert bridge.world.state['packet_quest_log']['baseline_sample_kind']=='CREATE'
    assert bridge.world.quest_model.records[55639].current_state=='ACTIVE'
    assert not any(e.event_type in {'QUEST_ACCEPTED','QUEST_COMPLETED','QUEST_TURNED_IN'}
                   for e in bridge.world.event_records)
    assert bridge.world.last_received==9.1


def test_old_values_only_layout_cannot_assert_a_create_baseline():
    from wowbot.packetio.validation import normalize_event
    decoder,record=own_event()
    value=next(e for e in decoder.decode_all(replace(record,payload=create_payload()))
               if e.event_type=='OWN_QUEST_LOG_UPDATE').to_dict()
    value['provenance']['payload_layout']='WPP_12_1_QUEST_LOG_REVIEWED_V1'
    with pytest.raises(ValueError):normalize_event(value)


def test_partial_values_cannot_be_relabelled_as_full_create():
    from wowbot.packetio.validation import normalize_event
    decoder,record=own_event()
    value=next(e for e in decoder.decode_all(replace(record,payload=create_payload()))
               if e.event_type=='OWN_QUEST_LOG_UPDATE').to_dict()
    value['payload']['slots']=value['payload']['slots'][:1]
    with pytest.raises(ValueError):normalize_event(value)
