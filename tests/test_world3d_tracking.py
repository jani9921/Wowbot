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


def test_same_visible_box_coalesces_alternating_native_public_ids():
    """Live feed alternated two public IDs on the same detection in <100 ms."""
    tracker = UltralyticsAssociationTracker(backend="botsort")

    class Boxes:
        def __init__(self, rows, orig_shape):
            self.rows = rows

    class AlternatingNative:
        frame_id = 0
        tracked_stracks = ()
        lost_stracks = ()

        def update(self, boxes, img=None):
            self.frame_id += 1
            native_id = 100 if self.frame_id % 2 else 101
            self.tracked_stracks = (
                SimpleNamespace(frame_id=self.frame_id, idx=0, track_id=native_id,
                                xyxy=np.asarray(boxes.rows[0][:4], dtype=np.float32)),)

    tracker._tracker, tracker._boxes_type = AlternatingNative(), Boxes
    image = _bgra_texture().tobytes()
    candidate = mob(PixelRect(20, 60, 60, 140), "unknown")
    first = tracker.update((candidate,), timestamp=1., raw=image,
                           width=320, height=240)[0]
    # Simulate a previously known second BoT-SORT identity. The fallback ID
    # alone would otherwise bridge before the exact-box continuation can run.
    tracker._native_to_public[101] = 999
    observed = [tracker.update((candidate,), timestamp=1. + .04*step,
                               raw=image, width=320, height=240)[0]
                for step in range(1, 6)]

    assert {item.track_id for item in (first, *observed)} == {first.track_id}
    assert tracker.exact_box_rebindings >= 1
    assert tracker.last_diagnostics["exact_box_rebindings"] >= 1


def test_exact_box_bridge_rejects_simultaneous_stale_and_different_appearance():
    tracker = UltralyticsAssociationTracker(backend="botsort")
    candidate = mob(PixelRect(20, 60, 60, 140), "unknown")
    tracker._last_boxes[7] = {
        "rect": (20, 60, 60, 140), "family": tracker._family(candidate.kind),
        "descriptor": (0.,) * 6, "seen_at": 1.,
    }
    bridge = tracker._coalesce_exact_continuation
    assert bridge(candidate, 999, set(), 1.04, (0.,) * 6) == (7, 999)
    assert bridge(candidate, 999, {7}, 1.04, (0.,) * 6) is None
    assert bridge(candidate, 999, set(), 1.2, (0.,) * 6) is None
    assert bridge(candidate, 999, set(), 1.04, (1.,) * 6) is None
    assert bridge(candidate, 999, set(), 1.04, None) is None


def test_only_local_avatar_is_screen_anchored_between_two_nearby_npcs():
    """Live PID 16548: three subjects met the broad avatar-position gate."""
    tracker = UltralyticsAssociationTracker(backend="botsort")

    class Boxes:
        def __init__(self, rows, orig_shape):
            self.rows = rows

    class Native:
        frame_id = 0
        tracked_stracks = ()
        lost_stracks = ()

        def update(self, boxes, img=None):
            self.frame_id += 1
            self.tracked_stracks = tuple(
                SimpleNamespace(frame_id=self.frame_id, idx=index,
                                track_id=100 + index,
                                xyxy=np.asarray(row[:4], dtype=np.float32))
                for index, row in enumerate(boxes.rows))

    tracker._tracker, tracker._boxes_type = Native(), Boxes
    candidates = (
        mob(PixelRect(425, 242, 480, 346), "unknown"),
        mob(PixelRect(480, 274, 543, 442), "unknown"),
        mob(PixelRect(550, 260, 592, 348), "unknown"),
    )
    assert tracker._screen_anchor_indices(candidates, 1027, 578) == ([1], 1)
    raw = bytes(1027 * 578 * 4)
    first = tracker.update(candidates, timestamp=1., raw=raw,
                           width=1027, height=578)
    second = tracker.update(candidates, timestamp=1.04, raw=raw,
                            width=1027, height=578)

    assert [item.track_id for item in second] == [item.track_id for item in first]
    assert tracker.last_diagnostics["screen_anchor_candidates"] == 1
    assert tracker.last_diagnostics["screen_anchored"] == 1
    assert tracker.last_diagnostics["native_assignments"] == 2
    assert all("screen_anchored" not in item.appearance for item in (second[0], second[2]))


