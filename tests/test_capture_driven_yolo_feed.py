import time
import uuid

from wowbot.agent.capture_worker import ProcessCaptureClient
from wowbot.agent.shared_frame_buffer import SharedFrameRingBuffer
from wowbot.vision.world3d.capture_yolo_feed import FeedResult
from wowbot.vision.world3d.models import PixelRect, WorldCandidate
from wowbot.vision.world3d.scene import build_scene_roi
from wowbot.vision.world3d.v3 import World3DPerceptionV3


def _frame(value, width=64, height=48):
    return bytes([value]) * (width * height * 4), width, height


def test_status_updates_keep_frame_identity_and_client_never_loses_a_frame():
    ring = SharedFrameRingBuffer.create(name_prefix=f"t_{uuid.uuid4().hex[:10]}", max_width=64, max_height=48)
    try:
        writer = SharedFrameRingBuffer.attach(name_prefix=ring.name_prefix)
        reader = SharedFrameRingBuffer.attach(name_prefix=ring.name_prefix)
        raw, width, height = _frame(7)
        writer.write_frame(raw, width, height, "captured", time.monotonic())
        first = reader.read()
        # 120 Hz "no new frame" status overwrites the header before a reader polls.
        writer.write_status("no_new_frame", time.monotonic())
        after_status = reader.read()
        assert after_status.frame_id == first.frame_id == 1
        assert after_status.sequence != first.sequence

        class Alive:
            @staticmethod
            def is_alive():
                return True

        client = ProcessCaptureClient(Alive(), reader)
        assert client.capture() is not None          # the frame survives the status overwrite
        assert client.capture() is None              # and is not replayed as new
        writer.write_frame(*_frame(9), "captured", time.monotonic())
        writer.write_status("no_new_frame", time.monotonic())
        second = client.capture()
        assert second is not None and second[0][0] == 9
        assert client.last_frame_id == 2
        assert client.frame_for_id(1)[0][0] == 7 and client.frame_for_id(2)[0][0] == 9
        writer.close()
        reader.close()
    finally:
        ring.close()
        ring.unlink()


class _FakeFeed:
    capture_driven = True
    name = "fake_feed"
    status = "ready"
    last_diagnostics = {"backend": "fake_feed"}

    def __init__(self, anchor):
        self.anchor = anchor
        self.queue = []
        self.results_received = 0
        self.detect_calls = 0

    def poll(self):
        if not self.queue:
            return None
        self.results_received += 1
        return self.queue.pop(0)

    def frame_for_sequence(self, sequence):
        return self.anchor if sequence == 5 else None

    def feed_diagnostics(self):
        return {"mode": "CAPTURE_DRIVEN", "inference_hz": 30.}

    def detect(self, *args, **kwargs):
        self.detect_calls += 1
        raise AssertionError("feed must never be asked to detect synchronously")

    def close(self):
        pass


def test_world3d_consumes_feed_results_without_submitting_or_waiting(monkeypatch):
    monkeypatch.setenv("AIPC_WORLD3D_TRACKER", "LEGACY")
    width, height = 320, 240
    anchor = _frame(40, width, height)
    current = _frame(41, width, height)
    feed = _FakeFeed(anchor)
    world3d = World3DPerceptionV3(learned_detector=feed, proposal_mode="YOLO_ONLY")
    scene = build_scene_roi(width, height)
    try:
        # No result yet: nothing is submitted, nothing blocks.
        world3d.process(current[0], width, height, scene, observed_at=1.0)
        assert world3d._detector_future is None and world3d._detector_submissions == 0

        box = WorldCandidate("unknown_subject_candidate", PixelRect(100, 80, 140, 160), .6,
                             candidate_labels=("learned_subject_like",))
        feed.queue.append(FeedResult(5, .9, width, height, (box,), {}, 8.0, .95))
        out = world3d.process(current[0], width, height, scene, observed_at=1.05)
        detector = world3d.last_diagnostics["detector"]
        assert detector["refreshed"] is True
        assert detector["cadence_mode"] == "CAPTURE_DRIVEN_FEED"
        assert detector["feed"]["mode"] == "CAPTURE_DRIVEN"
        assert world3d._detector_future is None
        assert feed.detect_calls == 0
        assert any(item.kind == "unknown_subject_candidate" for item in out)
    finally:
        world3d.close()


