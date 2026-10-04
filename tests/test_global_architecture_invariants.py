from pathlib import Path

from wowbot.agent.vision_seek import SeekVisualCueController
from wowbot.runtime import FailureManager, FailureReason
from wowbot.runtime.architecture_invariants import ARCHITECTURE_INVARIANTS, invariant


ROOT = Path(__file__).resolve().parents[1]


def test_all_twenty_invariants_have_one_named_owner_and_existing_evidence():
    assert [item.invariant_id for item in ARCHITECTURE_INVARIANTS] == [
        f"INV-{index:02d}" for index in range(1, 21)]
    assert len({item.owner for item in ARCHITECTURE_INVARIANTS}) >= 15
    for item in ARCHITECTURE_INVARIANTS:
        assert item.statement and item.owner and item.enforcement
        assert all((ROOT / path).is_file() for path in item.enforcement)
        assert invariant(item.invariant_id) is item


def test_inv13_failure_retry_budget_is_finite_and_eventually_disallows_retry():
    manager = FailureManager()
    decisions = [manager.record_failure(
        correlation_id="same", skill="COMBAT", reason=FailureReason.NO_RESPONSE,
        at=float(index), retryable=True) for index in range(1, 8)]
    assert decisions[0].retry_allowed
    assert not decisions[-1].retry_allowed
    assert decisions[-1].goal_failed
    assert len(manager.recent(correlation_id="same")) <= 16


def test_inv14_visual_local_search_has_finite_sector_and_time_budget():
    search = SeekVisualCueController(max_seconds=2.)
    search.begin({}, {}, 0.)
    for index in range(len(search.sectors)):
        now = index*.5
        assert not search.observe({"visual_candidates": []}, str(index), now).terminal
        assert search.command({}, str(index), now)
    exhausted = search.observe({"visual_candidates": []}, "done", 2.1)
    assert exhausted.terminal and not exhausted.success
    assert exhausted.reason in {"seek_visual_cue_safety_deadline",
                                "seek_visual_cue_sectors_exhausted"}