def test_screen_anchor_prefers_lower_avatar_and_tolerates_box_height_jitter():
    tracker = UltralyticsAssociationTracker(backend="botsort")
    # PID 10348: the upper NPC was sometimes closer to screen centre than the
    # actual avatar, and a 96/99-pixel box crossed the old height gate.
    upper = mob(PixelRect(546, 307, 603, 423), "unknown")
    avatar = mob(PixelRect(521, 389, 637, 572), "unknown")
    assert tracker._screen_anchor_indices((upper, avatar), 1153, 649, 1.) == ([1], 2)
    avatar_next = mob(PixelRect(522, 391, 636, 573), "unknown")
    assert tracker._screen_anchor_indices((upper, avatar_next), 1153, 649, 1.04) == ([1], 2)
    assert tracker._screen_anchor_indices((upper,), 1153, 649, 1.08) == ([], 1)
    assert tracker._screen_anchor_indices((avatar_next,), 1153, 649, 1.12) == ([0], 1)
    tracker.reset()
    short_a = mob(PixelRect(540, 363, 613, 462), "unknown")
    short_b = mob(PixelRect(540, 367, 613, 463), "unknown")
    assert tracker._screen_anchor_indices((short_a,), 1153, 649, 2.) == ([0], 1)
    assert tracker._screen_anchor_indices((short_b,), 1153, 649, 2.04) == ([0], 1)
    tracker.reset()
    bottom_337 = mob(PixelRect(441, 246, 479, 337), "unknown")
    bottom_336 = mob(PixelRect(441, 246, 479, 336), "unknown")
    assert tracker._screen_anchor_indices((bottom_337,), 920, 518, 3.) == ([0], 1)
    assert tracker._screen_anchor_indices((bottom_336,), 920, 518, 3.04) == ([0], 1)
    far_box = mob(PixelRect(500, 246, 538, 336), "unknown")
    assert tracker._screen_anchor_indices((far_box,), 920, 518, 3.08) == ([], 0)


def test_public_id_survives_tentative_rebirth_then_native_confirmation_after_camera_turn():
    """The fallback-only frame must not publish an ID that changes at confirmation."""
    tracker = UltralyticsAssociationTracker(backend="botsort")

    class Boxes:
        def __init__(self, rows, orig_shape):
            self.rows = rows

    class Native:
        frame_id = 0
        tracked_stracks = ()
        lost_stracks = ()

        def update(self, boxes, img=None):
            self.frame_id += 1
            native_id = 100 if self.frame_id <= 3 else None if self.frame_id == 4 else 101
            self.tracked_stracks = (() if native_id is None else (
                SimpleNamespace(frame_id=self.frame_id, idx=0, track_id=native_id,
                                xyxy=np.asarray(boxes.rows[0][:4], dtype=np.float32)),))

    tracker._tracker, tracker._boxes_type = Native(), Boxes
    texture = np.random.default_rng(42).integers(20, 250, (80, 40, 3), dtype=np.uint8)

    def frame(rect, when):
        image = np.zeros((240, 320, 4), dtype=np.uint8)
        image[rect.top:rect.bottom, rect.left:rect.right, :3] = texture
        image[:, :, 3] = 255
        return tracker.update((mob(rect, "unknown"),), timestamp=when,
                              raw=image.tobytes(), width=320, height=240)[0]

    old = PixelRect(20, 60, 60, 140)
    new = PixelRect(220, 60, 260, 140)
    first = [frame(old, 1. + index*.05) for index in range(3)]
    tentative = frame(new, 1.15)
    confirmed = frame(new, 1.20)
    assert len({item.track_id for item in (*first, tentative, confirmed)}) == 1
    assert "legacy_tentative" in tentative.appearance["track_association"]
    assert confirmed.appearance["tracker_backend"] == "botsort"
    assert tracker.reidentified >= 1


