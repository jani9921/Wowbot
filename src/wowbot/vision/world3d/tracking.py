from __future__ import annotations

from dataclasses import dataclass, replace
import math
import os
import threading
from types import SimpleNamespace
from typing import Any

try:
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:  # pragma: no cover - installed package path
    from adapters.numpy_runtime import np

from .models import PixelRect, WorldCandidate
from .association import linear_sum_assignment


@dataclass(slots=True)
class _TrackState:
    track_id: int
    kind: str
    center_x: float
    center_y: float
    relation: str | None
    class_name: str | None
    last_seen: int
    misses: int = 0
    width: float = 1.0
    height: float = 1.0
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    hits: int = 1
    appearance: dict[str, object] | None = None
    residual_history: tuple[float, ...] = ()
    observed_at: float | None = None
    lost_since: float | None = None


class WorldCandidateTracker:
    """Camera-aware UNKNOWN visual tracker.

    Association combines predicted position, scale and appearance evidence.
    A match only preserves visual identity; it never recognizes an entity.
    """

    def __init__(self, max_distance: float = 45.0, max_misses: int = 2) -> None:
        self.max_distance = float(max_distance)
        self.max_misses = int(max_misses)
        self._next_id = 1
        self._tracks: dict[int, _TrackState] = {}
        self._lost: dict[int, _TrackState] = {}
        self.frame_index = 0

    @staticmethod
    def _snapshot(track: _TrackState) -> dict[str, object]:
        return {
            "track_id": track.track_id, "kind": track.kind,
            "position": {"x": track.center_x, "y": track.center_y},
            "velocity": {"x": track.velocity_x, "y": track.velocity_y},
            "bbox": {"width": track.width, "height": track.height},
            "appearance_signature": dict(track.appearance or {}),
            "confidence": min(1., .35 + .1 * track.hits),
            "hits": track.hits, "missing_frames": track.misses,
            "last_seen_frame": track.last_seen, "observed_at": track.observed_at,
            "lost_since": track.lost_since,
        }

    def get_track(self, track_id: int) -> dict[str, object] | None:
        track = self._tracks.get(int(track_id)) or self._lost.get(int(track_id))
        return self._snapshot(track) if track else None

    def recent_tracks(self) -> tuple[dict[str, object], ...]:
        return tuple(self._snapshot(track) for track in self._tracks.values())

    def lost_tracks(self) -> tuple[dict[str, object], ...]:
        return tuple(self._snapshot(track) for track in self._lost.values())

    def invalidate_all(self, reason: str) -> None:
        for track in self._tracks.values():
            track.lost_since = track.observed_at
            self._lost[track.track_id] = track
        self._tracks.clear()
        # Diagnostics only: keep the latest bounded set and never reuse these
        # identities after an explicit context invalidation.
        self._lost = dict(list(self._lost.items())[-64:])

    @staticmethod
    def _center(rect: PixelRect) -> tuple[float, float]:
        return ((rect.left + rect.right) / 2.0, (rect.top + rect.bottom) / 2.0)

    @staticmethod
    def _family(kind: str) -> str:
        if "subject" in kind:
            return "subject"
        if "symbol" in kind:
            return "symbol"
        return kind

    @staticmethod
    def _appearance_distance(a: dict[str, object] | None, b: dict[str, object]) -> float:
        if not a:
            return .5
        keys = ("foreground_contrast", "edge_density", "body_geometry", "residual_motion")
        values = []
        for key in keys:
            av, bv = a.get(key), b.get(key)
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                values.append(abs(float(av) - float(bv)))
        return sum(values) / len(values) if values else .5

    def update(self, candidates: tuple[WorldCandidate, ...] | list[WorldCandidate],
               timestamp: float | None = None, *, raw: bytes | None = None,
               width: int | None = None,
               height: int | None = None, gray: Any | None = None,
               gray_step: int | None = None) -> tuple[WorldCandidate, ...]:
        # ``gray``/``gray_step`` feed camera-motion compensation of the MOT
        # adapter; this appearance/centroid tracker does not use them.
        self.frame_index += 1
        active = [t for t in self._tracks.values() if t.misses <= self.max_misses]
        unmatched = set(t.track_id for t in active)
        updates: list[WorldCandidate] = []

        ordered = sorted(candidates, key=lambda c: (0 if c.kind == "unknown_subject_candidate" else 1, -c.confidence))
        costs: list[list[float]] = []
        for cand in ordered:
            cx, cy = self._center(cand.rect)
            row = []
            for track in active:
                if self._family(track.kind) != self._family(cand.kind):
                    row.append(math.inf)
                    continue
                appearance = cand.appearance or {}
                camera_dx = float(appearance.get("camera_motion_dx", 0) or 0)
                camera_dy = float(appearance.get("camera_motion_dy", 0) or 0)
                predicted_x = track.center_x + camera_dx + track.velocity_x
                predicted_y = track.center_y + camera_dy + track.velocity_y
                dist = math.hypot(cx - predicted_x, cy - predicted_y)
                scale = abs(math.log(max(1., cand.rect.width) / max(1., track.width))) + \
                        abs(math.log(max(1., cand.rect.height) / max(1., track.height)))
                visual = self._appearance_distance(track.appearance, appearance)
                cost = dist / max(1., self.max_distance) + .22 * min(2., scale) + .28 * visual
                allowed = self.max_distance * (1.0 + .35 * track.misses)
                row.append(cost if dist <= allowed else math.inf)
            costs.append(row)
        assigned = {candidate_index: active[track_index]
                    for candidate_index, track_index in linear_sum_assignment(costs)}

        for candidate_index, cand in enumerate(ordered):
            cx, cy = self._center(cand.rect)
            best = assigned.get(candidate_index)
            created = best is None
            if best is None:
                best = _TrackState(
                    track_id=self._next_id,
                    kind=cand.kind,
                    center_x=cx,
                    center_y=cy,
                    relation=cand.relation,
                    class_name=cand.class_name,
                    last_seen=self.frame_index,
                    width=cand.rect.width,
                    height=cand.rect.height,
                    appearance=dict(cand.appearance),
                    observed_at=timestamp,
                )
                self._next_id += 1
                self._tracks[best.track_id] = best
            else:
                unmatched.discard(best.track_id)

            previous_relation = best.relation
            old_x, old_y = best.center_x, best.center_y
            camera_dx = float(cand.appearance.get("camera_motion_dx", 0) or 0)
            camera_dy = float(cand.appearance.get("camera_motion_dy", 0) or 0)
            if not created:
                best.velocity_x = .65 * best.velocity_x + .35 * (cx - old_x - camera_dx)
                best.velocity_y = .65 * best.velocity_y + .35 * (cy - old_y - camera_dy)
            best.center_x, best.center_y = cx, cy
            best.last_seen = self.frame_index
            best.observed_at = timestamp
            best.lost_since = None
            best.misses = 0
            if not created:
                best.hits += 1
            best.width, best.height = cand.rect.width, cand.rect.height
            best.appearance = dict(cand.appearance)
            residual = cand.appearance.get("residual_motion")
            if isinstance(residual, (int, float)):
                best.residual_history = (*best.residual_history, float(residual))[-12:]
            best.relation = cand.relation
            best.class_name = cand.class_name
            updates.append(_with_tracking(cand, best, previous_relation, cand.relation))

        # Tracking an unknown blob does not confirm that it is an entity.
        for track_id in list(unmatched):
            track = self._tracks.get(track_id)
            if track is not None:
                track.misses += 1
                if track.misses > self.max_misses:
                    track.lost_since = timestamp
                    self._lost[track_id] = track
                    self._lost = dict(list(self._lost.items())[-64:])
                    del self._tracks[track_id]

        # Preserve original detector order for all hypotheses, including obstacles.
        by_identity = {id(src): updates[i] for i, src in enumerate(ordered)}
        result: list[WorldCandidate] = []
        for cand in candidates:
            result.append(by_identity.get(id(cand), cand))
        return tuple(result)