class _TrackedFeed(_FakeFeed):
    def __init__(self, anchor):
        super().__init__(anchor)
        self.generation = 0
        self.resets = 0
        self.pipeline = None

    def start_pipeline(self, **pipeline):
        self.pipeline = pipeline

    def reset(self):
        self.resets += 1
        self.generation += 1


def test_world3d_uses_feed_association_and_discards_old_generation(monkeypatch):
    monkeypatch.setenv("AIPC_WORLD3D_TRACKER", "AUTO")
    width, height = 320, 240
    anchor = _frame(40, width, height)
    current = _frame(41, width, height)
    feed = _TrackedFeed(anchor)
    world3d = World3DPerceptionV3(learned_detector=feed, proposal_mode="YOLO_ONLY")
    scene = build_scene_roi(width, height)
    try:
        # The feed process owns association; World3D is told its pipeline.
        assert feed.pipeline == {"proposal_mode": "YOLO_ONLY", "tracker_mode": "auto"}

        def fail_update(*args, **kwargs):
            raise AssertionError("pre-tracked results must not be re-associated")
        monkeypatch.setattr(world3d.detector_tracker, "update", fail_update)
        box = WorldCandidate("unknown_subject_candidate", PixelRect(100, 80, 140, 160), .6,
                             track_id=17, candidate_labels=("learned_subject_like",))
        feed.queue.append(FeedResult(5, .9, width, height, (box,), {"version": "world3d_v2"},
                                     8.0, .95, 1, 0, True, {"backend": "botsort", "status": "ready"}))
        out = world3d.process(current[0], width, height, scene, observed_at=1.0)
        detector = world3d.last_diagnostics["detector"]
        assert detector["refreshed"] is True
        assert world3d.last_diagnostics["tracker"]["detector_association"]["backend"] == "botsort"
        assert [item.track_id for item in out if item.kind == "unknown_subject_candidate"] == [17]

        world3d.reset()
        assert feed.resets == 1 and feed.generation == 1
        # A result produced before the reset belongs to the old context.
        feed.queue.append(FeedResult(6, 1.0, width, height, (box,), {}, 8.0, 1.05, 2, 0, True, {}))
        world3d.process(current[0], width, height, scene, observed_at=1.1)
        assert world3d.last_diagnostics["detector"]["refreshed"] is False
    finally:
        world3d.close()


def test_prescaled_gmc_uses_quarter_resolution_gray_and_keeps_fallback():
    import numpy as np
    from wowbot.vision.world3d.tracking import _PrescaledTranslationGMC

    class Fallback:
        method = "sparseOptFlow"
        downscale = 4

        def __init__(self):
            self.applied = 0
            self.resets = 0

        def apply(self, raw_frame, detections=None):
            self.applied += 1
            return np.eye(2, 3)

        def reset_params(self):
            self.resets += 1

    rng = np.random.default_rng(3)
    base = rng.random((140, 240)).astype(np.float32) * 255
    import cv2
    base = cv2.GaussianBlur(base, (7, 7), 2)
    shifted = np.roll(base, (2, 5), axis=(0, 1))
    fallback = Fallback()
    gmc = _PrescaledTranslationGMC(fallback)
    gmc.downscale = 2
    assert fallback.downscale == 2 and gmc.method == "sparseOptFlow"
    gmc.set_frame(base, 4)
    assert np.allclose(gmc.apply(None), np.eye(2, 3))          # first frame: identity
    gmc.set_frame(shifted, 4)
    warp = gmc.apply(None)
    assert abs(warp[0, 2] - 20) < 1.5 and abs(warp[1, 2] - 8) < 1.5   # 4x the gray shift
    assert fallback.applied == 0
    # A frame without the prescaled gray uses the original estimator.
    gmc.apply(np.zeros((10, 10, 3), np.uint8))
    assert fallback.applied == 1