def test_appearance_reid_rejects_different_looking_npc_after_camera_turn():
    tracker = UltralyticsAssociationTracker(backend="botsort")
    first_rect = PixelRect(20, 60, 60, 140)
    new_rect = PixelRect(220, 60, 260, 140)

    def image(rect, seed):
        pixels = np.zeros((240, 320, 4), dtype=np.uint8)
        pixels[rect.top:rect.bottom, rect.left:rect.right, :3] = (
            np.random.default_rng(seed).integers(0, 255, (80, 40, 3), dtype=np.uint8))
        pixels[:, :, 3] = 255
        return pixels

    first_descriptor = tracker._appearance_descriptor(image(first_rect, 8), first_rect)
    other_descriptor = tracker._appearance_descriptor(image(new_rect, 37), new_rect)
    # Both are colourful, but independent random textures have similar *flat*
    # colour histograms; use a distinct channel palette as a stronger negative.
    other = image(new_rect, 37)
    other[new_rect.top:new_rect.bottom, new_rect.left:new_rect.right, 0] = 0
    other_descriptor = tracker._appearance_descriptor(other, new_rect)
    assert first_descriptor is not None and other_descriptor is not None
    tracker._last_boxes[7] = {"cx": 40., "cy": 100., "height": 80.,
                              "family": "subject", "descriptor": first_descriptor,
                              "hits": 5, "seen_at": 1.}
    assert tracker._reidentify(mob(new_rect, "unknown"), set(), timestamp=1.1,
                                descriptor=other_descriptor) is None


def test_explicit_world_invalidation_clears_reid_gallery():
    tracker = UltralyticsAssociationTracker(backend="botsort")
    tracker._last_boxes[9] = {"cx": 10., "cy": 20., "height": 40.,
                              "family": "subject", "descriptor": None,
                              "hits": 4, "seen_at": 1.}
    tracker._recently_lost[8] = {**tracker._last_boxes[9], "lost_at": 1.}
    tracker._fallback_to_public[3] = 9
    tracker.invalidate_all("loading")
    assert not tracker._last_boxes and not tracker._recently_lost
    assert not tracker._fallback_to_public


def test_established_npc_reacquires_after_two_second_camera_absence_but_not_after_expiry():
    tracker = UltralyticsAssociationTracker(backend="botsort")

    class Boxes:
        def __init__(self, rows, orig_shape):
            self.rows = rows

    class Native:
        frame_id = 0
        tracked_stracks = ()
        lost_stracks = ()
        next_id = 100

        def update(self, boxes, img=None):
            self.frame_id += 1
            self.tracked_stracks = (() if len(boxes.rows) == 0 else (
                SimpleNamespace(frame_id=self.frame_id, idx=0, track_id=self.next_id,
                                xyxy=np.asarray(boxes.rows[0][:4], dtype=np.float32)),))

    native = Native()
    tracker._tracker, tracker._boxes_type = native, Boxes
    texture = np.random.default_rng(88).integers(20, 250, (80, 40, 3), dtype=np.uint8)

    def observe(rect, when):
        pixels = np.zeros((240, 320, 4), dtype=np.uint8)
        pixels[:, :, 3] = 255
        if rect is not None:
            pixels[rect.top:rect.bottom, rect.left:rect.right, :3] = texture
        items = () if rect is None else (mob(rect, "unknown"),)
        return tracker.update(items, timestamp=when, raw=pixels.tobytes(),
                              width=320, height=240)

    old = PixelRect(20, 60, 60, 140)
    new = PixelRect(220, 60, 260, 140)
    first = None
    for index in range(4):
        first = observe(old, 1. + .05*index)[0]
    observe(None, 1.2)
    native.next_id = 101
    returned = observe(new, 3.2)[0]
    assert returned.track_id == first.track_id
    assert tracker.last_diagnostics["appearance_reid"] == "conservative_histogram_gallery"
    for index in range(12):
        observe(None, 3.3 + index*.7)
    native.next_id = 102
    expired = observe(new, 12.0)[0]
    assert expired.track_id != first.track_id


def test_appearance_gallery_does_not_guess_between_identical_npcs():
    tracker = UltralyticsAssociationTracker(backend="botsort")
    descriptor = tuple([.125] * 24)
    for public_id, cx in ((11, 30.), (12, 240.)):
        tracker._recently_lost[public_id] = {
            "cx": cx, "cy": 100., "height": 80., "family": "subject",
            "descriptor": descriptor, "hits": 5, "seen_at": 1., "lost_at": 1.}
    candidate = mob(PixelRect(130, 60, 170, 140), "unknown")
    assert tracker._reidentify(candidate, set(), timestamp=3.,
                                descriptor=descriptor) is None
