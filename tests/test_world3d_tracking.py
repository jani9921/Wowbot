from wowbot.vision.world3d.models import PixelRect, WorldCandidate
import pytest
import threading
import time
from types import SimpleNamespace

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from wowbot.vision.world3d.tracking import (
    UltralyticsAssociationTracker, WorldCandidateTracker,
)


def mob(rect, relation):
    return WorldCandidate("unknown_subject_candidate", rect, 0.9, "test", relation=relation)


def test_same_mob_keeps_track_across_relation_change():
    tracker = WorldCandidateTracker(max_distance=50)
    a = tracker.update((mob(PixelRect(100, 100, 140, 130), "neutral"),))[0]
    b = tracker.update((mob(PixelRect(104, 102, 144, 132), "hostile"),))[0]
    assert a.track_id == b.track_id
    assert b.previous_relation == "neutral"
    assert b.relation == "hostile"
    assert b.relation_changed is True
    assert "neutral->hostile" in b.evidence


def test_distant_mob_gets_new_track():
    tracker = WorldCandidateTracker(max_distance=20)
    a = tracker.update((mob(PixelRect(0, 0, 20, 20), "neutral"),))[0]
    b = tracker.update((mob(PixelRect(100, 100, 120, 120), "hostile"),))[0]
    assert a.track_id != b.track_id


def test_crossing_tracks_no_id_swap():
    """Global assignment avoids the classic first-candidate greedy steal."""
    tracker = WorldCandidateTracker(max_distance=50)
    first = tracker.update((
        mob(PixelRect(5, 5, 15, 15), "neutral"),
        mob(PixelRect(25, 5, 35, 15), "neutral"),
    ))
    observed = tracker.update((
        WorldCandidate("unknown_subject_candidate", PixelRect(17, 5, 27, 15),
                       .95, "high-confidence candidate", relation="neutral"),
        WorldCandidate("unknown_subject_candidate", PixelRect(23, 5, 33, 15),
                       .80, "lower-confidence candidate", relation="neutral"),
    ))

    assert observed[0].track_id == first[0].track_id
    assert observed[1].track_id == first[1].track_id


def test_unknown_subject_reacquires_after_short_detector_gap():
    """A detector flicker must not discard a still-UNKNOWN visual identity."""
    tracker = WorldCandidateTracker(max_distance=50, max_misses=8)
    first = tracker.update((mob(PixelRect(100, 100, 140, 130), "unknown"),))[0]
    for _ in range(5):
        tracker.update(())
    reacquired = tracker.update((mob(PixelRect(104, 101, 144, 131), "unknown"),))[0]
    assert reacquired.track_id == first.track_id


