"""Changed own InvSlots keep independent clocks and cannot invent bag UI."""
import struct

import pytest

from wowbot.packetio.validation import normalize_event, verified_semantics
from wowbot.packetio.own_inventory_codec import ZERO
from test_packet_agent_bridge import bridge
from test_native_inventory_20261030 import (RAW_ME, ITEM, BAG, packed, events,
    full_player_tail, create_payload, deliver_native, ready)
from test_native_inventory_delta_20261030 import mask_bytes


def root_payload(rows=(), *, changed=None, tail=b'', guid=RAW_ME, update_type=0x80):
    if changed is None:
        changed = {163, *(164+i for i, _ in rows)}
    blob = bytes((0, 0, 3))+struct.pack('<I', update_type)+mask_bytes(changed, 13)
    blob += b''.join(packed(value) for _, value in sorted(rows))+tail
    block = b'\0'+packed(guid)+struct.pack('<I', len(blob))+blob
    return struct.pack('<HI', 2175, 1)+b'\0'+struct.pack('<I', len(block))+block


def baseline(bridge):
    ready(bridge)
    return deliver_native(bridge, create_payload(player_tail=full_player_tail()))


def test_root_values_require_reviewed_v2_and_export_only_changed_slots():
    _, values = events(root_payload([(23, ZERO), (24, ITEM)]))
    event = next(e for e in values if e.event_type == 'OWN_INVENTORY_ROOTS').to_dict()
    assert event['payload']['sample_kind'] == 'VALUES'
    assert event['payload']['root_slots'] == [[23, ZERO], [24, ITEM]]
    assert verified_semantics(normalize_event(event))
    event['provenance']['payload_layout'] = 'WPP_12_1_OWN_INVENTORY_REVIEWED_V1'
    with pytest.raises(ValueError):
        normalize_event(event)


def test_slot_move_merges_without_rejuvenating_the_other_103_slots(bridge):
    decoder = baseline(bridge)
    deliver_native(bridge, root_payload([(23, ZERO), (24, ITEM)]), decoder=decoder, at=10.1)
    result = bridge.world.query.native_inventory(10.1)
    assert result['root_membership'] == 'COMPLETE' and len(result['root_slots']) == 105
    assert result['root_slots'][23:25] == [[23, ZERO], [24, ITEM]]
    assert result['root_sample_time'] == result['root_baseline_time'] == 10.
    assert result['root_slot_evidence']['24']['observed_at'] == 10.1
    assert result['root_slot_evidence']['19']['observed_at'] == 10.
    assert 'root_observation_id' not in result  # no single source for a merged snapshot
    assert 'root_slots' not in bridge.world.state['packet_inventory']
    result = bridge.world.query.native_inventory(12.05)
    assert result['root_membership'] == 'PARTIAL'
    assert result['root_slots'] == [[23, ZERO], [24, ITEM]]
    assert result['root_sample_time'] == 10.1 and result['root_baseline_time'] == 10.
    result['root_slots'][0][1] = BAG
    assert bridge.world.query.native_inventory(12.05)['root_slots'][0][1] == ZERO
    assert bridge.world.state['inventory']['items'][0]['bag'] == 0


def test_unrelated_active_data_cannot_rejuvenate_or_invalidate_inventory_roots(bridge):
    decoder = baseline(bridge)
    # Backpack sorting flag is unrelated to InvSlots; its payload is not exported.
    _, values = events(root_payload(changed={0, 1}, tail=b'\x80'), decoder, at=11.9)
    assert not any(e.event_type.startswith('OWN_INVENTORY') for e in values)
    deliver_native(bridge, root_payload(changed={0, 1}, tail=b'\x80'), decoder=decoder, at=11.9)
    assert bridge.world.query.native_inventory(11.9)['root_sample_time'] == 10.
    assert bridge.world.query.native_inventory(12.1)['root_membership'] == 'UNKNOWN'


