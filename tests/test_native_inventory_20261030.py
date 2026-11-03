"""Native owned inventory identity/counts; no bag-coordinate/input guessing."""
from dataclasses import replace
import struct

import pytest

from wowbot.packetio.validation import normalize_event,verified_semantics
from test_packet_agent_bridge import addon,bridge,deliver
from wowbot.agent.models import Observation
from test_unit_fields_20261027 import bits
from test_packet_codecs import packed_guid
from test_own_health_packets_20261030 import RAW_ME,own_event
from test_own_create_quest_log_20261030 import create_payload,PRIVATE

ZERO=bytes(2)
ITEM=f'{3<<58:016X}{123:016X}'
BAG=f'{3<<58:016X}{124:016X}'


def packed(raw):return packed_guid(low=int(raw[16:],16),high=int(raw[:16],16))


def full_player_tail(*, optional=True):
    # Prefix fixture has three ordinary + two random cosmetic choices.
    data=struct.pack('<IiiI',1,55639,3,1 if optional else 0)
    for _ in range(19):data+=struct.pack('<3i2Hi2B',1,2,3,4,5,6,7,8)+bits([(1,1),(0,1)])
    data+=struct.pack('<6i6fBiqI',1,2,3,4,5,6,*[1.]*6,0,10,12345,1 if optional else 0)
    data+=struct.pack('<64i3iI',*range(64),11,12,13,1 if optional else 0)
    data+=struct.pack('<IBI',1,2,3)+struct.pack('<I',77)  # CTROptions
    data+=struct.pack('<2i2fI',1,2,3.,4.,1 if optional else 0)
    if optional:data+=struct.pack('<ifiiB',1,2.,3,4,5)+bits([(1,1)])
    data+=PRIVATE+bytes(40)+bits([(1,1)])+PRIVATE+struct.pack('<i',0)
    for _ in range(16):
        data+=struct.pack('<i',123)+bits([(1,7)])+struct.pack('<Bi',3,17)
        data+=bits([(1,1)])+struct.pack('<BII',2,1,1234)
    data+=struct.pack('<I',1)+bytes(19*4+5*4+28)+PRIVATE+bytes(5*8)
    if optional:
        data+=bytes(70)+bytes(25)
        data+=struct.pack('<I',123)+bits([(3,8)])+b'pet'
    data+=struct.pack('<i',999)
    name=b'PRIVATE_PLAYER_SENTINEL'
    data+=bits([(len(name),6),(1,1),(0,1),(int(optional),1)])+name
    if optional:data+=bits([(3,10)]*5)+b'xyz'*5
    data+=b''.join(packed(ITEM) if i==23 else packed(BAG) if i==19 else ZERO for i in range(105))
    return data


def item_payload(*, low=123, owner=RAW_ME, container=RAW_ME, bag=False, qty=7, truncated=0):
    fields=bytes((1,3,255,1))+struct.pack('<iIf',12345 if not bag else 54321,0,1.)
    fields+=packed(owner)+packed(container)+PRIVATE*2+struct.pack('<II5iI',qty,1234,1,2,3,4,5,6)
    fields+=bytes(13*12)+struct.pack('<IIIBqQB',20,40,50,2,900,1000,3)
    fields+=bits([(1,7)])+struct.pack('<Bi',2,123)
    fields+=struct.pack('<IIiiII',1,1,7,12345,1,1)
    fields+=struct.pack('<iBiH',789,2,555,12)+bytes(4+37)
    if bag:
        fields+=b''.join(packed(ITEM) if i==0 else ZERO for i in range(98))+struct.pack('<I',16)
    if truncated:fields=fields[:-truncated]
    movement=bits([(0,1)]*21)+struct.pack('<I',0)  # unconditional pause-times count
    block=b'\2'+packed_guid(low=low,high=3<<58)+bytes((2 if bag else 1,))+movement
    block+=struct.pack('<I',len(fields))+fields
    return struct.pack('<HI',2175,1)+b'\0'+struct.pack('<I',len(block))+block


def events(payload, decoder=None, *, at=10.):
    if decoder is None:decoder,record=own_event()
    else:_,record=own_event()
    return decoder,decoder.decode_all(replace(record,payload=payload,timestamp=1000.+at-10.))


@pytest.mark.parametrize('optional',[False,True])
def test_roots_are_reached_after_exact_player_remainder_and_private_text_is_not_exported(optional):
    _,values=events(create_payload(player_tail=full_player_tail(optional=optional)))
    root=next(e for e in values if e.event_type=='OWN_INVENTORY_ROOTS')
    assert verified_semantics(normalize_event(root.to_dict()))
    assert root.payload['root_slots'][23]==[23,ITEM] and root.payload['root_slots'][19]==[19,BAG]
    assert 'PRIVATE_PLAYER_SENTINEL' not in str(root.to_dict()) and 'DEADBEEF' not in str(root.to_dict())
    assert all(e.event_type!='OWN_INVENTORY_INVALIDATED' for e in values)