class _PrescaledTranslationGMC:
    """BoT-SORT global motion from the World3D quarter-resolution gray.

    Live 2026-09-30, with the capture-driven YOLO feed refreshing every frame:
    Ultralytics' sparse-optical-flow GMC cost 12.5 ms of a 19 ms refresh
    (full-frame BGR->gray of a strided view plus 400-corner Lucas-Kanade).
    V2 has already reduced the same anchor frame to a quarter-resolution
    luminance image, so a sub-pixel phase correlation on it gives the global
    camera translation for ~1 ms (synthetic shifts: p90 error 2.5 px).  A
    frame without that gray, or a weak correlation peak, uses the original
    Ultralytics estimator / identity exactly as before.

    Live 2026-09-30 (feed trace, PID 3324): during camera turns detections
    moved 20-100 px per frame while this estimator reported ~1 px, so every
    turn frame spawned fresh track ids and the old boxes coasted in place.
    The estimate now comes from ``camera_motion.WorldCameraMotion`` (two world
    crops beside the avatar).  Among its hypotheses (similarity, mean, either
    crop, identity) the one mapping the most previous high-score detections
    onto the current ones wins; BoT-SORT applies the resulting similarity
    warp to tracked *and* lost tracks.
    """

    def __init__(self, fallback: Any, *, min_response: float = .1) -> None:
        from .camera_motion import WorldCameraMotion
        self.fallback = fallback
        self.motion = WorldCameraMotion(min_response=min_response)
        self._pending: tuple[Any, int] | None = None
        self._previous: Any | None = None
        self._previous_boxes: Any = None
        self._fallback_active = False
        self.last_response: float | None = None
        # Shift at the image centre in client pixels (trace/diagnostics).
        self.last_warp: tuple[float, float] | None = None
        self.last_scale: float | None = None
        self.last_hypothesis: str | None = None
        self.last_detection_support: int | None = None

    @property
    def method(self):
        return self.fallback.method

    @property
    def downscale(self):
        return self.fallback.downscale

    @downscale.setter
    def downscale(self, value) -> None:
        self.fallback.downscale = value

    def set_frame(self, gray: Any, step: int) -> None:
        self._pending = (gray, max(1, int(step)))

    def reset_params(self) -> None:
        self._pending = self._previous = self._previous_boxes = None
        self._fallback_active = False
        self.fallback.reset_params()

    def apply(self, raw_frame: Any, detections: Any = None) -> Any:
        pending, self._pending = self._pending, None
        if pending is None:
            # Keep the fallback's previous frame coherent across mode switches.
            self._previous = self._previous_boxes = None
            if not self._fallback_active:
                self.fallback.reset_params()
                self._fallback_active = True
            return self.fallback.apply(raw_frame, detections)
        if self._fallback_active:
            self.fallback.reset_params()
            self._fallback_active = False
        from .camera_motion import select_by_detections
        gray, step = pending
        current = np.ascontiguousarray(gray, dtype=np.float32)
        boxes = None if detections is None else np.asarray(detections, dtype=np.float64).reshape(-1, 4)
        previous, self._previous = self._previous, current
        previous_boxes, self._previous_boxes = self._previous_boxes, boxes
        self.last_response = self.last_warp = self.last_scale = None
        self.last_hypothesis = self.last_detection_support = None
        if previous is None or previous.shape != current.shape or min(current.shape) < 16:
            return np.eye(2, 3)
        hypotheses = self.motion.hypotheses(previous, current)
        try:
            chosen, support = select_by_detections(hypotheses, previous_boxes, boxes, step)
        except Exception:  # noqa: BLE001 -- keep the image estimate, never identity
            chosen, support = hypotheses[0], -1
        responses = [crop[2] for crop in self.motion.last_crops if crop is not None]
        self.last_response = max(responses) if responses else None
        self.last_hypothesis, self.last_detection_support = chosen.name, support
        self.last_scale = float(chosen.scale)
        height, width = current.shape
        cx, cy = chosen.shift_at(width/2, height/2)
        self.last_warp = (float(cx*step), float(cy*step))
        return chosen.warp(step)