def test_prescaled_gmc_ignores_screen_fixed_strip_hud_and_avatar():
    """Live 2026-09-30: camera turns moved detections 20-100 px/frame while
    GMC reported ~1 px, because the static AIPC strip / HUD / orbit-centre
    avatar dominated the whole-frame correlation."""
    import cv2
    import numpy as np
    from wowbot.vision.world3d.tracking import _PrescaledTranslationGMC

    class Fallback:
        method, downscale = "sparseOptFlow", 4

        def apply(self, raw_frame, detections=None):
            return np.eye(2, 3)

        def reset_params(self):
            pass

    rng = np.random.default_rng(11)
    h, w = 118, 210                                    # 843x475 client / 4
    world = cv2.GaussianBlur((rng.random((h, w)) * 255).astype(np.float32), (5, 5), 1.5)
    strip = np.kron(rng.integers(0, 2, (5, 20)), np.ones((4, 4))).astype(np.float32) * 255

    def frame(shift):
        image = np.roll(world, shift, axis=1).copy()
        image[:20, :80] = strip                        # AIPC pixel strip
        image[92:] = 40.                               # action bars
        image[55:80, 100:110] = 220.                   # avatar at the orbit centre
        return image

    for shift, expected in ((0, 0.), (6, 24.), (15, 60.)):
        gmc = _PrescaledTranslationGMC(Fallback())
        gmc.set_frame(frame(0), 4)
        gmc.apply(None)
        gmc.set_frame(frame(shift), 4)
        warp = gmc.apply(None)
        assert abs(warp[0, 2] - expected) < 2.5, (shift, warp)
        assert abs(warp[1, 2]) < 2.5


def test_world_motion_running_while_turning_is_a_similarity_not_identity():
    """Live 2026-09-30 20:22: running + turning made the two world crops
    disagree (expansion), so the warp fell back to identity mid-turn."""
    import cv2
    import numpy as np
    from wowbot.vision.world3d.camera_motion import WorldCameraMotion

    rng = np.random.default_rng(5)
    h, w = 118, 210
    world = cv2.GaussianBlur((rng.random((h, w)) * 255).astype(np.float32), (5, 5), 1.5)
    scale, shift = 1.05, 5.
    matrix = np.float32([[scale, 0, (1-scale)*w/2 + shift], [0, scale, (1-scale)*h/2]])
    moved = cv2.warpAffine(world, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)
    hypotheses = WorldCameraMotion().hypotheses(world, moved)
    best = hypotheses[0]
    assert best.name == "similarity"
    assert abs(best.scale - scale) < .02
    cx, _ = best.shift_at(w/2, h/2)
    assert abs(cx - shift) < 1.5


def test_detections_choose_between_disagreeing_crop_hypotheses():
    from wowbot.vision.world3d.camera_motion import MotionHypothesis, select_by_detections

    # One crop locked onto the static near ground, the other on far scenery
    # that moved 10 gray px (= 40 client px at step 4) like the NPCs did.
    hypotheses = [MotionHypothesis("mean", 1., 5., 0., .5),
                  MotionHypothesis("left", 1., 0., 0., .7),
                  MotionHypothesis("right", 1., 10., 0., .4),
                  MotionHypothesis("identity", 1., 0., 0., 0.)]
    previous = [(100, 200, 130, 280), (400, 210, 425, 270)]
    current = [(140, 200, 170, 280), (440, 210, 465, 270)]
    chosen, support = select_by_detections(hypotheses, previous, current, 4)
    assert chosen.name == "right" and support == 2
    # Without detections the default (first) hypothesis is used.
    assert select_by_detections(hypotheses, [], current, 4)[0].name == "mean"


def test_low_confidence_static_detection_keeps_its_track_id():
    from wowbot.vision.world3d.tracking import UltralyticsAssociationTracker

    tracker = UltralyticsAssociationTracker(backend="botsort", warmup_in_background=False)
    # Typical admitted scores of the live detector: a weak overhead symbol
    # and a mid-confidence subject jittering by a few pixels.
    ids = []
    for frame in range(45):
        jitter = frame % 3
        candidates = (
            WorldCandidate("unknown_symbol_candidate", PixelRect(557, 30, 567, 44), .014,
                           candidate_labels=("learned_symbol_like",)),
            WorldCandidate("unknown_subject_candidate",
                           PixelRect(548 + jitter, 107, 575 + jitter, 145), .19,
                           candidate_labels=("learned_subject_like",)),
        )
        output = tracker.update(candidates, timestamp=frame / 27, width=906, height=510)
        ids.append(tuple(sorted(item.track_id for item in output)))
    assert tracker.last_diagnostics.get("score_fusion") is False
    assert len(set(ids[1:])) == 1


