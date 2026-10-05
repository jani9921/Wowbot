from __future__ import annotations

from dataclasses import replace
import os
import threading
from types import SimpleNamespace
from typing import Any

try:
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:  # pragma: no cover - installed package path
    from adapters.numpy_runtime import np

from .models import PixelRect, WorldCandidate
from .candidate_tracker import WorldCandidateTracker, _TrackState, _with_tracking  # noqa: F401  (moved; re-exported)
from .prescaled_gmc import _PrescaledTranslationGMC  # noqa: F401  (moved; re-exported)
from .association_identity import AssociationIdentityMixin


class UltralyticsAssociationTracker(AssociationIdentityMixin):
    """Ultralytics MOT adapter for canonical screen-space candidates.

    YOLO inference may alternate between full-scene and foveal crops, but the
    learned-detector adapter has already converted every box back to client
    pixels before this class sees it.  BoT-SORT therefore receives one stable
    coordinate space and the complete client image for global camera-motion
    compensation.  Its TrackId remains visual evidence only; semantic entity
    identity is still owned by the WorldModel/fusion layers above V3.

    Ultralytics is an optional runtime dependency.  A load/runtime failure
    falls back to the existing conservative tracker and is exposed through
    diagnostics instead of taking perception down.
    """

    _FAMILY_IDS = {
        "subject": 0,
        "symbol": 1,
        "unknown_object_candidate": 2,
        "unknown_scene_candidate": 3,
        "visual_candidate": 4,
    }

    def __init__(self, *, backend: str = "botsort", track_buffer: int = 30,
                 gmc_method: str = "sparseOptFlow",
                 gmc_downscale: int = 4,
                 warmup_in_background: bool = False,
                 prescaled_gmc: bool = True,
                 fuse_score: bool = False) -> None:
        normalized = str(backend).strip().lower().replace("-", "")
        if normalized not in {"botsort", "bytetrack"}:
            raise ValueError("backend must be botsort or bytetrack")
        self.backend = normalized
        self.track_buffer = max(1, int(track_buffer))
        self.gmc_method = str(gmc_method).strip() or "sparseOptFlow"
        self.gmc_downscale = max(1, int(gmc_downscale))
        # Use the caller's quarter-resolution gray (update(gray=...)) for
        # camera-motion compensation when it is supplied.
        self.prescaled_gmc = bool(prescaled_gmc) and self.gmc_method.lower() not in {"none", ""}
        self.fuse_score = bool(fuse_score)
        self._tracker: Any | None = None
        self._boxes_type: Any | None = None
        self._load_error: str | None = None
        self._load_lock = threading.Lock()
        self._warmup_thread: threading.Thread | None = None
        self._fallback = WorldCandidateTracker(max_misses=8)
        self._states: dict[int, _TrackState] = {}
        self._native_to_public: dict[int, int] = {}
        self._next_public_id = 1
        self._cutover_complete = False
        # Short-gap re-identification (see _reidentify): last box of every
        # published id, and ids that vanished recently (camera-compensated).
        self.reid_seconds = 1.5
        # 8 of 25 live one-frame re-births jumped 1.21-1.39 box heights.
        self.reid_max_heights = 1.5
        # The avatar is missed by the detector for 1-7 s at a time (live PID
        # 1712: 36 % of frames); it returns to the same screen place.
        self.anchored_retention_seconds = float(
            os.environ.get("AIPC_ANCHORED_RETENTION_SECONDS", "6"))
        # Screen-anchored subjects (the own avatar the camera orbits) are not
        # given to BoT-SORT: its global camera warp would push their
        # prediction off a box that does not move on screen.  Live 2026-10-01
        # (PID 4588): with GMC working the avatar changed id 12 times in 94 s.
        self.screen_anchored = os.environ.get("AIPC_TRACK_SCREEN_ANCHORED", "1") != "0"
        self._anchored: dict[int, dict] = {}
        self._last_boxes: dict[int, dict] = {}
        self._recently_lost: dict[int, dict] = {}
        self.reidentified = 0
        self.frame_index = 0
        self.last_diagnostics: dict[str, object] = {
            "backend": self.backend, "status": "not_loaded",
            "coordinate_space": "CLIENT_PIXELS",
        }
        if warmup_in_background:
            self.last_diagnostics["status"] = "warming"
            self._warmup_thread = threading.Thread(
                target=self._ensure_tracker,
                name=f"aipc-{self.backend}-warmup", daemon=True)
            self._warmup_thread.start()

    @staticmethod
    def _family(kind: str) -> str:
        return WorldCandidateTracker._family(kind)

    def _family_id(self, kind: str) -> int:
        family = self._family(kind)
        if family in self._FAMILY_IDS:
            return self._FAMILY_IDS[family]
        # Unknown non-entity families must not cross-associate with each
        # other merely because their boxes overlap.
        return 100 + sum((index + 1) * ord(char)
                         for index, char in enumerate(family)) % 10000

    def _ensure_tracker(self) -> bool:
        if self._tracker is not None:
            return True
        if self._load_error is not None:
            return False
        with self._load_lock:
            if self._tracker is not None:
                return True
            if self._load_error is not None:
                return False
            try:
                from ultralytics.engine.results import Boxes
                from ultralytics.trackers.bot_sort import BOTSORT
                from ultralytics.trackers.byte_tracker import BYTETracker

                base = BOTSORT if self.backend == "botsort" else BYTETracker

                class FamilyAwareTracker(base):
                    """Prevent subject/symbol/object ID swaps in generic MOT."""

                    def get_dists(inner_self, tracks, detections):
                        distances = super(FamilyAwareTracker, inner_self).get_dists(
                            tracks, detections)
                        if len(tracks) and len(detections):
                            for track_index, track in enumerate(tracks):
                                for detection_index, detection in enumerate(detections):
                                    if int(track.cls) != int(detection.cls):
                                        distances[track_index, detection_index] = 1.0
                        return distances

                arguments = SimpleNamespace(
                    # Candidate admission has already happened in LearnedWorldDetector.
                    # A floor is applied only inside MOT so weak but admitted visual
                    # cues can start a track without changing their public confidence.
                    track_high_thresh=.10,
                    track_low_thresh=.01,
                    new_track_thresh=.10,
                    track_buffer=self.track_buffer,
                    match_thresh=.85,
                    # Our detector's admitted scores are low (subjects ~.15-.35).
                    # Score fusion requires IoU*score >= .15, i.e. IoU >= .75 at
                    # .2: any motion re-IDed the object and weak symbols could
                    # never re-match (live/offline 2026-09-30).  Gate on IoU.
                    fuse_score=self.fuse_score,
                    gmc_method=self.gmc_method,
                    proximity_thresh=.50,
                    appearance_thresh=.80,
                    with_reid=False,
                    model="auto",
                    device="cpu",
                )
                self._tracker = FamilyAwareTracker(arguments)
                if self.backend == "botsort" and hasattr(self._tracker, "gmc"):
                    # Ultralytics defaults GMC to half resolution. World3D frames
                    # are large and we need only a global affine correction, so a
                    # quarter-resolution solve preserves pan compensation while
                    # avoiding a second detector-sized CPU workload.
                    self._tracker.gmc.downscale = self.gmc_downscale
                    if self.prescaled_gmc:
                        self._tracker.gmc = _PrescaledTranslationGMC(self._tracker.gmc)
                self._boxes_type = Boxes
                self.last_diagnostics = {
                    "backend": self.backend, "status": "ready",
                    "coordinate_space": "CLIENT_PIXELS",
                    "camera_motion_compensation": (
                        (f"phaseCorrelate(world3d_gray)|{self.gmc_method}"
                         if self.prescaled_gmc else self.gmc_method)
                        if self.backend == "botsort" else "none"),
                    "gmc_downscale": (self.gmc_downscale
                                      if self.backend == "botsort" else None),
                    "appearance_reid": False,
                    "score_fusion": self.fuse_score,
                    "track_buffer": self.track_buffer,
                    "family_gate": True,
                }
                return True
            except Exception as exc:  # optional dependency/runtime compatibility
                self._load_error = f"{type(exc).__name__}:{exc}"
                self.last_diagnostics = {
                    "backend": self.backend, "status": "fallback_legacy",
                    "fallback_reason": self._load_error,
                    "coordinate_space": "CLIENT_PIXELS",
                }
                return False

    @staticmethod
    def _bgr_view(raw: bytes | None, width: int | None,
                  height: int | None) -> Any | None:
        if raw is None or not width or not height or len(raw) != width * height * 4:
            return None
        # Captures are BGRA; dropping alpha produces the BGR contract expected
        # by Ultralytics GMC without an additional full-frame colour swap.
        return np.frombuffer(raw, dtype=np.uint8).reshape(
            (height, width, 4))[:, :, :3]

    def _tracked_candidate(self, candidate: WorldCandidate, track: Any,
                           timestamp: float | None, width: int,
                           height: int, public_track_id: int) -> WorldCandidate:
        track_id = int(public_track_id)
        coordinates = track.xyxy.tolist()
        rect = PixelRect(
            max(0, min(width, round(float(coordinates[0])))),
            max(0, min(height, round(float(coordinates[1])))),
            max(0, min(width, round(float(coordinates[2])))),
            max(0, min(height, round(float(coordinates[3])))),
        )
        # Kalman rounding at an image edge must not create a degenerate box.
        if rect.width < 1 or rect.height < 1:
            rect = candidate.rect
        center_x, center_y = WorldCandidateTracker._center(rect)
        state = self._states.get(track_id)
        previous_relation = state.relation if state is not None else None
        old_x, old_y = ((state.center_x, state.center_y)
                        if state is not None else (center_x, center_y))
        appearance = dict(candidate.appearance)
        if state is None:
            state = _TrackState(
                track_id=track_id, kind=candidate.kind,
                center_x=center_x, center_y=center_y,
                relation=candidate.relation, class_name=candidate.class_name,
                last_seen=self.frame_index, width=rect.width, height=rect.height,
                appearance=appearance, observed_at=timestamp)
            self._states[track_id] = state
        else:
            camera_dx = float(appearance.get("camera_motion_dx", 0) or 0)
            camera_dy = float(appearance.get("camera_motion_dy", 0) or 0)
            state.velocity_x = .65 * state.velocity_x + .35 * (
                center_x - old_x - camera_dx)
            state.velocity_y = .65 * state.velocity_y + .35 * (
                center_y - old_y - camera_dy)
            state.hits += 1
        state.kind = candidate.kind
        state.center_x, state.center_y = center_x, center_y
        state.relation, state.class_name = candidate.relation, candidate.class_name
        state.last_seen, state.observed_at = self.frame_index, timestamp
        state.lost_since, state.misses = None, 0
        state.width, state.height = rect.width, rect.height
        state.appearance = appearance
        residual = appearance.get("residual_motion")
        if isinstance(residual, (int, float)):
            state.residual_history = (*state.residual_history, float(residual))[-12:]
        enriched = _with_tracking(
            WorldCandidate(
                kind=candidate.kind, rect=rect, confidence=candidate.confidence,
                evidence=candidate.evidence, relation=candidate.relation,
                class_name=candidate.class_name, class_color=candidate.class_color,
                track_id=candidate.track_id,
                previous_relation=candidate.previous_relation,
                relation_changed=candidate.relation_changed,
                appearance=appearance,
                candidate_labels=tuple(candidate.candidate_labels),
            ),
            state, previous_relation, candidate.relation)
        enriched_appearance = dict(enriched.appearance)
        enriched_appearance.update({
            "track_association": (
                "ultralytics_botsort+gmc+kalman+family_gate"
                if self.backend == "botsort"
                else "ultralytics_bytetrack+kalman+family_gate"),
            "tracker_backend": self.backend,
            "track_hits": state.hits,
        })
        return WorldCandidate(
            kind=enriched.kind, rect=enriched.rect,
            confidence=enriched.confidence, evidence=enriched.evidence,
            relation=enriched.relation, class_name=enriched.class_name,
            class_color=enriched.class_color, track_id=enriched.track_id,
            previous_relation=enriched.previous_relation,
            relation_changed=enriched.relation_changed,
            appearance=enriched_appearance,
            candidate_labels=tuple(enriched.candidate_labels),
        )

    def update(self, candidates: tuple[WorldCandidate, ...] | list[WorldCandidate],
               timestamp: float | None = None, *, raw: bytes | None = None,
               width: int | None = None,
               height: int | None = None, gray: Any | None = None,
               gray_step: int | None = None) -> tuple[WorldCandidate, ...]:
        self.frame_index += 1
        fallback_output = self._fallback.update(
            candidates, timestamp=timestamp, raw=raw, width=width, height=height)
        if (self._warmup_thread is not None and self._warmup_thread.is_alive()
                and self._tracker is None):
            self.last_diagnostics.update({
                "status": "warming_fallback_legacy",
                "fallback_tracks": len(fallback_output),
            })
            return fallback_output
        if not self._ensure_tracker() or width is None or height is None:
            return fallback_output
        try:
            if self.backend == "botsort" and hasattr(self._tracker, "gmc"):
                # Very small replay/test frames lose too much feature detail
                # at 1/4 scale; production-sized frames retain the cheap path.
                effective_downscale = (min(self.gmc_downscale, 2)
                                       if min(width, height) < 400
                                       else self.gmc_downscale)
                self._tracker.gmc.downscale = effective_downscale
                self.last_diagnostics["gmc_effective_downscale"] = effective_downscale
                gmc = self._tracker.gmc
                if isinstance(gmc, _PrescaledTranslationGMC) and gray is not None and gray_step:
                    gmc.set_frame(gray, gray_step)
            anchored_index = ([index for index, candidate in enumerate(candidates)
                               if self._screen_anchored(candidate, width, height)]
                              if self.screen_anchored else [])
            anchored_set = set(anchored_index)
            world_index = [index for index in range(len(candidates))
                           if index not in anchored_set]
            rows = np.asarray([
                [candidate.rect.left, candidate.rect.top,
                 candidate.rect.right, candidate.rect.bottom,
                 # Internal-only score floor. Public evidence retains the
                 # detector's original confidence unchanged.
                 max(.11, float(candidate.confidence)),
                 self._family_id(candidate.kind)]
                for candidate in (candidates[index] for index in world_index)
            ], dtype=np.float32).reshape((-1, 6))
            boxes = self._boxes_type(rows, orig_shape=(height, width))
            self._tracker.update(boxes, img=self._bgr_view(raw, width, height))
            current: dict[int, Any] = {}
            for track in self._tracker.tracked_stracks:
                if int(track.frame_id) != int(self._tracker.frame_id):
                    continue
                index = int(track.idx)
                if 0 <= index < len(world_index):
                    current[world_index[index]] = track
            if not self._cutover_complete:
                # The background import must not create a visible ID reset.
                # Bind each first native TrackId to the already-published
                # legacy ID for the same current detection index. Ultralytics
                # deliberately withholds some new/unconfirmed tracks, so a
                # partial result is a normal MOT lifecycle state rather than
                # a broken library contract.
                for index, track in current.items():
                    self._native_to_public[int(track.track_id)] = int(
                        fallback_output[index].track_id)
                self._next_public_id = max(
                    [self._next_public_id, *self._native_to_public.values()]) + 1
                self._cutover_complete = True
            self._age_recently_lost(timestamp)
            in_use = {self._native_to_public[int(track.track_id)]
                      for track in current.values()
                      if int(track.track_id) in self._native_to_public}
            anchored_ids = self._anchored_assign(candidates, anchored_index, timestamp, in_use)
            in_use.update(anchored_ids.values())
            for index, track in current.items():
                native_id = int(track.track_id)
                if native_id not in self._native_to_public:
                    fallback_id = int(fallback_output[index].track_id)
                    reidentified = self._reidentify(candidates[index], in_use)
                    if reidentified is not None:
                        # Detach the vanished native track so a later
                        # recovery of it cannot publish a duplicate id.
                        for old_native, public in list(self._native_to_public.items()):
                            if public == reidentified:
                                del self._native_to_public[old_native]
                        self._native_to_public[native_id] = reidentified
                        self.reidentified += 1
                    elif (fallback_id not in self._native_to_public.values()
                          and fallback_id not in self._anchored
                          and fallback_id not in in_use):
                        # This also bridges a track that was published during
                        # warm-up but happened to be occluded on the exact
                        # cutover frame. Legacy is only an ID alias source here;
                        # BoT-SORT remains the association authority.
                        self._native_to_public[native_id] = fallback_id
                        self._next_public_id = max(
                            self._next_public_id, fallback_id + 1)
                    else:
                        self._native_to_public[native_id] = self._next_public_id
                        self._next_public_id += 1
                    in_use.add(self._native_to_public[native_id])
            # BoT-SORT/ByteTrack may omit a just-created tentative detection
            # until a later frame confirms it. Publish that detection through
            # the continuously-running conservative tracker for now, while
            # keeping native MOT active for every assigned detection. When a
            # withheld native track becomes confirmed on a later frame, the
            # mapping above adopts the same fallback public id. This avoids a
            # full sticky downgrade because one of three boxes was tentative.
            output = tuple(
                self._tracked_candidate(
                    candidate, current[index], timestamp, width, height,
                    self._native_to_public[int(current[index].track_id)])
                if index in current else
                self._tracked_candidate(
                    replace(candidate, appearance={**candidate.appearance,
                                                   "screen_anchored": True}),
                    SimpleNamespace(xyxy=np.asarray(
                        [candidate.rect.left, candidate.rect.top,
                         candidate.rect.right, candidate.rect.bottom], dtype=np.float64)),
                    timestamp, width, height, anchored_ids[index])
                if index in anchored_ids else fallback_output[index]
                for index, candidate in enumerate(candidates))
            output = self._unique_ids(output, current, anchored_ids)
            self._remember_published(output, timestamp)
            active_ids = {
                self._native_to_public[int(track.track_id)]
                for track in self._tracker.tracked_stracks
                if int(track.track_id) in self._native_to_public} | set(self._anchored)
            lost_ids = {
                self._native_to_public[int(track.track_id)]
                for track in self._tracker.lost_stracks
                if int(track.track_id) in self._native_to_public}
            for track_id, state in list(self._states.items()):
                if track_id in active_ids:
                    if state.last_seen != self.frame_index:
                        state.misses += 1
                    continue
                if track_id in lost_ids:
                    state.misses += 1
                    state.lost_since = state.lost_since or timestamp
                    continue
                del self._states[track_id]
            self.last_diagnostics.update({
                "status": ("ready" if len(current)+len(anchored_ids) == len(candidates)
                           else "ready_partial"),
                "screen_anchored": len(anchored_ids),
                "frame_index": self.frame_index,
                "detections": len(candidates), "published": len(output),
                "native_assignments": len(current),
                "tentative_legacy_bridge": len(candidates)-len(current),
                "active_tracks": len(active_ids), "lost_tracks": len(lost_ids),
            })
            return output
        except Exception as exc:
            # Make the fallback sticky for this instance. Mixing two ID spaces
            # frame-by-frame would be worse than consistently using legacy.
            self._load_error = f"{type(exc).__name__}:{exc}"
            self._tracker = None
            self.last_diagnostics.update({
                "status": "fallback_legacy",
                "fallback_reason": self._load_error,
            })
            return fallback_output

    def get_track(self, track_id: int) -> dict[str, object] | None:
        state = self._states.get(int(track_id))
        if state is not None:
            return WorldCandidateTracker._snapshot(state)
        return self._fallback.get_track(track_id)

    def recent_tracks(self) -> tuple[dict[str, object], ...]:
        if self._states:
            return tuple(WorldCandidateTracker._snapshot(state)
                         for state in self._states.values() if state.lost_since is None)
        return self._fallback.recent_tracks()

    def lost_tracks(self) -> tuple[dict[str, object], ...]:
        if self._states:
            return tuple(WorldCandidateTracker._snapshot(state)
                         for state in self._states.values() if state.lost_since is not None)
        return self._fallback.lost_tracks()

    def invalidate_all(self, reason: str) -> None:
        self._states.clear()
        self._anchored.clear()
        self._tracker = None
        self._native_to_public.clear()
        self._cutover_complete = False
        self._fallback.invalidate_all(reason)
        self.last_diagnostics.update({"status": "invalidated", "reason": reason})

    def reset(self) -> None:
        """Clear temporal state without repeating the expensive module load."""
        self._states.clear()
        self._native_to_public.clear()
        self._last_boxes.clear()
        self._recently_lost.clear()
        self._anchored.clear()
        self._next_public_id = 1
        self._cutover_complete = False
        self._fallback = WorldCandidateTracker(max_misses=8)
        self.frame_index = 0
        if self._tracker is not None:
            self._tracker.reset()
            gmc = getattr(self._tracker, "gmc", None)
            if isinstance(gmc, _PrescaledTranslationGMC):
                gmc.reset_params()
            elif gmc is not None:
                gmc.prevFrame = None
                gmc.prevKeyPoints = None
                gmc.prevDescriptors = None
                gmc.initializedFirstFrame = False
            self.last_diagnostics.update({
                "status": "ready", "frame_index": 0,
                "detections": 0, "published": 0,
                "active_tracks": 0, "lost_tracks": 0,
            })
        elif self._warmup_thread is not None and self._warmup_thread.is_alive():
            self.last_diagnostics.update({"status": "warming"})