@pytest.mark.parametrize('bag',[False,True])
def test_only_selected_owned_item_or_container_create_fields_are_normalized(bag):
    _,values=events(item_payload(low=124 if bag else 123,bag=bag))
    event=next(e for e in values if e.event_type=='OWN_ITEM_UPDATE')
    assert verified_semantics(normalize_event(event.to_dict()))
    assert event.payload['stack_count']==7 and event.payload['durability']==20
    assert event.payload['max_durability']==40 and event.payload['container_guid']==RAW_ME
    assert 'DEADBEEF' not in str(event.to_dict())
    if bag:assert event.payload['num_slots']==16 and event.payload['container_slots'][0]==[0,ITEM]


@pytest.mark.parametrize('payload',[item_payload(owner=f'{2<<58:016X}{999:016X}'),
                                 item_payload(truncated=1),item_payload(bag=True,truncated=1)])
def test_foreign_or_incomplete_inventory_prefixes_cannot_produce_owned_state(payload):
    _,values=events(payload)
    assert all(e.event_type!='OWN_ITEM_UPDATE' for e in values)


def test_unreviewed_item_delta_invalidates_previous_count_without_reading_private_fields():
    decoder,_=events(item_payload())
    body=b'\0'+packed(ITEM)+struct.pack('<I',1)+b'\xff'
    packet=struct.pack('<HI',2175,1)+b'\0'+struct.pack('<I',len(body))+body
    _,values=events(packet,decoder)
    removed=next(e for e in values if e.event_type=='OWN_ITEM_REMOVED')
    assert removed.payload['removal']=='UNREVIEWED_UPDATE'
    assert verified_semantics(normalize_event(removed.to_dict()))


def ready(bridge):
    bridge.world.ingest(Observation.create(addon(game_build='70575',inventory={'items':[{
        'item_id':12345,'bag':0,'slot':1,'count':99,'x':.2,'y':.4}], 'complete':True}),9.1))
    bridge.adapter.observations(None,bridge.world,10.)


def deliver_native(bridge,payload,*,decoder=None,at=10.):
    bridge.inbox._clock=lambda:at
    bridge.inbox._wall_clock=lambda:1000.+at-10.
    decoder,values=events(payload,decoder,at=at)
    for value in values:
        if value.event_type.startswith('OWN_'):
            deliver(bridge,value,at=at)
    return decoder


def test_owned_item_evidence_is_readonly_partial_and_never_overwrites_ui_or_quest_credit(bridge):
    ready(bridge)
    deliver_native(bridge,item_payload())
    result=bridge.world.query.owned_item_count(12345,10.)
    assert result['status']=='OBSERVED_LOWER_BOUND' and result['count']==7
    assert result['carried'] is None and result['complete'] is False
    assert bridge.world.state['inventory']['items'][0]['count']==99
    assert bridge.world.state['packet_inventory']['coverage']=='PARTIAL'
    assert bridge.world.last_received==9.1
    assert not any(e.event_type in {'QUEST_COMPLETED','LOOT_RECEIVED','QUEST_TURNED_IN'}
                   for e in bridge.world.event_records)
    rows=bridge.world.query.native_inventory(10.)
    rows['items'][0]['stack_count']=999
    assert bridge.world.query.owned_item_count(12345,10.)['count']==7
    assert bridge.world.query.owned_item_count(999,10.)['status']=='UNKNOWN'
    assert bridge.world.query.owned_item_count(12345,12.1)['status']=='UNKNOWN'


def test_unreviewed_delta_is_a_barrier_against_reordered_old_item_create(bridge):
    ready(bridge)
    decoder=deliver_native(bridge,item_payload())
    body=b'\0'+packed(ITEM)+struct.pack('<I',1)+b'\xff'
    packet=struct.pack('<HI',2175,1)+b'\0'+struct.pack('<I',len(body))+body
    deliver_native(bridge,packet,decoder=decoder,at=10.2)
    assert bridge.world.query.owned_item_count(12345,10.2)['status']=='UNKNOWN'
    deliver_native(bridge,item_payload(qty=5),at=10.1)
    assert bridge.world.query.owned_item_count(12345,10.2)['status']=='UNKNOWN'
    deliver_native(bridge,item_payload(qty=8),at=10.3)
    assert bridge.world.query.owned_item_count(12345,10.3)['count']==8