class UltralyticsAssociationTracker:
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

    def _unique_ids(self, output: tuple[WorldCandidate, ...], current: dict[int, Any],
                    anchored_ids: dict[int, int]) -> tuple[WorldCandidate, ...]:
        """One public id per frame; screen-anchored ids are claimed first.

        Live 2026-10-01 06:45: the avatar (anchored id 5) and a world box
        whose legacy-bridge id was also 5 were published together; the World3D
        layer then opened a second track for "V3:5" and alternated.
        """
        claimed = set(anchored_ids.values())
        result = list(output)
        for index, item in enumerate(result):
            if index in anchored_ids or item.track_id is None:
                continue
            public = int(item.track_id)
            if public in claimed:
                public = self._next_public_id
                self._next_public_id += 1
                if index in current:
                    self._native_to_public[int(current[index].track_id)] = public
                result[index] = replace(item, track_id=public)
            claimed.add(public)
        return tuple(result)

    @staticmethod
    def _screen_anchored(candidate: WorldCandidate, width: int, height: int) -> bool:
        """A large subject box centred on the third-person avatar position."""
        rect = candidate.rect
        return ("subject" in str(candidate.kind)
                and abs((rect.left+rect.right)/2 - width/2) < .06*width
                and rect.bottom > .55*height and rect.height > .15*height)

    def _anchored_assign(self, candidates, indices: list[int],
                         timestamp: float | None, world_in_use: set[int]) -> dict[int, int]:
        """IoU association without camera warp for screen-anchored boxes.

        A box newly entering the avatar zone (an NPC walking behind the avatar)
        inherits the id it was published with on the previous frame; leaving
        the zone, ``_reidentify`` hands that id back to BoT-SORT.
        """
        now = float(timestamp) if timestamp is not None else self.frame_index/30.
        for public, entry in list(self._anchored.items()):
            if now-entry["seen"] > self.anchored_retention_seconds:
                del self._anchored[public]

        def iou(a: PixelRect, b: PixelRect) -> float:
            left, top = max(a.left, b.left), max(a.top, b.top)
            right, bottom = min(a.right, b.right), min(a.bottom, b.bottom)
            inter = max(0, right-left)*max(0, bottom-top)
            union = a.width*a.height + b.width*b.height - inter
            return inter/union if union > 0 else 0.

        def similarity(a: PixelRect, b: PixelRect) -> float:
            # IoU, or for a reshaped box (animation, mount) a centre match
            # within half a box height scored just above the IoU gate.
            overlap = iou(a, b)
            if overlap >= .3:
                return overlap
            height = max(a.height, b.height, 1)
            ratio = max(a.height, b.height)/max(1, min(a.height, b.height))
            distance = math.hypot((a.left+a.right-b.left-b.right)/2,
                                  (a.top+a.bottom-b.top-b.bottom)/2)/height
            return .3 if distance <= .5 and ratio <= 1.6 else overlap

        pairs = sorted(((similarity(candidates[index].rect, entry["rect"]), -entry["first"],
                         index, public)
                        for index in indices for public, entry in self._anchored.items()),
                       reverse=True)
        assigned: dict[int, int] = {}
        used: set[int] = set()
        for overlap, _, index, public in pairs:
            if overlap < .3:
                break
            if index in assigned or public in used:
                continue
            assigned[index] = public
            used.add(public)
        for index in indices:
            if index in assigned:
                continue
            public = self._inherit_published(candidates[index], world_in_use | used)
            if public is None:
                public = self._next_public_id
                self._next_public_id += 1
            assigned[index] = public
            used.add(public)
            self._anchored[public] = {"first": now}
        for index, public in assigned.items():
            self._anchored[public].update({"rect": candidates[index].rect, "seen": now})
        return assigned

    def _inherit_published(self, candidate: WorldCandidate, in_use: set[int]) -> int | None:
        """Id published on the previous frame at the same place (unambiguous)."""
        rect = candidate.rect
        cx, cy = (rect.left+rect.right)/2, (rect.top+rect.bottom)/2
        height = max(1., float(rect.height))
        family = self._family(candidate.kind)
        scored = []
        for public_id, box in self._last_boxes.items():
            if public_id in in_use or box["family"] != family:
                continue
            ratio = max(height, box["height"])/min(height, box["height"])
            distance = math.hypot(cx-box["cx"], cy-box["cy"])/max(height, box["height"])
            if ratio <= 1.5 and distance <= .5:
                scored.append((distance, public_id))
        scored.sort()
        if not scored or (len(scored) > 1 and scored[1][0]-scored[0][0] < .15):
            return None
        return scored[0][1]

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

    def _gmc_translation(self) -> tuple[float, float]:
        gmc = getattr(self._tracker, "gmc", None) if self._tracker is not None else None
        warp = getattr(gmc, "last_warp", None)
        if not warp:
            return 0., 0.
        return float(warp[0]), float(warp[1])

    def _age_recently_lost(self, timestamp: float | None) -> None:
        """Carry vanished ids with the camera and forget them after a while."""
        dx, dy = self._gmc_translation()
        for public_id, entry in list(self._recently_lost.items()):
            if (timestamp is not None and entry["lost_at"] is not None
                    and timestamp-entry["lost_at"] > self.reid_seconds):
                del self._recently_lost[public_id]
                continue
            entry["cx"] += dx
            entry["cy"] += dy

    def _remember_published(self, output, timestamp: float | None) -> None:
        present = {int(item.track_id): item for item in output if item.track_id is not None}
        for public_id, box in list(self._last_boxes.items()):
            if public_id not in present:
                self._recently_lost[public_id] = {**box, "lost_at": timestamp}
                del self._last_boxes[public_id]
        for public_id, item in present.items():
            rect = item.rect
            self._last_boxes[public_id] = {
                "cx": (rect.left+rect.right)/2, "cy": (rect.top+rect.bottom)/2,
                "height": max(1., float(rect.height)),
                "family": self._family(item.kind)}
            self._recently_lost.pop(public_id, None)

    def _reidentify(self, candidate: WorldCandidate, in_use: set[int]) -> int | None:
        """Give a newly born native track the id of a subject that just vanished.

        Live 2026-09-30 (running around an NPC): 73 % of new subject ids were
        the same subject returning after a median 0.25 s gap, displaced by a
        median 0.61 box heights (own avatar occluding it, orbiting camera);
        BoT-SORT's Kalman prediction no longer overlapped it.  Same family,
        near the camera-compensated last position, similar height and an
        unambiguous best match are required; identity semantics stay with the
        addon GUID layer.
        """
        family = self._family(candidate.kind)
        rect = candidate.rect
        cx, cy = (rect.left+rect.right)/2, (rect.top+rect.bottom)/2
        height = max(1., float(rect.height))
        # Live 2026-10-01 (PID 1712): most re-births happened within ONE frame
        # (0.04 s): the old id was published on the previous frame, so it was
        # not yet "recently lost" and was invisible here.  An id published
        # last frame and unmatched on this one is lost *now*; its box moves
        # with this frame's camera warp.
        dx, dy = self._gmc_translation()
        pool = dict(self._recently_lost)
        for public_id, box in self._last_boxes.items():
            if public_id not in pool:
                pool[public_id] = {**box, "cx": box["cx"]+dx, "cy": box["cy"]+dy}
        scored = []
        for public_id, entry in pool.items():
            if (public_id in in_use or public_id in self._anchored
                    or entry["family"] != family):
                continue
            ratio = max(height, entry["height"])/min(height, entry["height"])
            if ratio > 1.7:
                continue
            distance = math.hypot(cx-entry["cx"], cy-entry["cy"])/max(height, entry["height"])
            if distance <= self.reid_max_heights:
                scored.append((distance, public_id))
        if not scored:
            return None
        scored.sort()
        if len(scored) > 1 and scored[1][0]-scored[0][0] < .25:
            return None
        public_id = scored[0][1]
        self._recently_lost.pop(public_id, None)
        return public_id

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


