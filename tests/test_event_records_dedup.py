"""Perf fix: _emit_derived_event()'s duplicate check is O(1) via
_BoundedEventRecords.ids instead of an O(n) linear scan over up to 500
entries -- profiled 2026-09-22 as a real, multi-million-comparison cost
under a churning-track workload."""
from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel


def _obs(frame="f1", t=1.):
    return Observation.create({"session_id": "s1", "frame_id": frame, "timestamp": t}, t)


def test_emitting_the_same_event_twice_is_deduplicated():
    world = WorldModel()
    obs = _obs()
    first = world._emit_derived_event("ENTITY_APPEARED", {"guid": "Creature-1"}, obs)
    before = len(world.event_records)
    second = world._emit_derived_event("ENTITY_APPEARED", {"guid": "Creature-1"}, obs)
    assert second.event_id == first.event_id
    assert len(world.event_records) == before  # not appended again


def test_ids_set_stays_in_sync_after_eviction_past_maxlen():
    world = WorldModel()
    maxlen = world.event_records.maxlen
    for i in range(maxlen + 50):
        world._emit_derived_event("SOME_EVENT", {"i": i}, _obs(frame=f"f{i}", t=float(i)))
    assert len(world.event_records) == maxlen
    assert len(world.event_records.ids) == maxlen
    # Every id currently in the deque must be in the set, and nothing else.
    assert {item.event_id for item in world.event_records} == world.event_records.ids


def test_an_evicted_events_id_can_be_re_emitted_after_falling_out_of_the_window():
    world = WorldModel()
    maxlen = world.event_records.maxlen
    obs0 = _obs(frame="f0", t=0.)
    first = world._emit_derived_event("SOME_EVENT", {"i": 0}, obs0)
    assert first.event_id in world.event_records.ids
    for i in range(1, maxlen + 1):
        world._emit_derived_event("SOME_EVENT", {"i": i}, _obs(frame=f"f{i}", t=float(i)))
    # The original event has now been evicted -- its id must be gone too,
    # and emitting the identical (event_type, payload, observation) again
    # must be treated as new, not silently dropped as a stale duplicate.
    assert first.event_id not in world.event_records.ids
    again = world._emit_derived_event("SOME_EVENT", {"i": 0}, obs0)
    assert again.event_id == first.event_id
    assert again.event_id in world.event_records.ids