def test_roots_are_complete_native_membership_and_never_client_coordinates(bridge):
    ready(bridge)
    deliver_native(bridge,create_payload(player_tail=full_player_tail()))
    state=bridge.world.query.native_inventory(10.)
    assert state['root_membership']=='COMPLETE' and state['coverage']=='PARTIAL'
    assert state['root_slots'][23]==[23,ITEM] and state['root_sample_time']==10.
    assert state['items']==[] and 'x' not in str(state['root_slots'])
    assert 'root_slots' not in bridge.world.state['packet_inventory']  # hot status stays compact
    assert bridge.world.state['inventory']['items'][0]['bag']==0


@pytest.mark.parametrize('change',[{'loading':True},{'phase':'other'},{'character_guid':'Player-1602-9999'}])
def test_native_items_do_not_cross_loading_phase_or_identity(bridge,change):
    ready(bridge);deliver_native(bridge,item_payload())
    bridge.world.ingest(Observation.create({**bridge.world.addon_state,**change,'frame_id':'changed'},10.1))
    assert bridge.world.query.owned_item_count(12345,10.1)['status']=='UNKNOWN'
    assert 'packet_inventory' not in bridge.world.state


def test_inventory_schema_rejects_foreign_guids_invalid_indices_and_unknown_layout():
    _,values=events(create_payload(player_tail=full_player_tail()))
    value=next(e for e in values if e.event_type=='OWN_INVENTORY_ROOTS').to_dict()
    value['payload']['root_slots'][0]=[0,f'{2<<58:016X}{999:016X}']
    with pytest.raises(ValueError):normalize_event(value)
    _,values=events(item_payload())
    value=next(e for e in values if e.event_type=='OWN_ITEM_UPDATE').to_dict()
    value['payload']['raw_secret']='must be dropped'
    assert 'raw_secret' not in normalize_event(value)['payload']
    value['provenance']['payload_layout']='WPP_12_1_REVIEWED_PREFIX_V1'
    assert not verified_semantics(normalize_event(value))


def test_item_create_then_delta_in_one_record_is_invalidated_in_wire_order():
    first=item_payload()
    update=b'\0'+packed(ITEM)+struct.pack('<I',1)+b'\xff'
    blocks=first[11:]+update
    together=struct.pack('<HI',2175,2)+b'\0'+struct.pack('<I',len(blocks))+blocks
    _,values=events(together)
    assert [e.event_type for e in values[1:]]==['OWN_ITEM_UPDATE','OWN_ITEM_REMOVED']
    assert values[-1].payload['removal']=='UNREVIEWED_UPDATE'


def test_known_item_changing_owner_is_not_read_as_another_players_inventory():
    decoder,_=events(item_payload())
    _,values=events(item_payload(owner=f'{2<<58:016X}{999:016X}'),decoder)
    assert [e.event_type for e in values[1:]]==['OWN_ITEM_REMOVED']
    assert values[-1].payload['removal']=='OWNER_CHANGED'


def test_readonly_advisor_sees_ownership_as_lower_bound_not_carried_ui_readiness(bridge):
    from wowbot.agent.advisory_tools import AdvisoryReadTools
    ready(bridge);deliver_native(bridge,item_payload())
    tool=AdvisoryReadTools(bridge.world,10.)
    value=tool.call({'tool':'item','ref':'12345'})
    assert value['count']==99  # independent client bag snapshot is retained
    assert value['native_ownership']['count_lower_bound']==7
    assert value['native_ownership']['carried'] is None and value['native_ownership']['complete'] is False
    assert '12345' in tool.context()['allowed_refs']['items']
    assert value['native_ownership']['evidence'][0] in tool.context()['allowed_refs']['evidence']
    assert 'native_ownership' not in bridge.world.state['inventory']['items'][0]
    assert 'native_ownership' not in AdvisoryReadTools(bridge.world,12.1).call({'tool':'item','ref':'12345'})


def test_gap_rebaseline_cannot_reuse_old_inventory_even_before_projection(bridge):
    from test_packet_continuity_20261030 import connected
    provider,decoder,baseline,_=connected(bridge)
    deliver_native(bridge,item_payload(),decoder=decoder)
    assert bridge.world.query.owned_item_count(12345,10.)['count']==7
    provider.invalidate('stream_gap')
    assert provider.accept_baseline(baseline.to_dict())
    assert bridge.world.query.owned_item_count(12345,10.)['status']=='UNKNOWN'
    bridge.world._rebuild_state()
    assert '_packet_inventory' not in bridge.world.__dict__
    assert 'packet_inventory' not in bridge.world.state