@pytest.mark.parametrize('data', [
    root_payload([(23, ZERO)], changed={187}),  # missing array parent
    root_payload([(23, RAW_ME)]),              # player is not an item
    root_payload([(23, ZERO)], tail=b'unknown-tail'),
    root_payload([(23, ITEM)], changed={0, 1, 163, 187}),  # unreviewed preceding field
    root_payload([(23, ITEM)])[:-1],           # truncated enclosing update
])
def test_unreviewed_root_payload_never_produces_a_partial_false_snapshot(data):
    _, values = events(data)
    assert not any(e.event_type == 'OWN_INVENTORY_ROOTS' for e in values)


def test_unknown_root_layout_is_a_barrier_against_older_snapshot_and_delta(bridge):
    decoder = baseline(bridge)
    bad = root_payload([(23, ZERO)], tail=b'unknown-tail')
    deliver_native(bridge, bad, decoder=decoder, at=10.2)
    assert bridge.world.query.native_inventory(10.2)['root_membership'] == 'UNKNOWN'
    deliver_native(bridge, create_payload(player_tail=full_player_tail()), at=10.1)
    deliver_native(bridge, root_payload([(24, ITEM)]), decoder=decoder, at=10.1)
    deliver_native(bridge, root_payload([(24, ITEM)]), decoder=decoder, at=10.2)
    assert bridge.world.query.native_inventory(10.2)['root_membership'] == 'UNKNOWN'
    deliver_native(bridge, root_payload([(24, ITEM)]), decoder=decoder, at=10.3)
    result = bridge.world.query.native_inventory(10.3)
    assert result['root_membership'] == 'PARTIAL' and result['root_slots'] == [[24, ITEM]]
    assert result['root_baseline_time'] is None


def test_reordered_separate_slot_deltas_and_old_invalidation_do_not_erase_newer_facts(bridge):
    decoder = baseline(bridge)
    deliver_native(bridge, root_payload([(24, ITEM)]), decoder=decoder, at=10.2)
    deliver_native(bridge, root_payload([(23, ZERO)]), decoder=decoder, at=10.1)
    deliver_native(bridge, root_payload([(24, ZERO)]), decoder=decoder, at=10.1)
    deliver_native(bridge, root_payload([(23, ZERO)], tail=b'unknown'), decoder=decoder, at=10.1)
    result = bridge.world.query.native_inventory(10.2)
    assert result['root_membership'] == 'PARTIAL'
    assert result['root_slots'] == [[24, ITEM]]
    assert result['root_baseline_time'] is None
    assert result['root_slot_evidence']['24']['observed_at'] == 10.2


def test_invalidation_older_than_a_complete_newer_root_snapshot_does_not_erase_it(bridge):
    decoder = baseline(bridge)
    deliver_native(bridge, create_payload(player_tail=full_player_tail()), decoder=decoder, at=10.2)
    deliver_native(bridge, root_payload([(23, ZERO)],tail=b'unknown'), decoder=decoder, at=10.1)
    result = bridge.world.query.native_inventory(10.2)
    assert result['root_membership']=='COMPLETE' and result['root_baseline_time']==10.2
    assert len(result['root_slots'])==105


def test_conflicting_merged_roots_are_unknown_until_a_verified_move_resolves_them(bridge):
    decoder = baseline(bridge)
    deliver_native(bridge, root_payload([(24, ITEM)]), decoder=decoder, at=10.1)
    result = bridge.world.query.native_inventory(10.1)
    assert result['root_membership'] == 'UNKNOWN' and 'root_slots' not in result
    deliver_native(bridge, root_payload([(23, ZERO)]), decoder=decoder, at=10.2)
    assert bridge.world.query.native_inventory(10.2)['root_membership'] == 'COMPLETE'


def test_root_delta_without_create_has_only_positive_partial_membership(bridge):
    ready(bridge)
    deliver_native(bridge, root_payload([(24, ITEM)]))
    result = bridge.world.query.native_inventory(10.)
    assert result['root_membership'] == 'PARTIAL' and result['root_baseline_time'] is None
    assert result['root_slots'] == [[24, ITEM]] and result['items'] == []
    assert bridge.world.query.owned_item_count(12345, 10.)['status'] == 'UNKNOWN'
