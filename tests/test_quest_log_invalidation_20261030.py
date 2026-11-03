"""An unread own quest delta cannot leave a complete/absent membership proof."""
from dataclasses import replace
import struct

import pytest

from wowbot.packetio.validation import normalize_event, verified_semantics
from test_packet_agent_bridge import bridge, deliver
from test_native_quest_log_20261030 import setup, send, slot, quest_event
from test_native_inventory_20261030 import RAW_ME, packed
from test_own_health_packets_20261030 import own_event


def unknown(*, at=10.1, **options):
    decoder, record = quest_event(at=at,extra_bits=(0,3),**options)
    return next(e for e in decoder.decode_all(record) if e.event_type=='OWN_QUEST_LOG_INVALIDATED')


def invalidate(bridge, *, at=10.1, **options):
    bridge.inbox._clock=lambda:at
    bridge.inbox._wall_clock=lambda:1000.+at-10.
    return deliver(bridge,unknown(at=at,**options),at=at)


def full(bridge, *, at=10.):
    return send(bridge,[slot(i,55639 if i==3 else 0) for i in range(175)],at=at)


def test_invalidation_has_own_build_specific_layout_and_no_private_body():
    event = unknown()
    assert verified_semantics(normalize_event(event.to_dict()))
    assert set(event.payload)=={'mover_guid','world_map_id'}
    assert event.provenance['payload_layout']=='WPP_12_1_QUEST_LOG_INVALIDATION_V1'
    wrong = event.to_dict()
    wrong['provenance']['payload_layout']='WPP_12_1_REVIEWED_PREFIX_V1'
    assert not verified_semantics(normalize_event(wrong))
    wrong['direction']='CLIENT_TO_SERVER'
    with pytest.raises(ValueError):normalize_event(wrong)


def test_unknown_prefix_revokes_old_membership_without_mutating_ui_quest_progress(bridge):
    setup(bridge);full(bridge)
    assert bridge.world.query.quest_presence(88719,10.)['state']=='ABSENT'
    invalidate(bridge)
    assert bridge.world.query.quest_presence(88719,10.1)['state']=='UNKNOWN'
    assert bridge.world.query.quest_presence(55639,10.1)['state']=='UNKNOWN'
    assert bridge.world.query.quest_log_slots(10.1)['baseline_observed_at'] is None
    assert bridge.world.quest_model.records[55639].current_state=='ACTIVE'
    assert bridge.world.quest_model.records[55639].objectives[0].current_count==0
    assert bridge.world.last_received==9.1


def test_invalidation_is_a_barrier_against_older_snapshot_but_allows_fresh_partial_then_full(bridge):
    setup(bridge);full(bridge)
    invalidate(bridge,at=10.2)
    full(bridge,at=10.1)
    assert bridge.world.query.quest_presence(88719,10.2)['state']=='UNKNOWN'
    send(bridge,[slot(4,88719)],at=10.3)
    assert bridge.world.query.quest_presence(88719,10.3)['state']=='PRESENT'
    assert bridge.world.query.quest_presence(55639,10.3)['state']=='UNKNOWN'
    full(bridge,at=10.4)
    assert bridge.world.query.quest_presence(88719,10.4)['state']=='ABSENT'
    assert bridge.world.query.quest_presence(55639,10.4)['state']=='PRESENT'


def test_delayed_invalidation_preserves_only_newer_fields_not_the_old_complete_collection(bridge):
    setup(bridge);full(bridge)
    send(bridge,[slot(3,55639)],at=10.2)
    invalidate(bridge,at=10.1)
    view = bridge.world.query.quest_log_slots(10.2)
    assert view['membership']=='PARTIAL' and view['known_slots']==1
    assert bridge.world.query.quest_presence(55639,10.2)['state']=='PRESENT'
    assert bridge.world.query.quest_presence(88719,10.2)['state']=='UNKNOWN'


def test_mask_proven_unchanged_questlog_does_not_refresh_or_invalidate_original_slots(bridge):
    setup(bridge);full(bridge)
    decoder, record = quest_event([],full=False,extra_bits=(0,3),private_prefix=b'NOT_EXPORTED',at=11.9)
    values = decoder.decode_all(record)
    assert not any(e.event_type.startswith('OWN_QUEST_LOG') for e in values)
    assert bridge.world.query.quest_log_slots(11.9)['baseline_observed_at']==10.
    assert bridge.world.query.quest_presence(55639,12.1)['state']=='UNKNOWN'


def test_unreviewed_fragment_change_invalidates_own_collections_without_reading_its_tail():
    decoder, record = own_event()
    blob=bytes((0,1))+b'PRIVATE_TAIL_NOT_READ'
    block=b'\0'+packed(RAW_ME)+struct.pack('<I',len(blob))+blob
    payload=struct.pack('<HI',2175,1)+b'\0'+struct.pack('<I',len(block))+block
    values=decoder.decode_all(replace(record,payload=payload))
    assert {e.event_type for e in values}=={'PACKET_OPCODE_OBSERVED','OWN_INVENTORY_INVALIDATED','OWN_QUEST_LOG_INVALIDATED'}
    assert 'PRIVATE_TAIL' not in str([e.to_dict() for e in values])


def test_other_world_invalidation_does_not_erase_this_worlds_membership(bridge):
    setup(bridge);full(bridge)
    event=unknown()
    event=replace(event,payload={**event.payload,'world_map_id':1})
    bridge.inbox._clock=lambda:10.1
    bridge.inbox._wall_clock=lambda:1000.1
    deliver(bridge,event,at=10.1)
    assert bridge.world.query.quest_presence(88719,10.1)['state']=='ABSENT'