def test_capture_feed_scans_full_frame_by_default(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import wowbot.vision.world3d.capture_yolo_feed as feed_module
    from wowbot.vision.world3d.learned_detector import build_runtime_learned_detector

    seen = {}

    class RecordingFeed:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(feed_module, "CaptureDrivenYoloFeed", RecordingFeed)
    monkeypatch.delenv("AIPC_YOLO_FEED_ADAPTIVE_SAMPLING", raising=False)
    model = tmp_path / "model.pt"
    model.write_bytes(b"x")
    handle = SimpleNamespace(client=SimpleNamespace(ring_name="ring", frame_for_id=lambda _: None))
    build_runtime_learned_detector(model, capture_handle=handle)
    assert seen["detector_kwargs"]["adaptive_sampling"] is False
    monkeypatch.setenv("AIPC_YOLO_FEED_ADAPTIVE_SAMPLING", "1")
    build_runtime_learned_detector(model, capture_handle=handle)
    assert seen["detector_kwargs"]["adaptive_sampling"] is True


def test_ring_carries_capture_side_decoded_telemetry_to_the_pixel_sensor():
    from wowbot.agent.sensor import PixelSensor
    from wowbot.agent.shared_frame_buffer import PAYLOAD_DECODED, PAYLOAD_NOT_VISIBLE

    ring = SharedFrameRingBuffer.create(name_prefix=f"t_{uuid.uuid4().hex[:10]}", max_width=64, max_height=48)
    try:
        writer = SharedFrameRingBuffer.attach(name_prefix=ring.name_prefix)
        reader = SharedFrameRingBuffer.attach(name_prefix=ring.name_prefix)

        class Alive:
            @staticmethod
            def is_alive():
                return True

        client = ProcessCaptureClient(Alive(), reader)
        sensor = PixelSensor(client)
        writer.write_frame(*_frame(7), "captured", time.monotonic(),
                           payload="1600x900:fallback", payload_state=PAYLOAD_NOT_VISIBLE)
        assert sensor.poll(time.monotonic()) is None
        assert sensor.health == "pixel_strip_not_visible:1600x900:fallback"
        # The main process never decodes the strip itself: a decoded packet
        # from the capture side reaches the assembler unchanged.
        writer.write_frame(*_frame(8), "captured", time.monotonic(),
                           payload="AIPC5|s|1|FAST|1|1|{}", payload_state=PAYLOAD_DECODED)
        client_frame = client.capture()
        assert client_frame is not None and client.last_decoded == ("AIPC5|s|1|FAST|1|1|{}", PAYLOAD_DECODED)
        writer.close()
        reader.close()
    finally:
        ring.close()
        ring.unlink()


def test_botsort_drives_world_gmc_with_numpy_detections_without_fallback():
    """Live 2026-10-01: BoT-SORT passes ``results_high.xyxy`` (numpy) to the
    GMC; ``boxes or ()`` raised, Ultralytics logged "GMC failed" and used
    identity, so camera turns produced new ids again."""
    import cv2
    import numpy as np
    from wowbot.vision.world3d.tracking import UltralyticsAssociationTracker

    rng = np.random.default_rng(9)
    gray = cv2.GaussianBlur((rng.random((118, 210)) * 255).astype(np.float32), (5, 5), 1.5)
    tracker = UltralyticsAssociationTracker(backend="botsort", warmup_in_background=False)
    raw = bytes(843 * 475 * 4)
    ids = []
    for frame in range(8):
        shift = 6 * frame                                   # 24 client px per frame
        candidates = (WorldCandidate("unknown_subject_candidate",
                                     PixelRect(300 + 4*shift, 200, 340 + 4*shift, 300), .8,
                                     candidate_labels=("learned_subject_like",)),)
        output = tracker.update(candidates, timestamp=frame / 30, raw=raw, width=843,
                                height=475, gray=np.roll(gray, shift, axis=1), gray_step=4)
        ids.extend(item.track_id for item in output if item.track_id is not None)
    gmc = tracker._tracker.gmc
    assert gmc.last_hypothesis is not None and gmc.last_detection_support >= 0
    assert abs(gmc.last_warp[0] - 24) < 3
    assert len(set(ids)) == 1


def test_screen_fixed_avatar_and_world_npc_both_keep_ids_through_a_turn():
    """Live 2026-10-01 (PID 4588, running around an NPC): once GMC measured
    the turns, BoT-SORT warped the screen-fixed avatar's prediction away from
    its box and the avatar changed id 12 times in 94 s."""
    import cv2
    import numpy as np
    from wowbot.vision.world3d.tracking import UltralyticsAssociationTracker

    rng = np.random.default_rng(13)
    gray = cv2.GaussianBlur((rng.random((118, 210)) * 255).astype(np.float32), (5, 5), 1.5)
    tracker = UltralyticsAssociationTracker(backend="botsort", warmup_in_background=False)
    raw = bytes(843 * 475 * 4)
    avatar_ids, npc_ids = set(), set()
    for frame in range(12):
        shift = 6 * frame                                   # world: 24 client px per frame
        avatar = WorldCandidate("unknown_subject_candidate", PixelRect(395, 225, 448, 370), .6,
                                candidate_labels=("learned_subject_like",))
        npc = WorldCandidate("unknown_subject_candidate",
                             PixelRect(120 + 4*shift, 170, 150 + 4*shift, 230), .5,
                             candidate_labels=("learned_subject_like",))
        output = tracker.update((avatar, npc), timestamp=frame / 30, raw=raw, width=843,
                                height=475, gray=np.roll(gray, shift, axis=1), gray_step=4)
        if output[0].track_id is not None:
            avatar_ids.add(output[0].track_id)
        if output[1].track_id is not None:
            npc_ids.add(output[1].track_id)
    assert len(avatar_ids) == 1, avatar_ids
    assert len(npc_ids) == 1, npc_ids
    assert avatar_ids != npc_ids
    assert tracker.last_diagnostics["screen_anchored"] == 1


def test_detection_shift_wins_only_when_no_image_hypothesis_explains_the_boxes():
    from wowbot.vision.world3d.camera_motion import MotionHypothesis, select_by_detections

    # Live 49.49 s: one crop said -58 px, the NPC box moved +66 px.
    wrong = [MotionHypothesis("single", 1., -58/4, -17/4, .3),
             MotionHypothesis("identity", 1., 0., 0., 0.)]
    previous = [(364, 109, 421, 190)]
    current = [(430, 112, 489, 189)]
    chosen, support = select_by_detections(wrong, previous, current, 4)
    assert chosen.name == "detections" and support == 1
    assert abs(chosen.tx*4 - 67) < 1
    # An image hypothesis that explains the same boxes keeps priority.
    right = [MotionHypothesis("left", 1., 66/4, 0., .6)] + wrong
    assert select_by_detections(right, previous, current, 4)[0].name == "left"


def test_feed_never_publishes_one_id_twice_in_a_frame_with_avatar_dropouts():
    """Live 2026-10-01 06:45: a world box inherited the legacy-bridge id that
    the anchored avatar already used, so two boxes carried "V3:5"."""
    import cv2
    import numpy as np
    from wowbot.vision.world3d.tracking import UltralyticsAssociationTracker

    rng = np.random.default_rng(21)
    gray = cv2.GaussianBlur((rng.random((118, 210)) * 255).astype(np.float32), (5, 5), 1.5)
    tracker = UltralyticsAssociationTracker(backend="botsort", warmup_in_background=False)
    raw = bytes(843 * 475 * 4)
    avatar_ids = set()
    for frame in range(40):
        shift = (3 * frame) % 40
        boxes = []
        if frame % 5 != 2:                                   # avatar detector dropouts
            boxes.append(WorldCandidate("unknown_subject_candidate", PixelRect(395, 225, 448, 370),
                                        .6, candidate_labels=("learned_subject_like",)))
        for left in (120, 520, 330):                         # world subjects, one near the avatar
            boxes.append(WorldCandidate("unknown_subject_candidate",
                                        PixelRect(left + 4*shift, 170, left + 30 + 4*shift, 240),
                                        .45, candidate_labels=("learned_subject_like",)))
        output = tracker.update(tuple(boxes), timestamp=frame / 30, raw=raw, width=843,
                                height=475, gray=np.roll(gray, shift, axis=1), gray_step=4)
        ids = [item.track_id for item in output if item.track_id is not None]
        assert len(ids) == len(set(ids)), (frame, ids)
        if frame % 5 != 2:
            avatar_ids.add(output[0].track_id)
    assert len(avatar_ids) == 1, avatar_ids


def test_one_frame_jump_and_long_avatar_dropout_keep_their_ids():
    """Live 2026-10-01 (PID 1712): most NPC re-births happened within one
    frame (the lost id was not yet "recently lost"), several jumped 1.2-1.4
    box heights, and the avatar was missed by the detector for 1-7 s."""
    import cv2
    import numpy as np
    from wowbot.vision.world3d.tracking import UltralyticsAssociationTracker

    rng = np.random.default_rng(17)
    gray = cv2.GaussianBlur((rng.random((118, 210)) * 255).astype(np.float32), (5, 5), 1.5)
    tracker = UltralyticsAssociationTracker(backend="botsort", warmup_in_background=False)
    raw = bytes(843 * 475 * 4)

    def frame(index, avatar=True, npc_left=150):
        boxes = []
        if avatar:
            boxes.append(WorldCandidate("unknown_subject_candidate", PixelRect(395, 225, 448, 370),
                                        .6, candidate_labels=("learned_subject_like",)))
        boxes.append(WorldCandidate("unknown_subject_candidate",
                                    PixelRect(npc_left, 150, npc_left + 40, 230), .55,
                                    candidate_labels=("learned_subject_like",)))
        output = tracker.update(tuple(boxes), timestamp=index / 30, raw=raw, width=843,
                                height=475, gray=gray, gray_step=4)
        return (output[0].track_id if avatar else None), output[-1].track_id

    avatar_ids, npc_ids = set(), set()
    index = 0
    for _ in range(10):
        a, n = frame(index); avatar_ids.add(a); npc_ids.add(n); index += 1
    # The NPC box jumps 1.3 box heights (104 px) in a single frame.
    for _ in range(5):
        a, n = frame(index, npc_left=254); avatar_ids.add(a); npc_ids.add(n); index += 1
    # The avatar is not detected for 3 s.
    for _ in range(90):
        _, n = frame(index, avatar=False, npc_left=254); npc_ids.add(n); index += 1
    for _ in range(5):
        a, n = frame(index, npc_left=254); avatar_ids.add(a); npc_ids.add(n); index += 1
    assert len(npc_ids) == 1, npc_ids
    assert len(avatar_ids) == 1, avatar_ids


def test_dead_feed_process_is_restarted_and_its_error_reported(monkeypatch):
    # Live 2026-10-04 18:05: the feed process died at start-up, the agent saw
    # nothing for the whole run and the status only said "error".
    from wowbot.vision.world3d.capture_yolo_feed import CaptureDrivenYoloFeed
    feed = CaptureDrivenYoloFeed(model_config={"model_path": "m.engine"}, detector_kwargs={},
                                 capture_ring="x")
    started = []

    class Dead:
        exitcode = 1

        def is_alive(self):
            return False

        def join(self, timeout=None):
            return None

    monkeypatch.setattr(feed, "start_pipeline", lambda **kw: started.append(kw) or setattr(feed, "_process", Dead()))
    feed._process = Dead()
    feed._poll_status()
    diagnostics = feed.feed_diagnostics()
    assert started and feed.restarts == 1
    assert diagnostics["restarts"] == 1 and diagnostics["last_failure"] == "yolo_feed_process_exited:1"
    feed._poll_status()                     # within the 10 s spacing: no second restart yet
    assert feed.restarts == 1
    feed.close()
