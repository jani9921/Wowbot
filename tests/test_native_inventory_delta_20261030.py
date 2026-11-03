"""Owned item VALUES preserve each field's original observation clock."""
import struct

import pytest

from wowbot.packetio.validation import normalize_event,verified_semantics
from test_packet_agent_bridge import bridge
from test_unit_fields_20261027 import bits
from test_native_inventory_20261030 import (RAW_ME,ITEM,BAG,ZERO,packed,events,item_payload,
                                           deliver_native,ready)


def mask_bytes(changed,words):
    values=[sum(1<<(i%32) for i in changed if i//32==j) for j in range(words)]
    presence=sum(1<<j for j,w in enumerate(values) if w)
    return bits([(presence,words),*((w,32) for w in values if w)])


def delta_payload(*, quantity=None, durability=None, parent=None, owner=None, unsupported=False,
                  slots=None, capacity=None, guid=ITEM, tail=b''):
    kinds=0
    value=b''
    changed={0}
    if quantity is not None:changed.add(7)
    if durability is not None:changed.add(10)
    if parent is not None:changed.add(4)
    if owner is not None:changed.add(3)
    if unsupported:changed.add(17)
    if len(changed)>1:
        kinds|=2;value+=mask_bytes(changed,2)
        if owner is not None:value+=packed(owner)
        if parent is not None:value+=packed(parent)
        if quantity is not None:value+=struct.pack('<I',quantity)
        if durability is not None:value+=struct.pack('<I',durability)
    if slots is not None or capacity is not None:
        kinds|=4;changed=set()
        if slots:changed.update({2,*(3+i for i,_ in slots)})
        if capacity is not None:changed.update({0,1})
        value+=mask_bytes(changed,4)
        if capacity is not None:value+=struct.pack('<I',capacity)
        for _,item in sorted(slots or ()):value+=packed(item)
    blob=bytes((1,0,3))+struct.pack('<I',kinds)+value+tail
    block=b'\0'+packed(guid)+struct.pack('<I',len(blob))+blob
    return struct.pack('<HI',2175,1)+b'\0'+struct.pack('<I',len(block))+block


def test_owned_quantity_delta_is_reviewed_v2_and_v1_cannot_claim_it():
    decoder,_=events(item_payload())
    _,values=events(delta_payload(quantity=9),decoder,at=10.1)
    value=next(e for e in values if e.event_type=='OWN_ITEM_UPDATE').to_dict()
    assert value['payload']['sample_kind']=='VALUES' and value['payload']['stack_count']==9
    assert 'item_id' not in value['payload']  # no resampling cached metadata as a wire value
    assert verified_semantics(normalize_event(value))
    value['provenance']['payload_layout']='WPP_12_1_OWN_INVENTORY_REVIEWED_V1'
    with pytest.raises(ValueError):normalize_event(value)


def test_counter_change_updates_count_but_durability_does_not_rejuvenate_it(bridge):
    ready(bridge)
    decoder=deliver_native(bridge,item_payload())
    deliver_native(bridge,delta_payload(quantity=11),decoder=decoder,at=10.1)
    row=bridge.world.query.native_inventory(10.1)['items'][0]
    assert row['stack_count']==11 and row['sample_time']==10.1 and row['identity_sample_time']==10.
    deliver_native(bridge,delta_payload(durability=17),decoder=decoder,at=11.9)
    row=bridge.world.query.native_inventory(11.9)['items'][0]
    assert row['durability']==17 and row['sample_time']==10.1
    assert bridge.world.query.owned_item_count(12345,12.2)['status']=='UNKNOWN'
    assert bridge.world.state['inventory']['items'][0]['count']==99


def test_reordered_different_field_deltas_keep_independent_clocks(bridge):
    ready(bridge);decoder=deliver_native(bridge,item_payload())
    deliver_native(bridge,delta_payload(durability=17),decoder=decoder,at=10.2)
    deliver_native(bridge,delta_payload(quantity=11),decoder=decoder,at=10.1)
    row=bridge.world.query.native_inventory(10.2)['items'][0]
    assert row['durability']==17 and row['stack_count']==11 and row['sample_time']==10.1


def test_container_slot_delta_does_not_rejuvenate_all_98_slots_or_quantity(bridge):
    ready(bridge);decoder=deliver_native(bridge,item_payload(low=124,bag=True))
    deliver_native(bridge,delta_payload(guid=BAG,slots=[(0,'0'*32),(1,ITEM)]),decoder=decoder,at=10.1)
    row=bridge.world.query.native_inventory(10.1)['items'][0]
    assert [0,'0'*32] in row['container_slots'] and [1,ITEM] in row['container_slots']
    assert row['sample_time']==10. and row['container_slots_coverage']=='COMPLETE'
    deliver_native(bridge,delta_payload(guid=BAG,quantity=1),decoder=decoder,at=12.05)
    row=bridge.world.query.native_inventory(12.05)['items'][0]
    assert row['identity_sample_time']==10. and len(row['container_slots'])==2
    assert row['container_slots_coverage']=='PARTIAL' and 'num_slots' not in row


@pytest.mark.parametrize('change',[{'unsupported':True},{'quantity':5,'tail':b'unknown-tail'}])
def test_unreviewed_delta_loses_ownership_until_another_create(bridge,change,monkeypatch):
    ready(bridge);decoder=deliver_native(bridge,item_payload())
    deliver_native(bridge,delta_payload(**change),decoder=decoder,at=10.1)
    assert bridge.world.query.owned_item_count(12345,10.1)['status']=='UNKNOWN'
    from wowbot.packetio import own_item_delta
    def forbidden(*args):pytest.fail('private item reader used after ownership was invalidated')
    monkeypatch.setattr(own_item_delta,'read_values',forbidden)
    _,values=events(delta_payload(quantity=9),decoder,at=10.2)
    assert all(e.event_type!='OWN_ITEM_UPDATE' for e in values)


def test_owner_change_drops_item_before_reading_any_foreign_private_tail():
    decoder,_=events(item_payload())
    _,values=events(delta_payload(owner=f'{2<<58:016X}{999:016X}',tail=b'private-not-read'),decoder,at=10.1)
    assert values[-1].event_type=='OWN_ITEM_REMOVED' and values[-1].payload['removal']=='OWNER_CHANGED'


def test_transient_duplicate_slot_identity_is_not_advertised_as_complete_container(bridge):
    ready(bridge);decoder=deliver_native(bridge,item_payload(low=124,bag=True))
    deliver_native(bridge,delta_payload(guid=BAG,slots=[(1,ITEM)]),decoder=decoder,at=10.1)
    row=bridge.world.query.native_inventory(10.1)['items'][0]
    assert row['container_slots_coverage']=='UNKNOWN' and 'container_slots' not in row
    deliver_native(bridge,delta_payload(guid=BAG,slots=[(0,'0'*32)]),decoder=decoder,at=10.2)
    row=bridge.world.query.native_inventory(10.2)['items'][0]
    assert row['container_slots_coverage']=='COMPLETE'


def test_old_removal_cannot_erase_a_fresher_create_or_quantity_sample(bridge):
    ready(bridge);decoder=deliver_native(bridge,item_payload())
    deliver_native(bridge,delta_payload(quantity=11),decoder=decoder,at=10.2)
    deliver_native(bridge,delta_payload(unsupported=True),decoder=decoder,at=10.1)
    assert bridge.world.query.owned_item_count(12345,10.2)['count']==11