def _bgra_texture(width=320, height=240):
    rng = np.random.default_rng(17)
    image = rng.integers(0, 255, (height, width, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    return image


def test_botsort_keeps_id_across_large_camera_pan():
    pytest.importorskip("ultralytics")
    tracker = UltralyticsAssociationTracker(backend="botsort")
    first_frame = _bgra_texture()
    second_frame = cv2.warpAffine(
        first_frame, np.float32([[1, 0, 35], [0, 1, 0]]), (320, 240))

    first = tracker.update(
        (mob(PixelRect(80, 80, 110, 150), "unknown"),),
        timestamp=1.0, raw=first_frame.tobytes(), width=320, height=240)[0]
    moved = tracker.update(
        (mob(PixelRect(115, 80, 145, 150), "unknown"),),
        timestamp=1.05, raw=second_frame.tobytes(), width=320, height=240)[0]

    assert moved.track_id == first.track_id
    assert moved.appearance["tracker_backend"] == "botsort"
    assert "gmc" in moved.appearance["track_association"]


def test_botsort_reacquires_same_id_after_detector_gap():
    pytest.importorskip("ultralytics")
    tracker = UltralyticsAssociationTracker(backend="botsort", track_buffer=30)
    image = _bgra_texture()
    raw = image.tobytes()
    first = tracker.update(
        (mob(PixelRect(100, 80, 140, 160), "unknown"),),
        timestamp=1.0, raw=raw, width=320, height=240)[0]
    for index in range(5):
        tracker.update((), timestamp=1.05 + index * .05,
                       raw=raw, width=320, height=240)
    reacquired = tracker.update(
        (mob(PixelRect(104, 81, 144, 161), "unknown"),),
        timestamp=1.35, raw=raw, width=320, height=240)[0]

    assert reacquired.track_id == first.track_id
    assert tracker.last_diagnostics["lost_tracks"] == 0


def test_botsort_family_gate_prevents_subject_symbol_id_swap():
    pytest.importorskip("ultralytics")
    tracker = UltralyticsAssociationTracker(backend="botsort")
    image = _bgra_texture()
    raw = image.tobytes()
    subject = mob(PixelRect(100, 80, 130, 140), "unknown")
    symbol = WorldCandidate(
        "unknown_symbol_candidate", PixelRect(102, 80, 132, 140), .9, "test")
    first = tracker.update(
        (subject, symbol), timestamp=1.0, raw=raw, width=320, height=240)
    observed = tracker.update(
        (WorldCandidate("unknown_symbol_candidate", PixelRect(104, 80, 134, 140),
                        .9, "test"),
         mob(PixelRect(106, 80, 136, 140), "unknown")),
        timestamp=1.05, raw=raw, width=320, height=240)

    first_ids = {item.kind: item.track_id for item in first}
    observed_ids = {item.kind: item.track_id for item in observed}
    assert observed_ids == first_ids
    assert tracker.last_diagnostics["family_gate"] is True


def test_background_botsort_warmup_does_not_block_and_preserves_public_id(monkeypatch):
    pytest.importorskip("ultralytics")
    original_loader = UltralyticsAssociationTracker._ensure_tracker
    entered = threading.Event()
    release = threading.Event()

    def delayed_loader(self):
        entered.set()
        assert release.wait(timeout=5)
        return original_loader(self)

    monkeypatch.setattr(
        UltralyticsAssociationTracker, "_ensure_tracker", delayed_loader)
    tracker = UltralyticsAssociationTracker(
        backend="botsort", warmup_in_background=True)
    assert entered.wait(timeout=2)
    image = _bgra_texture()
    raw = image.tobytes()
    started = time.perf_counter()
    fallback = tracker.update(
        (mob(PixelRect(100, 80, 140, 160), "unknown"),),
        timestamp=1.0, raw=raw, width=320, height=240)[0]
    assert time.perf_counter() - started < .25
    assert tracker.last_diagnostics["status"] == "warming_fallback_legacy"

    release.set()
    tracker._warmup_thread.join(timeout=10)
    native = tracker.update(
        (mob(PixelRect(104, 81, 144, 161), "unknown"),),
        timestamp=1.05, raw=raw, width=320, height=240)[0]

    assert native.track_id == fallback.track_id
    assert tracker.last_diagnostics["status"] == "ready"


def test_partial_native_assignment_bridges_tentative_detection_without_sticky_fallback():
    """Ultralytics may withhold a new track until its next confirming frame."""
    tracker = UltralyticsAssociationTracker(backend="botsort")

    class Boxes:
        def __init__(self, rows, orig_shape):
            self.rows = rows
            self.orig_shape = orig_shape

    class PartialTracker:
        def __init__(self):
            self.frame_id = 0
            self.tracked_stracks = []
            self.lost_stracks = []

        def update(self, boxes, img=None):
            self.frame_id += 1
            self.tracked_stracks = [
                SimpleNamespace(
                    frame_id=self.frame_id, idx=index, track_id=100 + index,
                    xyxy=np.asarray(boxes.rows[index][:4], dtype=np.float32))
                for index in range(2)
            ]

    tracker._tracker = PartialTracker()
    tracker._boxes_type = Boxes
    image = _bgra_texture()
    candidates = (
        mob(PixelRect(20, 30, 50, 100), "unknown"),
        mob(PixelRect(90, 30, 120, 100), "unknown"),
        mob(PixelRect(160, 30, 190, 100), "unknown"),
    )

    first = tracker.update(
        candidates, timestamp=1., raw=image.tobytes(), width=320, height=240)
    second = tracker.update(
        candidates, timestamp=1.1, raw=image.tobytes(), width=320, height=240)

    assert len(first) == len(second) == 3
    assert [item.track_id for item in second] == [item.track_id for item in first]
    assert first[0].appearance["tracker_backend"] == "botsort"
    assert first[1].appearance["tracker_backend"] == "botsort"
    assert "tracker_backend" not in first[2].appearance
    assert tracker.last_diagnostics["status"] == "ready_partial"
    assert tracker.last_diagnostics["native_assignments"] == 2
    assert tracker.last_diagnostics["tentative_legacy_bridge"] == 1
    assert tracker._load_error is None
