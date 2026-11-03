"""REV4 P3 retained native collections (2026-10-31).

The server sends own quest-log/inventory VALUES only on change, so a correct
CREATE baseline used to turn UNKNOWN two seconds later although nothing had
changed.  A field clock now stays current while a fresh APPLIED witness
proves an unbroken applied chain since it was sampled: a missed or reordered
delta (UNAPPLIED), a DECODE_GAP / record gap, a delivery gap or an expired
witness ends the lease.  It is a lease, not a longer TTL; UI freshness and
input authority never follow from it."""
from types import SimpleNamespace

from test_applied_packet_progress_20261030 import control
from test_native_inventory_20261030 import events
from test_native_inventory_delta_20261030 import delta_payload
from test_packet_delivery_20261030 import native  # noqa: F401  (fixture)

from wowbot.agent.runtime_packet_progress import retained


def test_the_create_baseline_stays_current_across_chained_witnesses(native):
    for record, at in ((100, 10.), (101, 11.5), (102, 13.), (103, 14.5)):
        control(native, record=record, at=at)
    query = native.world.query
    assert query.packet_stream_progress(14.5)['status'] == 'APPLIED'
    assert query.owned_item_count(12345, 14.5)['count'] == 7
    assert query.quest_presence(55639, 14.5)['state'] == 'PRESENT'
    # The complete membership is still a complete, current collection.
    assert query.quest_presence(123456, 14.5)['state'] == 'ABSENT'
    assert native.world.last_received == 9.1        # no UI/addon freshness
    assert query.owned_item_count(12345, 16.6)['status'] == 'UNKNOWN'   # the witness aged out


def test_a_regressed_progress_chain_gives_no_lease(native):
    control(native, record=100, at=10.)
    control(native, record=99, at=11.5)
    assert native.world.query.packet_stream_progress(11.5)['status'] == 'UNAPPLIED'
    control(native, record=101, at=12.5)
    assert native.world.query.packet_stream_progress(12.5)['status'] == 'UNAPPLIED'
    assert native.world.query.owned_item_count(12345, 12.5)['status'] == 'UNKNOWN'
    assert native.world.query.quest_presence(123456, 12.5)['state'] == 'UNKNOWN'


def test_a_progress_that_overtook_its_delta_gives_no_lease(native):
    changed = events(delta_payload(quantity=11), native.decoder)[1][-1]
    native.feed(changed, poll=False)
    observations = control(native, ingest=False)
    assert native.world.ingest(observations[1]) and native.world.ingest(observations[0])
    assert native.world.query.packet_stream_progress(10.)['status'] == 'UNAPPLIED'
    control(native, record=101, at=12.5)
    assert native.world.query.owned_item_count(12345, 12.5)['status'] == 'UNKNOWN'


def test_a_decode_gap_discards_and_a_later_witness_revives_nothing(native):
    control(native, record=100, at=10., decode_failures=1)
    assert native.world.query.packet_stream_progress(10.)['status'] == 'DECODE_GAP'
    control(native, record=101, at=11.5, decode_failures=1)
    assert native.world.query.packet_stream_progress(11.5)['status'] == 'APPLIED'
    assert native.world.query.owned_item_count(12345, 11.5)['status'] == 'UNKNOWN'
    assert native.world.query.quest_presence(123456, 11.5)['state'] == 'UNKNOWN'


def test_the_lease_keeps_the_newest_value_never_an_older_one(native):
    changed = events(delta_payload(quantity=11), native.decoder)[1][-1]
    native.feed(changed)
    for record, at in ((100, 10.), (101, 11.5), (102, 13.)):
        control(native, record=record, at=at)
    assert native.world.query.owned_item_count(12345, 13.)['count'] == 11


def test_the_lease_needs_a_current_witness_newer_than_the_fact():
    provider = SimpleNamespace(process=SimpleNamespace(generation='g', selected_pid=1), capture_epoch='e',
                               continuity_generation=1, expected=lambda pid: object())
    token = ('g', 'e', 1)
    row = {'token': token, 'status': 'APPLIED', 'applied_since': 5., 'sample_time': 10.}
    model = SimpleNamespace(session_context_provider=provider,
                            __dict__={})
    model.__dict__.update(_packet_stream_progress=row, _packet_continuity_token=token,
                          session_context_provider=provider)
    assert retained(model, 6., 11.)
    assert not retained(model, 4., 11.)                 # sampled before the applied coverage
    assert not retained(model, 10.5, 11.)               # newer than the witness: TTL decides
    assert not retained(model, 6., 12.5)                # the witness is too old
    for status in ('UNAPPLIED', 'DECODE_GAP'):
        row['status'] = status
        assert not retained(model, 6., 11.)
    row.update(status='APPLIED', applied_since=None)
    assert not retained(model, 6., 11.)
    row['applied_since'] = 5.
    model.__dict__['_packet_continuity_token'] = ('g', 'e', 2)    # continuity changed
    assert not retained(model, 6., 11.)
