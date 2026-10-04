from collections import deque

from wowbot.runtime.backpressure import (
    bound_queue, coalesce_latest, drop_stale, prioritize_critical_event,
)


def test_coalesce_latest_replaces_only_prior_pending_sample():
    assert coalesce_latest(None, "new") == ("new", False)
    assert coalesce_latest("old", "new") == ("new", True)


def test_drop_stale_preserves_survivor_order_and_bound_queue_evicts_oldest():
    kept, dropped = drop_stale(
        (("old", 1.), ("a", 9.6), ("b", 9.9)),
        now=10., max_age=.5, timestamp=lambda item: item[1])
    assert kept == (("a", 9.6), ("b", 9.9)) and dropped == 1
    queue = deque((1, 2))
    assert bound_queue(queue, 3, max_size=2) == 1
    assert tuple(queue) == (2, 3)


def test_critical_admission_evicts_ordinary_and_can_observably_overflow():
    queue = deque(((1, "ordinary"), (2, "critical")))
    decision = prioritize_critical_event(
        queue, (3, "critical"), max_size=2,
        is_critical=lambda row: row[1] == "critical")
    assert decision.accepted and decision.dropped == 1
    assert tuple(queue) == ((2, "critical"),)
    queue.append((3, "critical"))
    overflow = prioritize_critical_event(
        queue, (4, "critical"), max_size=2,
        is_critical=lambda row: row[1] == "critical")
    assert overflow.accepted and overflow.critical_overflow == 1


def test_noncritical_event_is_rejected_when_queue_is_all_critical():
    queue = deque(((1, "critical"), (2, "critical")))
    decision = prioritize_critical_event(
        queue, (3, "ordinary"), max_size=2,
        is_critical=lambda row: row[1] == "critical")
    assert not decision.accepted and decision.dropped == 1
    assert len(queue) == 2
