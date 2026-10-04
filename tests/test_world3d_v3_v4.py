from pathlib import Path
from concurrent.futures import Future
import threading
import time

import numpy as np
from PIL import Image

from wowbot.vision.world3d.models import PixelRect, WorldCandidate, WorldSceneROI
from wowbot.vision.world3d.ocr import TargetedOCR
from wowbot.vision.world3d.v3 import World3DPerceptionV3
from wowbot.vision.world3d.v4 import HardExampleCollector, VisionSemanticFusion
from wowbot.agent.perception import PerceptionWorker


def frame(width=320, height=240):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :, :3] = 35
    image[:, :, 3] = 255
    image[70:180, 140:180, :3] = 150
    image[82:168, 148:172, :3] = 65
    return image


class FakeOCR:
    available = True
    name = "fake_cpu_ocr"

    def read(self, image):
        assert image.width < 320 and image.height < 240
        return "Lady Jaina Proudmoore", .91


def test_v3_reuses_v2_detector_and_tracks_between_refreshes():
    pipeline = World3DPerceptionV3(detector_hz=5, ocr=TargetedOCR(FakeOCR(), interval=.2))
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    first = pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=1.)
    assert first
    assert pipeline.last_diagnostics["detector"]["version"] == "world3d_v2"
    assert pipeline.last_diagnostics["detector"]["refreshed"] is True
    ids = {item.track_id for item in first}

    shifted = np.roll(frame(), 4, axis=1)
    second = pipeline.process(shifted.tobytes(), 320, 240, scene, observed_at=1.04)
    assert second
    assert pipeline.last_diagnostics["detector"]["refreshed"] is False
    assert ids.intersection(item.track_id for item in second)
    assert any(item.appearance.get("tracking_mode") == "CPU_PATCH_PROPAGATION" for item in second)
    assert all(item.class_name is None for item in second)


def test_patch_tracker_does_not_drift_on_unchanged_frame():
    pipeline = World3DPerceptionV3(detector_hz=5)
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    first = pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=1.)
    second = pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=1.04)
    by_id = {item.track_id: item.rect for item in first}
    assert all(item.rect == by_id[item.track_id] for item in second if item.track_id in by_id)


def test_patch_tracker_follows_fast_camera_translation_beyond_old_limit():
    rng = np.random.default_rng(7)
    first_frame = rng.integers(0, 256, (240, 320, 4), dtype=np.uint8)
    first_frame[:, :, 3] = 255
    shifted_frame = np.zeros_like(first_frame)
    shifted_frame[:, 48:] = first_frame[:, :-48]
    tracker = __import__(
        "wowbot.vision.world3d.v3", fromlist=["CpuPatchTracker"]).CpuPatchTracker(4)
    candidate = WorldCandidate(
        "unknown_subject_candidate", PixelRect(100, 80, 140, 180), .8, "test")
    tracker.anchor(first_frame.tobytes(), 320, 240, (candidate,))
    second = tracker.propagate(shifted_frame.tobytes(), 320, 240)
    assert second
    assert abs(tracker.last_camera_motion["dx"]) >= 24


def test_patch_tracker_ema_smooths_detector_bbox_and_confidence_jitter():
    tracker = __import__(
        "wowbot.vision.world3d.v3", fromlist=["CpuPatchTracker"]).CpuPatchTracker(4)
    raw = frame().tobytes()
    first = WorldCandidate(
        "unknown_subject_candidate", PixelRect(100, 80, 140, 180), .8,
        "first", track_id=7)
    jittered = WorldCandidate(
        "unknown_subject_candidate", PixelRect(108, 84, 148, 184), .4,
        "second", track_id=7)

    tracker.anchor(raw, 320, 240, (first,))
    result = tracker.anchor(raw, 320, 240, (jittered,))[0]

    assert first.rect.left < result.rect.left < jittered.rect.left
    assert jittered.confidence < result.confidence < first.confidence
    assert result.appearance["temporal_smoothing"] == "EMA"


def test_detector_deadline_is_start_to_start_not_post_inference_cooldown():
    pipeline = World3DPerceptionV3(detector_hz=10)
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=1.)
    # A synchronous first refresh that consumed 80 ms should leave only the
    # remainder of the 100 ms cadence, not impose another 170 ms cooldown.
    assert pipeline.next_detector_at <= 1.101


