"""DESIGN-093: CapabilityAcceptanceTracker per-capability metrics."""
from wowbot.agent.capability_acceptance import CapabilityAcceptanceTracker


def test_report_rate_is_none_before_any_case_is_recorded():
    tracker = CapabilityAcceptanceTracker()
    assert tracker.report_rate("INTERACT") is None


def test_report_rate_tracks_successes_over_cases():
    tracker = CapabilityAcceptanceTracker()
    for _ in range(4):
        tracker.record_case("INTERACT")
    tracker.record_success("INTERACT")
    tracker.record_success("INTERACT")
    tracker.record_failure("INTERACT", "TARGET_LOST")
    tracker.record_failure("INTERACT", "OUT_OF_RANGE")
    assert tracker.report_rate("INTERACT") == 0.5


def test_group_by_failure_counts_each_reason_separately():
    tracker = CapabilityAcceptanceTracker()
    tracker.record_case("COMBAT")
    tracker.record_failure("COMBAT", "OUT_OF_RANGE")
    tracker.record_case("COMBAT")
    tracker.record_failure("COMBAT", "OUT_OF_RANGE")
    tracker.record_case("COMBAT")
    tracker.record_failure("COMBAT", "LINE_OF_SIGHT")
    assert tracker.group_by_failure("COMBAT") == {"OUT_OF_RANGE": 2, "LINE_OF_SIGHT": 1}
    assert tracker.group_by_failure("UNKNOWN_CAPABILITY") == {}


def test_capabilities_are_tracked_independently():
    tracker = CapabilityAcceptanceTracker()
    tracker.record_case("LOOT")
    tracker.record_success("LOOT")
    assert tracker.report_rate("LOOT") == 1.0
    assert tracker.report_rate("COMBAT") is None


def test_snapshot_reports_every_tracked_capability():
    tracker = CapabilityAcceptanceTracker()
    tracker.record_case("LOOT")
    tracker.record_success("LOOT")
    snapshot = tracker.snapshot()
    assert snapshot["LOOT"] == {"cases": 1, "successes": 1, "failures": 0,
                                "success_rate": 1.0, "failure_reasons": {}}
