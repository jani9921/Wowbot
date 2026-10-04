"""Unified V2 detector + high-rate CPU tracker + targeted OCR."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import hashlib
import math
import os
import time

try:
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:
    from adapters.numpy_runtime import np

from .models import PixelRect, WorldCandidate, WorldSceneROI
from .ocr import TargetedOCR, TextObservation
from .tracking import UltralyticsAssociationTracker, WorldCandidateTracker
from .v2 import World3DPerceptionV2
from .learned_detector import LearnedWorldDetector
from ..opencv_backend import OpenCvComputeBackend, create_opencv_backend


def build_detector_tracker(mode: str, *, learned_tracking_enabled: bool,
                           warmup_in_background: bool = True):
    """Detector-rate association tracker (shared by V3 and the YOLO feed process)."""
    mode = str(mode).strip().lower().replace("-", "")
    if mode == "auto":
        mode = "botsort" if learned_tracking_enabled else "legacy"
    if mode in {"botsort", "bytetrack"}:
        return UltralyticsAssociationTracker(
            backend=mode,
            track_buffer=int(os.getenv("AIPC_WORLD3D_TRACK_BUFFER", "30")),
            gmc_method=os.getenv("AIPC_WORLD3D_GMC", "sparseOptFlow"),
            gmc_downscale=int(os.getenv("AIPC_WORLD3D_GMC_DOWNSCALE", "4")),
            warmup_in_background=warmup_in_background,
        )
    if mode != "legacy":
        raise ValueError(
            "AIPC_WORLD3D_TRACKER must be AUTO, BOTSORT, BYTETRACK or LEGACY")
    return WorldCandidateTracker(max_misses=8)


class CpuPatchTracker:
    """Propagate UNKNOWN tracks between expensive detector refreshes."""

    def __init__(self, downsample: int = 4,
                 compute_backend: OpenCvComputeBackend | None = None):
        self.downsample = max(2, int(downsample))
        self.compute_backend = compute_backend
        self.bbox_ema_alpha = max(.05, min(1., float(os.getenv(
            "AIPC_WORLD3D_BBOX_EMA_ALPHA", ".75"))))
        self.confidence_ema_alpha = max(.05, min(1., float(os.getenv(
            "AIPC_WORLD3D_CONFIDENCE_EMA_ALPHA", ".35"))))
        self.previous: np.ndarray | None = None
        self.candidates: tuple[WorldCandidate, ...] = ()
        self.last_camera_motion = {"dx": 0, "dy": 0, "confidence": 0.0}
        self.last_timings_ms = {"gray": 0.0, "camera": 0.0, "patches": 0.0,
                                "total": 0.0}

    def reset(self):
        self.previous = None
        self.candidates = ()
        self.last_camera_motion = {"dx": 0, "dy": 0, "confidence": 0.0}
        self.last_timings_ms = {"gray": 0.0, "camera": 0.0, "patches": 0.0,
                                "total": 0.0}

    def gray(self, raw: bytes, width: int, height: int) -> np.ndarray:
        return World3DPerceptionV2._gray(
            raw, width, height, self.downsample, self.compute_backend)

    def anchor(self, raw: bytes, width: int, height: int,
               candidates: tuple[WorldCandidate, ...], *,
               gray: np.ndarray | None = None) -> tuple[WorldCandidate, ...]:
        started = time.perf_counter()
        previous_by_id = {
            candidate.track_id: candidate for candidate in self.candidates
            if candidate.track_id is not None
        }
        smoothed: list[WorldCandidate] = []
        for candidate in candidates:
            previous = previous_by_id.get(candidate.track_id)
            if previous is None or previous.kind != candidate.kind:
                smoothed.append(candidate)
                continue
            old_cx = (previous.rect.left + previous.rect.right) / 2
            old_cy = (previous.rect.top + previous.rect.bottom) / 2
            new_cx = (candidate.rect.left + candidate.rect.right) / 2
            new_cy = (candidate.rect.top + candidate.rect.bottom) / 2
            jump = math.hypot(new_cx-old_cx, new_cy-old_cy)
            old_scale = max(1., previous.rect.width, previous.rect.height)
            scale_ratio = max(
                candidate.rect.width / max(1., previous.rect.width),
                previous.rect.width / max(1., candidate.rect.width),
                candidate.rect.height / max(1., previous.rect.height),
                previous.rect.height / max(1., candidate.rect.height),
            )
            # Smooth ordinary detector jitter. A large displacement/scale jump
            # is probably camera motion or a questionable reassociation; using
            # the fresh box avoids a visible and actionable trailing bbox.
            if jump > max(24., old_scale*1.25) or scale_ratio > 2.2:
                smoothed.append(candidate)
                continue
            alpha = self.bbox_ema_alpha
            rect = PixelRect(
                round(alpha*candidate.rect.left + (1-alpha)*previous.rect.left),
                round(alpha*candidate.rect.top + (1-alpha)*previous.rect.top),
                round(alpha*candidate.rect.right + (1-alpha)*previous.rect.right),
                round(alpha*candidate.rect.bottom + (1-alpha)*previous.rect.bottom),
            )
            conf_alpha = self.confidence_ema_alpha
            confidence = (conf_alpha*candidate.confidence
                          + (1-conf_alpha)*previous.confidence)
            appearance = {
                **candidate.appearance,
                "temporal_smoothing": "EMA",
                "bbox_ema_alpha": self.bbox_ema_alpha,
                "confidence_ema_alpha": self.confidence_ema_alpha,
            }
            smoothed.append(replace(
                candidate, rect=rect, confidence=confidence,
                appearance=appearance))
        # ``gray`` is V2's identical luminance of this exact frame when the
        # caller already has it (same downsample and compute backend).
        self.previous = gray if gray is not None else self.gray(raw, width, height)
        self.candidates = tuple(smoothed)
        elapsed = (time.perf_counter() - started) * 1000
        self.last_timings_ms = {"gray": round(elapsed, 3), "camera": 0.0,
                                "patches": 0.0, "total": round(elapsed, 3)}
        return self.candidates

    def propagate(self, raw: bytes, width: int, height: int) -> tuple[WorldCandidate, ...]:
        total_started = time.perf_counter()
        stage_started = total_started
        current = self.gray(raw, width, height)
        gray_ms = (time.perf_counter() - stage_started) * 1000
        if self.previous is None or self.previous.shape != current.shape or not self.candidates:
            self.previous = current
            total_ms = (time.perf_counter() - total_started) * 1000
            self.last_timings_ms = {"gray": round(gray_ms, 3), "camera": 0.0,
                                    "patches": 0.0, "total": round(total_ms, 3)}
            return ()
        stage_started = time.perf_counter()
        # Fast camera turns routinely move the scene by more than the old
        # fixed ten correlation cells.  Phase correlation already gives us a
        # confidence score, so permit a wider transform here and reject it on
        # confidence instead of silently freezing every track during a turn.
        camera_limit = max(10, min(current.shape) // 4)
        dx, dy, camera_conf = World3DPerceptionV2._camera_translation(
            self.previous, current, limit=camera_limit)
        camera_ms = (time.perf_counter() - stage_started) * 1000
        step = self.downsample
        self.last_camera_motion = {"dx": dx*step, "dy": dy*step,
                                   "confidence": round(camera_conf, 4)}
        output = []
        stage_started = time.perf_counter()
        for candidate in self.candidates:
            rect = candidate.rect
            x0, x1 = rect.left//step, max(rect.left//step+2, math.ceil(rect.right/step))
            y0, y1 = rect.top//step, max(rect.top//step+2, math.ceil(rect.bottom/step))
            reference = self.previous[max(0, y0):min(self.previous.shape[0], y1),
                                      max(0, x0):min(self.previous.shape[1], x1)]
            # The avatar the camera orbits does not move with the scene.
            base_x, base_y = ((0, 0) if candidate.appearance.get("screen_anchored")
                              else (dx, dy))
            best = (float("inf"), base_x, base_y)
            if reference.size >= 16:
                ref = reference.astype(np.float32) - float(reference.mean())
                # Global translation cannot model all perspective/parallax
                # produced by a WoW camera turn.  Search a wider residual
                # neighbourhood so a tracked NPC does not disappear merely
                # because it moved more than eight screen pixels between
                # admitted frames.  The downsampled patches keep this cheap.
                residual_offsets = (-6, -3, 0, 3, 6)
                for oy in residual_offsets:
                    for ox in residual_offsets:
                        nx0, ny0 = x0+base_x+ox, y0+base_y+oy
                        nx1, ny1 = nx0+reference.shape[1], ny0+reference.shape[0]
                        if nx0 < 0 or ny0 < 0 or nx1 > current.shape[1] or ny1 > current.shape[0]:
                            continue
                        patch = current[ny0:ny1, nx0:nx1].astype(np.float32)
                        patch -= float(patch.mean())
                        error = float(np.mean(np.abs(ref-patch))) / 64.0
                        # Equal/flat matches must prefer the camera prediction;
                        # otherwise iteration order would drift a static track.
                        cost = error + .002*math.hypot(ox, oy)
                        if cost < best[0]:
                            best = (cost, base_x+ox, base_y+oy)
            quality = max(0.0, min(1.0, 1.0-best[0])) if math.isfinite(best[0]) else 0.0
            shift_x, shift_y = int(best[1]*step), int(best[2]*step)
            moved = PixelRect(max(0, rect.left+shift_x), max(0, rect.top+shift_y),
                              min(width, rect.right+shift_x), min(height, rect.bottom+shift_y))
            appearance = {**candidate.appearance,
                "tracking_mode": "CPU_PATCH_PROPAGATION", "detector_refresh": False,
                "patch_match_quality": round(quality, 4),
                "camera_motion_dx": shift_x, "camera_motion_dy": shift_y,
                "camera_motion_confidence": round(camera_conf, 4)}
            output.append(replace(candidate, rect=moved,
                confidence=max(.25, candidate.confidence*(.97 + .02*quality)),
                appearance=appearance,
                evidence=f"{candidate.evidence}; frame_to_frame_patch_track"))
        self.previous = current
        self.candidates = tuple(output)
        patches_ms = (time.perf_counter() - stage_started) * 1000
        total_ms = (time.perf_counter() - total_started) * 1000
        self.last_timings_ms = {
            "gray": round(gray_ms, 3), "camera": round(camera_ms, 3),
            "patches": round(patches_ms, 3), "total": round(total_ms, 3),
        }
        return self.candidates


class World3DPerceptionV3:
    """Single perception stack; V2 is the detector, not a competing pipeline."""

    def __init__(self, *, detector_hz: float = 5., ocr=None,
                 compute_backend: OpenCvComputeBackend | None = None,
                 learned_detector: LearnedWorldDetector | None = None,
                 proposal_mode: str = "HYBRID",
                 continuous_detector: bool | None = None,
                 empty_detector_grace: int | None = None):
        self.compute_backend = (compute_backend if compute_backend is not None
                                else create_opencv_backend())
        self.v2 = World3DPerceptionV2(
            compute_backend=self.compute_backend,
            learned_detector=learned_detector,
            proposal_mode=proposal_mode,
        )
        # Detector refreshes are intentionally slower than the patch tracker.
        # Do not retire an UNKNOWN detector identity after only three missing
        # refreshes: a body can flicker behind foliage/nameplates while its
        # CPU patch track remains useful, and the presentation tracker relies
        # on this upstream id to reacquire it without creating a new subject.
        # Missing tracks are not emitted as inspectable candidates.
        self._learned_tracking_enabled = learned_detector is not None
        self.detector_tracker_mode = str(os.getenv(
            "AIPC_WORLD3D_TRACKER", "AUTO")).strip().lower().replace("-", "")
        self.detector_tracker = self._build_detector_tracker()
        self.fast_tracker = CpuPatchTracker(
            self.v2.downsample, compute_backend=self.compute_backend)
        self.ocr = ocr or TargetedOCR()
        self.detector_interval = 1.0/max(1., min(15., detector_hz))
        # The learned detector owns a single-in-flight latest-frame stream.
        # There is therefore no stale queue to protect with a second 8-15 Hz
        # cooldown.  By default, submit the newest frame as soon as the prior
        # refresh completes; canonical evidence publication remains separately
        # rate-limited by PerceptionWorker.  The environment switch keeps a
        # reversible legacy cadence for diagnosis and low-power hosts.
        if continuous_detector is None:
            continuous_detector = str(os.getenv(
                "AIPC_WORLD3D_CONTINUOUS_DETECTOR", "1")).strip().lower() not in {
                    "0", "false", "no", "off"}
        self.continuous_detector = bool(continuous_detector)
        if empty_detector_grace is None:
            empty_detector_grace = int(os.getenv(
                "AIPC_WORLD3D_EMPTY_REFRESH_GRACE", "8"))
        self.empty_detector_grace = max(0, int(empty_detector_grace))
        self._empty_detector_refreshes = 0
        self.next_detector_at = 0.0
        self.frame_index = 0
        self.last_text: tuple[TextObservation, ...] = ()
        self.last_diagnostics: dict[str, object] = {}
        self._detector_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="aipc-world3d-detector")
        self._detector_future: Future | None = None
        self._generation = 0
        self._pending_v2_reset = False
        self._initial_detection_complete = False
        self._last_detector_diagnostics: dict[str, object] = {}
        self._last_detector_ms: float | None = None
        self._last_detector_started_at: float | None = None
        self._detector_submissions = 0
        self._detector_completions = 0
        self._detector_busy_frames = 0
        self._feed_tracker_diagnostics: dict[str, object] = {}
        feed = self._capture_feed()
        if feed is not None and callable(getattr(feed, "start_pipeline", None)):
            feed.start_pipeline(proposal_mode=self.v2.proposal_mode,
                                tracker_mode=self.detector_tracker_mode)

    def _build_detector_tracker(self):
        if self._capture_feed() is not None:
            # The capture-driven feed process owns detector-rate association
            # (every YOLO result, not only those World3D happens to take).
            # This instance only covers untracked results from custom feeds.
            return WorldCandidateTracker(max_misses=8)
        return build_detector_tracker(
            self.detector_tracker_mode,
            learned_tracking_enabled=self._learned_tracking_enabled)

    def reset(self):
        self._generation += 1
        if self._detector_future is None:
            self.v2.reset()
            self._pending_v2_reset = False
        else:
            # V2 is owned by the detector worker while a refresh is running.
            # Defer its mutable reset and discard the old-generation result.
            self._pending_v2_reset = True
        reset_detector_tracker = getattr(self.detector_tracker, "reset", None)
        if callable(reset_detector_tracker):
            reset_detector_tracker()
        else:
            self.detector_tracker = self._build_detector_tracker()
        feed = self._capture_feed()
        if feed is not None and callable(getattr(feed, "reset", None)):
            # New generation: the feed resets its V2/association state and
            # results of the old generation are discarded on arrival.
            feed.reset()
        self._feed_tracker_diagnostics = {}
        self.fast_tracker.reset()
        self.next_detector_at = 0.0
        self.frame_index = 0
        self.last_text = ()
        self.last_diagnostics = {}
        self._initial_detection_complete = False
        self._last_detector_started_at = None
        self._detector_submissions = 0
        self._detector_completions = 0
        self._detector_busy_frames = 0
        self._empty_detector_refreshes = 0

    def close(self) -> None:
        self._generation += 1
        self._detector_pool.shutdown(wait=False, cancel_futures=True)
        close_detector = getattr(self.v2.learned_detector, "close", None)
        if callable(close_detector):
            close_detector()

    def _capture_feed(self):
        detector = self.v2.learned_detector
        return detector if getattr(detector, "capture_driven", False) else None

    def _anchor_gray(self, width: int, height: int):
        """V2's luminance of the refresh anchor, reused instead of recomputed.

        Called only after V2 processed that anchor and before another V2 job
        can start (single in-flight detector / synchronous feed path).
        """
        gray = self.v2.previous_gray
        step = self.v2.downsample
        expected = ((height + step - 1) // step, (width + step - 1) // step)
        return gray if gray is not None and tuple(gray.shape) == expected else None

    def _detect(self, raw: bytes, width: int, height: int,
                scene: WorldSceneROI, generation: int):
        started = time.perf_counter()
        detected = self.v2.process(raw, width, height, scene)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return (generation, raw, width, height, tuple(detected), elapsed_ms,
                deepcopy(self.v2.last_diagnostics))

    def process(self, raw: bytes, width: int, height: int, scene: WorldSceneROI,
                *, observed_at: float = 0.0, ui_hints: dict | None = None) -> tuple[WorldCandidate, ...]:
        process_started = time.perf_counter()
        self.frame_index += 1
        ui_hints = ui_hints or {}
        profile = ui_hints.get("world3d_profile") or {}
        profile_detector_hz = float(profile.get("detector_hz") or (1./self.detector_interval))
        profile_detector_interval = 1./max(1., min(15., profile_detector_hz))
        schedule_interval = 0. if self.continuous_detector else profile_detector_interval
        modal_ui = bool(ui_hints.get("quest_ui_open") or ui_hints.get("gossip_open"))
        detector_refresh = False
        detector_scheduled = False
        initial_refresh = False
        detector_ms = None
        if modal_ui:
            # A UI anchor is a region proposal, not proof of a particular
            # dialog or button. Targeted OCR supplies separate text evidence.
            rect = PixelRect(int(width*.18), int(height*.12), int(width*.82), int(height*.88))
            candidates = (WorldCandidate(
                "unknown_ui_dialog_candidate", rect, .72,
                "modal telemetry cue defines bounded UI inspection ROI",
                track_id=-1, appearance={"proposal_semantics": "UNKNOWN", "ui_anchor": True},
                candidate_labels=("dialog_region_like",)),)
        else:
            completed = None
            pretracked = False
            feed = self._capture_feed()
            if feed is not None:
                # Capture-driven detector: it already ran on the newest frame it
                # could read; only take the newest finished result, never wait
                # and never submit.  Anchor on the exact frame YOLO saw.
                result = feed.poll()
                if (result is not None and (result.width, result.height) == (width, height)
                        and getattr(result, "generation", 0) == getattr(feed, "generation", 0)):
                    anchor = feed.frame_for_sequence(result.sequence) or (raw, width, height)
                    anchor_raw, anchor_width, anchor_height = anchor
                    if getattr(result, "tracked", False):
                        # V2 features and BoT-SORT association already ran in
                        # the feed process on every YOLO result (identities do
                        # not depend on which results World3D takes).
                        pretracked = True
                        detected = tuple(result.candidates)
                        diagnostics = dict(result.diagnostics)
                        self._feed_tracker_diagnostics = dict(result.tracker_diagnostics or {})
                    else:
                        detected = tuple(self.v2.process(
                            anchor_raw, anchor_width, anchor_height, scene,
                            precomputed_learned=result.candidates))
                        diagnostics = deepcopy(self.v2.last_diagnostics)
                    completed = (self._generation, anchor_raw, anchor_width, anchor_height,
                                 detected, result.inference_ms, diagnostics)
                    self._initial_detection_complete = True
                    self._detector_submissions = feed.results_received
                    self._last_detector_started_at = observed_at - result.inference_ms/1000.
            elif self._detector_future is not None and self._detector_future.done():
                try:
                    completed = self._detector_future.result()
                finally:
                    self._detector_future = None
            if completed is not None:
                generation, anchor_raw, anchor_width, anchor_height, detected, detector_ms, diagnostics = completed
                if generation == self._generation:
                    self._detector_completions += 1
                    if pretracked:
                        # This process's V2 never saw the anchor; the patch
                        # tracker computes its own luminance for it.
                        anchor_gray = None
                        tracked = detected
                    else:
                        anchor_gray = self._anchor_gray(anchor_width, anchor_height)
                        tracked = self.detector_tracker.update(
                            detected, timestamp=observed_at, raw=anchor_raw,
                            width=anchor_width, height=anchor_height,
                            gray=anchor_gray, gray_step=self.v2.downsample)
                    if tracked:
                        self._empty_detector_refreshes = 0
                        candidates = self.fast_tracker.anchor(
                            anchor_raw, anchor_width, anchor_height, tracked,
                            gray=anchor_gray)
                        if (anchor_raw is not raw or anchor_width != width
                                or anchor_height != height):
                            candidates = self.fast_tracker.propagate(raw, width, height)
                    else:
                        self._empty_detector_refreshes += 1
                        if (self.fast_tracker.candidates
                                and self._empty_detector_refreshes <= self.empty_detector_grace):
                            # A single empty YOLO refresh is negative evidence,
                            # not proof that every visible object vanished. Keep
                            # the bounded patch predictions until the detector
                            # either reacquires them or exhausts the miss grace.
                            propagated = self.fast_tracker.propagate(raw, width, height)
                            candidates = tuple(replace(candidate, appearance={
                                **candidate.appearance,
                                "detector_miss_streak": self._empty_detector_refreshes,
                                "detector_observation": "EMPTY_REFRESH_GRACE",
                                "tracking_only": True,
                            }) for candidate in propagated)
                            self.fast_tracker.candidates = candidates
                        else:
                            candidates = self.fast_tracker.anchor(
                                anchor_raw, anchor_width, anchor_height, (),
                                gray=anchor_gray)
                    detector_refresh = True
                    self._last_detector_ms = detector_ms
                    self._last_detector_diagnostics = diagnostics
                    # Maintain a start-to-start cadence.  The single in-flight
                    # future is already the back-pressure boundary; adding a
                    # second post-inference cooldown unnecessarily reduced a
                    # nominal 5-8 Hz detector to roughly 3-4 Hz and made
                    # reacquisition visibly lag behind camera turns.
                    started_at = (self._last_detector_started_at
                                  if self._last_detector_started_at is not None
                                  else observed_at - detector_ms/1000.)
                    self.next_detector_at = started_at + schedule_interval
                else:
                    candidates = self.fast_tracker.propagate(raw, width, height)
                    if self._pending_v2_reset:
                        self.v2.reset()
                        self._pending_v2_reset = False
            elif (feed is None and not self._initial_detection_complete
                  and self._detector_future is None):
                # Preserve deterministic first-frame behavior and establish an
                # anchor before asynchronous refreshes begin.
                generation, anchor_raw, anchor_width, anchor_height, detected, detector_ms, diagnostics = (
                    self._detect(raw, width, height, scene, self._generation))
                anchor_gray = self._anchor_gray(anchor_width, anchor_height)
                tracked = self.detector_tracker.update(
                    detected, timestamp=observed_at, raw=anchor_raw,
                    width=anchor_width, height=anchor_height,
                    gray=anchor_gray, gray_step=self.v2.downsample)
                self._empty_detector_refreshes = 0 if tracked else 1
                candidates = self.fast_tracker.anchor(
                    anchor_raw, anchor_width, anchor_height, tracked, gray=anchor_gray)
                detector_refresh = True
                initial_refresh = True
                self._initial_detection_complete = True
                self._last_detector_ms = detector_ms
                self._last_detector_diagnostics = diagnostics
                self._last_detector_started_at = observed_at - detector_ms/1000.
                self._detector_completions += 1
                self.next_detector_at = self._last_detector_started_at + schedule_interval
            else:
                candidates = self.fast_tracker.propagate(raw, width, height)

            if (feed is None and not initial_refresh and self._detector_future is None
                    and self._initial_detection_complete
                    and observed_at >= self.next_detector_at):
                self._detector_future = self._detector_pool.submit(
                    self._detect, raw, width, height, scene, self._generation)
                self._last_detector_started_at = observed_at
                self._detector_submissions += 1
                detector_scheduled = True
                # A deadline prevents repeated submission attempts while the
                # worker is starting; completion installs the adaptive value.
                self.next_detector_at = observed_at + schedule_interval
            elif feed is None and self._detector_future is not None and not detector_refresh:
                # No queue is formed: this input frame is superseded by the
                # next frame observed after the current inference completes.
                self._detector_busy_frames += 1
        self.last_text = self.ocr.process(raw, width, height, candidates, observed_at, ui_hints)
        if self.last_text:
            enriched = []
            for candidate in candidates:
                texts = [vars_text(item) for item in self.last_text if _overlap(item.rect, candidate.rect)]
                appearance = dict(candidate.appearance)
                if texts:
                    appearance["ocr_evidence"] = texts
                appearance["detector_refresh"] = detector_refresh
                enriched.append(replace(candidate, appearance=appearance))
            candidates = tuple(enriched)
            self.fast_tracker.candidates = candidates
            # OCR regions which do not overlap an entity/scene proposal remain
            # separate UI observations rather than being discarded or forced
            # onto the nearest entity.
            detached = []
            for text in self.last_text:
                if any(_overlap(text.rect, candidate.rect) for candidate in candidates):
                    continue
                identity = -int(hashlib.sha256(text.region_id.encode()).hexdigest()[:7], 16)
                detached.append(WorldCandidate(
                    "unknown_ui_text_candidate", text.rect, text.confidence,
                    "targeted OCR text region without entity association", track_id=identity,
                    appearance={"proposal_semantics": "UNKNOWN", "ocr_evidence": [vars_text(text)]},
                    candidate_labels=("readable_text_like",)))
            candidates = (*candidates, *detached)
        self.last_diagnostics = {
            "version": "world3d_v3_unified", "frame_index": self.frame_index,
            "mode": "MODAL_UI" if modal_ui else "WORLD3D",
            "perception_profile": dict(profile),
            "detector": {**self._last_detector_diagnostics, "refreshed": detector_refresh,
                         "in_flight": self._detector_future is not None,
                         "scheduled": detector_scheduled,
                         "cadence_mode": ("CAPTURE_DRIVEN_FEED" if self._capture_feed() is not None
                                          else "LATEST_FRAME_MAX_THROUGHPUT"
                                          if self.continuous_detector else "PROFILE_LIMITED"),
                         "feed": (self._capture_feed().feed_diagnostics()
                                  if self._capture_feed() is not None else None),
                         "target_hz": ("SOURCE_RATE" if self.continuous_detector
                                       else round(1/profile_detector_interval, 2)),
                         "profile_target_hz": round(1/profile_detector_interval, 2),
                         "submissions": self._detector_submissions,
                         "completions": self._detector_completions,
                         "busy_frames_superseded": self._detector_busy_frames,
                          "empty_refresh_streak": self._empty_detector_refreshes,
                          "empty_refresh_grace": self.empty_detector_grace,
                         "last_refresh_ms": (round(self._last_detector_ms, 2)
                                             if self._last_detector_ms is not None else None),
                         "next_refresh_at": round(self.next_detector_at, 4)},
            "tracker": {"mode": "CPU_PATCH_PROPAGATION", "target_hz": "capture_rate",
                        "tracks": len(candidates),
                        "detector_association": dict(
                            self._feed_tracker_diagnostics
                            or getattr(self.detector_tracker, "last_diagnostics",
                                       {"backend": "legacy", "status": "ready"})),
                        "camera_motion_px": dict(self.fast_tracker.last_camera_motion),
                        "timings_ms": dict(self.fast_tracker.last_timings_ms)},
            "ocr": dict(self.ocr.diagnostics), "scene_graph_input_tracks": len(candidates),
            "process_ms": round((time.perf_counter() - process_started) * 1000, 3),
            "opencv_compute": (self.compute_backend.diagnostics()
                               if self.compute_backend is not None
                               else {"requested": "AUTO", "active": "NUMPY",
                                     "reason": "opencv_unavailable"}),
        }
        return candidates


def _overlap(a: PixelRect, b: PixelRect) -> bool:
    return min(a.right, b.right) > max(a.left, b.left) and min(a.bottom, b.bottom) > max(a.top, b.top)


def vars_text(item: TextObservation) -> dict:
    return {"region_id": item.region_id, "text": item.text, "confidence": item.confidence,
            "engine": item.engine, "observed_at": item.observed_at,
            "semantic_type": "UNKNOWN"}