def test_continuous_detector_resubmits_latest_frame_without_profile_cooldown():
    pipeline = World3DPerceptionV3(detector_hz=5, continuous_detector=True)
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    try:
        pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=1.)
        # The next input starts the one allowed asynchronous refresh; the
        # initial synchronous anchor is never redundantly submitted again.
        pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=1.005)
        deadline = time.monotonic() + 2.
        while (pipeline._detector_future is not None
               and not pipeline._detector_future.done()
               and time.monotonic() < deadline):
            time.sleep(.005)
        pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=1.01)
        diagnostics = pipeline.last_diagnostics["detector"]
        assert diagnostics["cadence_mode"] == "LATEST_FRAME_MAX_THROUGHPUT"
        assert diagnostics["target_hz"] == "SOURCE_RATE"
        assert diagnostics["refreshed"] is True
        assert diagnostics["in_flight"] is True
        assert diagnostics["submissions"] >= 2
        assert diagnostics["completions"] >= 2
    finally:
        pipeline.close()


def test_learned_production_pipeline_uses_botsort_association_by_default(monkeypatch):
    from wowbot.vision.world3d.tracking import UltralyticsAssociationTracker

    monkeypatch.delenv("AIPC_WORLD3D_TRACKER", raising=False)
    pipeline = World3DPerceptionV3(learned_detector=object())
    try:
        assert isinstance(pipeline.detector_tracker, UltralyticsAssociationTracker)
        assert pipeline.detector_tracker.backend == "botsort"
        tracker = pipeline.detector_tracker
        pipeline.reset()
        assert pipeline.detector_tracker is tracker
    finally:
        pipeline.close()


def test_profile_limited_detector_remains_available_as_explicit_fallback():
    pipeline = World3DPerceptionV3(detector_hz=5, continuous_detector=False)
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    try:
        pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=1.)
        diagnostics = pipeline.last_diagnostics["detector"]
        assert diagnostics["cadence_mode"] == "PROFILE_LIMITED"
        assert diagnostics["target_hz"] == 5.
        assert diagnostics["in_flight"] is False
    finally:
        pipeline.close()


def test_slow_periodic_detector_does_not_block_fast_tracker_frames():
    pipeline = World3DPerceptionV3(detector_hz=5)
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    gate = threading.Event()
    try:
        assert pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=1.)
        original = pipeline.v2.process

        def slow_detector(*args, **kwargs):
            gate.wait(2.)
            return original(*args, **kwargs)

        pipeline.v2.process = slow_detector
        pipeline.next_detector_at = 0.
        started = time.perf_counter()
        tracked = pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=2.)
        assert time.perf_counter() - started < .10
        assert tracked
        assert pipeline.last_diagnostics["detector"]["in_flight"] is True

        started = time.perf_counter()
        tracked = pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=2.04)
        assert time.perf_counter() - started < .10
        assert tracked
    finally:
        gate.set()
        pipeline.close()


def test_empty_first_detection_is_not_repeated_synchronously():
    pipeline = World3DPerceptionV3(detector_hz=5)
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    calls = 0
    gate = threading.Event()

    def empty_detector(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            gate.wait(2.)
        return ()

    pipeline.v2.process = empty_detector
    try:
        assert pipeline.process(
            frame().tobytes(), 320, 240, scene, observed_at=1.) == ()
        assert calls == 1
        pipeline.next_detector_at = 0.
        started = time.perf_counter()
        assert pipeline.process(
            frame().tobytes(), 320, 240, scene, observed_at=2.) == ()
        assert time.perf_counter() - started < .10
        assert calls == 2  # second refresh started, but did not block this call
        assert pipeline.last_diagnostics["detector"]["in_flight"] is True
    finally:
        gate.set()
        pipeline.close()


def test_empty_detector_refresh_temporally_smooths_existing_tracks():
    pipeline = World3DPerceptionV3(
        detector_hz=5, continuous_detector=False, empty_detector_grace=2)
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    raw = frame().tobytes()
    try:
        first = pipeline.process(raw, 320, 240, scene, observed_at=1.)
        assert first
        identities = {item.track_id for item in first}

        for miss in range(1, 3):
            completed = Future()
            completed.set_result((
                pipeline._generation, raw, 320, 240, (), 1.0,
                {"version": "test-empty-detector"}))
            pipeline._detector_future = completed
            smoothed = pipeline.process(
                raw, 320, 240, scene, observed_at=1. + miss * .05)
            assert smoothed
            assert identities.intersection(item.track_id for item in smoothed)
            assert all(item.appearance["detector_miss_streak"] == miss
                       for item in smoothed)
            assert pipeline.last_diagnostics["detector"]["empty_refresh_streak"] == miss

        completed = Future()
        completed.set_result((
            pipeline._generation, raw, 320, 240, (), 1.0,
            {"version": "test-empty-detector"}))
        pipeline._detector_future = completed
        expired = pipeline.process(raw, 320, 240, scene, observed_at=1.2)
        assert expired == ()
    finally:
        pipeline.close()


def test_targeted_ocr_and_scene_fusion_remain_hypotheses():
    candidate = WorldCandidate("unknown_subject_candidate", PixelRect(100, 80, 150, 180), .75,
                               track_id=17, appearance={})
    ocr = TargetedOCR(FakeOCR(), interval=.2)
    texts = ocr.process(frame().tobytes(), 320, 240, (candidate,), 1.)
    assert texts and texts[0].text == "Lady Jaina Proudmoore"
    track = {"track_id": "WORLD3D:17", "detector_kind": "unknown_subject_candidate",
             "semantic_type": "UNKNOWN", "confirmed": False,
             "appearance": {"ocr_evidence": [{"text": texts[0].text,
                                                "confidence": texts[0].confidence}]},
             "candidate_labels": [],
             "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED",
                                    "symbol_track_id": "WORLD3D:18"}]}
    symbol = {"track_id": "WORLD3D:18", "detector_kind": "unknown_symbol_candidate",
              "semantic_type": "UNKNOWN", "appearance": {}, "candidate_labels": []}
    fused = VisionSemanticFusion().enrich([track, symbol])[0]
    assert "quest_related_subject_like" in fused["candidate_labels"]
    assert fused["semantic_hypotheses"][0]["fact"] is False
    assert fused["semantic_type"] == "UNKNOWN" and fused["confirmed"] is False