def _with_tracking(cand: WorldCandidate, track: _TrackState, previous_relation: str | None, relation: str | None) -> WorldCandidate:
    evidence = cand.evidence
    if previous_relation is not None and relation is not None and previous_relation != relation:
        evidence = f"{evidence}; relation_transition={previous_relation}->{relation}"
    appearance = dict(cand.appearance)
    if track.residual_history:
        mean_residual = sum(track.residual_history) / len(track.residual_history)
        appearance["residual_motion_trend"] = round(mean_residual, 4)
        # Static is a soft evidence penalty, never a semantic rejection.  It
        # becomes meaningful only after several temporally associated frames.
        appearance["static_scene_score"] = round(
            min(1.0, float(appearance.get("static_scene_score", 0)) +
                (0.18 if track.hits >= 4 and mean_residual < .12 else 0.0)), 4)
    appearance["track_association"] = "position+camera+motion+scale+appearance"
    appearance["track_hits"] = track.hits
    return WorldCandidate(
        kind=cand.kind,
        rect=cand.rect,
        confidence=cand.confidence,
        evidence=evidence,
        relation=cand.relation,
        class_name=cand.class_name,
        class_color=cand.class_color,
        track_id=track.track_id,
        previous_relation=previous_relation,
        relation_changed=(previous_relation is not None and previous_relation != relation),
        appearance=appearance,
        candidate_labels=tuple(cand.candidate_labels),
    )