def test_hard_example_collection_is_bounded_and_unlabelled(tmp_path):
    collector = HardExampleCollector(tmp_path, limit=1, cooldown=10)
    track = {"track_id": "WORLD3D:9", "detector_kind": "unknown_subject_candidate",
             "semantic_type": "UNKNOWN", "track_state": "STABLE", "confidence": .7,
             "appearance": {}, "candidate_labels": ["generic_subject_like"],
             "bbox": {"left": 100, "top": 70, "right": 150, "bottom": 180}}
    assert collector.consider(frame().tobytes(), 320, 240, [track], 1.) == 1
    assert collector.consider(frame().tobytes(), 320, 240, [track], 20.) == 0
    metadata = next(Path(tmp_path).glob("*.json")).read_text(encoding="utf-8")
    assert "UNLABELED_HARD_EXAMPLE" in metadata
    assert len(list(Path(tmp_path).glob("*.png"))) == 1


def test_hard_example_runtime_active_state_and_failure_trigger_are_collected(tmp_path):
    collector = HardExampleCollector(tmp_path, limit=2, cooldown=10)
    track = {"track_id": "WORLD3D:failure", "detector_kind": "unknown_subject_candidate",
             "semantic_type": "UNKNOWN", "track_state": "ACTIVE", "confidence": .8,
             "appearance": {"ocr_evidence": [{"text": "Murloc"}]},
             "candidate_labels": ["generic_subject_like"],
             "quest_role_penalty": {"amount": .35},
             "detection_hypotheses": {"generic": 2, "learned": 1},
             "bbox": {"left": 100, "top": 70, "right": 150, "bottom": 180}}
    assert collector.consider(frame().tobytes(), 320, 240, [track], 1.) == 1
    payload = __import__("json").loads(next(Path(tmp_path).glob("*.json")).read_text())
    assert "quest_no_credit_after_target" in payload["trigger_reasons"]
    assert "detector_disagreement" in payload["trigger_reasons"]


def test_modal_ui_uses_ui_roi_and_skips_world_detector():
    pipeline = World3DPerceptionV3(ocr=TargetedOCR(FakeOCR(), interval=.2))
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    found = pipeline.process(frame().tobytes(), 320, 240, scene, observed_at=1.,
                             ui_hints={"quest_ui_open": True})
    assert len(found) == 1
    assert found[0].kind == "unknown_ui_dialog_candidate"
    assert found[0].appearance["ocr_evidence"][0]["text"] == "Lady Jaina Proudmoore"
    assert pipeline.last_diagnostics["mode"] == "MODAL_UI"
    assert pipeline.last_diagnostics["detector"]["refreshed"] is False

    worker = PerceptionWorker(ocr=TargetedOCR(FakeOCR(), interval=.2))
    try:
        payload = worker._candidates(found, 320, 240, 1., raw=frame().tobytes())[0]
        assert payload["source"] == "UI_CV"
        assert payload["semantic_type"] == "UNKNOWN"
        assert payload["inspectable"] is False
    finally:
        worker.close()


def test_cursor_tooltip_text_survives_without_entity_candidate():
    image = np.zeros((240, 320, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    pipeline = World3DPerceptionV3(ocr=TargetedOCR(FakeOCR(), interval=.2))
    found = pipeline.process(image.tobytes(), 320, 240,
        WorldSceneROI(PixelRect(0, 0, 320, 240)), observed_at=1.,
        ui_hints={"tooltip_probe": True, "cursor_position": {"nx": .5, "ny": .5}})
    text = next(item for item in found if item.kind == "unknown_ui_text_candidate")
    assert text.appearance["ocr_evidence"][0]["text"] == "Lady Jaina Proudmoore"
    assert text.class_name is None
