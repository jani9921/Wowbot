"""Source-local temporal tracks for visual detections.

A track means only that a visual phenomenon persisted. It does not prove an
entity identity, quest role, hostility, or any other semantic fact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import os

from wowbot.vision.world3d.association import linear_sum_assignment

from .stable_objects import StableObjectLayer


@dataclass
class _Track:
    identity: int
    x: float
    y: float
    first_seen: float
    last_seen: float
    hits: int = 1
    misses: int = 0
    detector_votes: dict[str, int] = field(default_factory=dict)
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    confidence_history: list[float] = field(default_factory=list)
    observation_history: list[str] = field(default_factory=list)
    bbox_history: list[dict] = field(default_factory=list)
    appearance_history: list[dict] = field(default_factory=list)
    candidate_label_history: list[tuple[str, ...]] = field(default_factory=list)
    kind: str = "visual_candidate"
    width: float | None = None
    height: float | None = None
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    residual_history: list[float] = field(default_factory=list)
    last_payload: dict = field(default_factory=dict)
    upstream_track_id: str | None = None
    # V3 is normally the source identity authority.  A detector refresh can
    # still briefly restart a V3 id for the same visual subject, so retain a
    # small alias history instead of forcing a new presentation/world track.
    upstream_track_aliases: list[str] = field(default_factory=list)
    # Own avatar: fixed on screen while the camera orbits it, so camera
    # motion must not be applied to its prediction or coast.
    screen_anchored: bool = False


class VisualTrackManager:
    def __init__(self, *, max_misses: int = 8, lost_grace_seconds: float = 1.20,
                 max_active_tracks: int = 60, max_new_candidates: int = 60,
                 reidentification_grace_seconds: float = 12.0,
                 max_retired_tracks: int = 32,
                 present_grace_seconds: float | None = None):
        self.max_misses = max_misses
        # Presentation vs identity (live 2026-09-30 20:22): an unmatched track
        # is *drawn/published* only for ``present_grace_seconds`` (a stale box
        # must not trail behind a camera turn) but stays associable, coasting
        # with the camera, until ``lost_grace_seconds`` so a subject that
        # reappears keeps its id.  None keeps the historical behaviour.
        self.present_grace_seconds = (None if present_grace_seconds is None
                                      else max(0., float(present_grace_seconds)))
        # Count is a back-pressure guard, not the source of truth: the same
        # eight missed observations can represent 40 ms on a fast machine or
        # several seconds on a slow capture.  Preserve an UNKNOWN track until
        # both count and wall-clock evidence support loss.
        self.lost_grace_seconds = max(.05, float(lost_grace_seconds))
        # Association below builds a full new-candidates x active-tracks cost
        # matrix and solves it with linear_sum_assignment (Hungarian) every
        # tick. A scene that never stabilizes (e.g. a stuck INSPECT/search
        # loop actively panning the camera) can flood dozens-to-hundreds of
        # never-matching candidates per tick; since a track only leaves
        # `active` after both a miss quorum AND `lost_grace_seconds` of real
        # time, unmatched tracks accumulate across ticks faster than they
        # expire, growing both matrix dimensions tick over tick and
        # collapsing the control loop (live-confirmed 2026-09-22: candidate
        # count 4-8x baseline, step() climbing 175ms->700ms+ over ~50 ticks
        # with stable_world_tracks stuck at 0). These bound the matrix to a
        # constant worst case regardless of detector noise.
        self.max_active_tracks = max(1, int(max_active_tracks))
        self.max_new_candidates = max(1, int(max_new_candidates))
        # Recently lost tracks are kept outside the active assignment set.
        # This permits conservative visual continuity across a longer gap
        # without letting stale tracks grow the Hungarian cost matrix or
        # asserting that a visual match proves semantic/entity identity.
        self.reidentification_grace_seconds = max(
            self.lost_grace_seconds, float(reidentification_grace_seconds))
        self.max_retired_tracks = max(1, int(max_retired_tracks))
        self.next_id = 1
        self.tracks: dict[str, dict[int, _Track]] = {}
        self.retired_tracks: dict[str, list[_Track]] = {}
        # Persistent presentation objects for World3D: one id and one box per
        # visual phenomenon across raw id churn and short detector gaps.
        # The hold bridged heavy raw id churn (1.5 s / 3 s).  With detector-
        # rate association fixed (full-frame feed, IoU gating) a held box that
        # is not camera-compensated slides off its subject during a turn and
        # lingers (live 2026-09-30), so the runtime holds are short.
        self.stable_objects = StableObjectLayer(
            hold_seconds=float(os.environ.get("AIPC_STABLE_HOLD_SECONDS", ".5")),
            tracked_hold_seconds=float(os.environ.get(
                "AIPC_STABLE_TRACKED_HOLD_SECONDS", "1.0")))

    def reset(self):
        self.next_id = 1
        self.tracks.clear()
        self.retired_tracks.clear()
        self.stable_objects.reset()

    def _prune_retired_tracks(self, source: str, observed_at: float) -> None:
        retained = [
            track for track in self.retired_tracks.get(source, [])
            if observed_at-track.last_seen <= self.reidentification_grace_seconds
        ]
        self.retired_tracks[source] = retained[-self.max_retired_tracks:]

    def _retire_track(self, source: str, track: _Track, observed_at: float) -> None:
        # Feature-poor tracks are still retained so diagnostics can explain a
        # rejected re-identification, but the bounded archive cannot affect
        # active association cost or grow indefinitely.
        archive = self.retired_tracks.setdefault(source, [])
        archive.append(track)
        self._prune_retired_tracks(source, observed_at)

    @staticmethod
    def _comparable_appearance_features(a: dict, b: dict) -> int:
        return sum(
            isinstance(a.get(key), (int, float)) and isinstance(b.get(key), (int, float))
            for key in ("foreground_contrast", "edge_density", "body_geometry", "residual_motion")
        )

    def _pop_reidentification_candidate(self, source: str, item: dict,
                                        observed_at: float) -> _Track | None:
        """Return one unambiguous recent visual continuation, if any.

        This is deliberately stricter than ordinary frame-to-frame tracking:
        it requires three comparable appearance dimensions, compatible scale,
        and nearby screen position.  A close score tie is rejected so two
        similar adjacent creatures cannot silently exchange track identity.
        """
        candidates: list[tuple[float, _Track]] = []
        appearance = item["appearance"]
        for track in self.retired_tracks.get(source, []):
            if observed_at-track.last_seen > self.reidentification_grace_seconds:
                continue
            if self._family(track.kind) != item["family"]:
                continue
            previous = track.appearance_history[-1] if track.appearance_history else {}
            if self._comparable_appearance_features(previous, appearance) < 3:
                continue
            visual = self._appearance_distance(previous, appearance)
            if visual > .10:
                continue
            displacement = math.hypot(item["x"]-track.x, item["y"]-track.y)
            if displacement > .10:
                continue
            scale = 0.0
            if track.width and track.height:
                scale = (abs(math.log(item["width"]/track.width))
                         + abs(math.log(item["height"]/track.height)))
            if scale > .55:
                continue
            # Appearance dominates; position and scale only break otherwise
            # plausible visual matches. This remains a hypothesis, not fact.
            candidates.append((visual + .35*displacement + .04*scale, track))
        candidates.sort(key=lambda entry: entry[0])
        if not candidates:
            return None
        if len(candidates) > 1 and candidates[1][0]-candidates[0][0] < .025:
            return None
        selected = candidates[0][1]
        self.retired_tracks[source] = [
            track for track in self.retired_tracks.get(source, [])
            if track.identity != selected.identity
        ]
        return selected

    def _evict_excess_active_tracks(self, active: dict[int, _Track]) -> None:
        if len(active) <= self.max_active_tracks:
            return
        # Keep the most temporally established tracks (most hits, fewest
        # recent misses); drop the rest immediately instead of waiting out
        # the miss-quorum/grace-period eviction path.
        ranked = sorted(active.values(), key=lambda track: (-track.hits, track.misses))
        for track in ranked[self.max_active_tracks:]:
            del active[track.identity]

    def update(self, source: str, detections: list[dict], observed_at: float) -> list[dict]:
        active = self.tracks.setdefault(source, {})
        self._prune_retired_tracks(source, observed_at)
        self._evict_excess_active_tracks(active)
        if len(detections) > self.max_new_candidates:
            detections = sorted(
                detections, key=lambda item: -float(item.get("confidence", 0))
            )[:self.max_new_candidates]
        if source == "WORLD3D":
            detections = self._subject_probes(detections, active)
        unmatched = set(active)
        result = []
        threshold = .05 if source == "WORLD3D" else .035
        prepared = []
        for detection in sorted(detections, key=lambda item: -float(item.get("confidence", 0))):
            x, y = detection.get("x"), detection.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                result.append(detection)
                continue
            detector_kind = str(detection.get("detector_kind") or detection.get("kind") or "visual_candidate")
            family = self._family(detector_kind)
            appearance = detection.get("appearance") if isinstance(detection.get("appearance"), dict) else {}
            camera_dx = float(appearance.get("camera_motion_dx", 0) or 0)
            camera_dy = -float(appearance.get("camera_motion_dy", 0) or 0)
            bbox = detection.get("bbox") if isinstance(detection.get("bbox"), dict) else {}
            coordinate_width = max(1., float(bbox.get("right", 0) or 0) - float(bbox.get("left", 0) or 0))
            coordinate_height = max(1., float(bbox.get("bottom", 0) or 0) - float(bbox.get("top", 0) or 0))
            # Camera deltas are client pixels. Convert using the bbox coordinate
            # and normalized center when the full frame size is unavailable;
            # the first-stage tracker already absorbed most of this motion.
            frame_w = coordinate_width / max(.002, float(detection.get("bbox_width_fraction", 0) or .02))
            frame_h = coordinate_height / max(.002, float(detection.get("bbox_height_fraction", 0) or .04))
            camera_nx, camera_ny = camera_dx / frame_w, camera_dy / frame_h
            if appearance.get("screen_anchored"):
                camera_nx = camera_ny = 0.
            prepared.append({"detection": detection, "x": float(x), "y": float(y),
                             "detector_kind": detector_kind, "family": family,
                             "appearance": appearance, "width": coordinate_width,
                             "height": coordinate_height, "camera_nx": camera_nx,
                             "camera_ny": camera_ny,
                             "upstream_track_id": (str(detection.get("upstream_track_id"))
                                                   if detection.get("upstream_track_id") is not None else None)})

        active_tracks = list(active.values())
        costs = []
        association_modes: list[list[str | None]] = []
        for item in prepared:
            row = []
            modes = []
            for candidate_track in active_tracks:
                if self._family(candidate_track.kind) != item["family"]:
                    row.append(math.inf)
                    modes.append(None)
                    continue
                # World3D V3 has already associated its detector and fast
                # patch-tracker observations.  Preserve that upstream visual
                # identity across this presentation/relations layer instead
                # of making a competing nearest-centre decision. Other
                # sources (minimap/map) still use normal global assignment.
                upstream_id = item["upstream_track_id"]
                if upstream_id is not None:
                    known_upstreams = {candidate_track.upstream_track_id,
                                       *candidate_track.upstream_track_aliases}
                    if upstream_id in known_upstreams:
                        # Live 2026-10-01: two tracks carrying the same V3 id
                        # tied at 0 and the assignment alternated between
                        # them.  The current owner, then the older track wins.
                        row.append((0. if upstream_id == candidate_track.upstream_track_id
                                    else 1e-3) + 1e-4/(1+candidate_track.hits))
                        modes.append("UPSTREAM_EXACT")
                        continue
                predicted_x = candidate_track.x + candidate_track.velocity_x + item["camera_nx"]
                predicted_y = candidate_track.y + candidate_track.velocity_y + item["camera_ny"]
                distance = math.hypot(item["x"]-predicted_x, item["y"]-predicted_y)
                scale = 0.0
                if candidate_track.width and candidate_track.height:
                    scale = (abs(math.log(item["width"]/candidate_track.width))
                             + abs(math.log(item["height"]/candidate_track.height)))
                visual = self._appearance_distance(
                    candidate_track.appearance_history[-1]
                    if candidate_track.appearance_history else {}, item["appearance"])
                bbox_overlap = self._bbox_iou(
                    candidate_track.bbox_history[-1] if candidate_track.bbox_history else {},
                    item["detection"].get("bbox"))
                allowed = threshold * (1.0 + .35*candidate_track.misses)
                if upstream_id is not None and candidate_track.upstream_track_id is not None:
                    # A new V3 id may only inherit a source-local track when
                    # it is a close, visually compatible continuation. This
                    # is deliberately narrower than ordinary association so
                    # two adjacent Murlocs cannot be merged merely because a
                    # detector refresh changed one upstream id.
                    reid_allowed = min(allowed, .04)
                    if distance > reid_allowed or visual > .52:
                        row.append(math.inf)
                        modes.append(None)
                        continue
                    row.append(distance + .012*min(2., scale) + .018*visual - .006*bbox_overlap + .008)
                    modes.append("UPSTREAM_REIDENTIFIED")
                    continue
                row.append(distance + .012*min(2., scale) + .018*visual - .006*bbox_overlap
                           if distance <= allowed else math.inf)
                modes.append("SPATIAL")
            costs.append(row)
            association_modes.append(modes)
        assigned = {detection_index: (active_tracks[track_index], association_modes[detection_index][track_index])
                    for detection_index, track_index in linear_sum_assignment(costs)}

        for detection_index, item in enumerate(prepared):
            detection = item["detection"]
            x, y = item["x"], item["y"]
            detector_kind = item["detector_kind"]
            appearance = item["appearance"]
            coordinate_width, coordinate_height = item["width"], item["height"]
            camera_nx, camera_ny = item["camera_nx"], item["camera_ny"]
            was_missing = False
            assigned_track = assigned.get(detection_index)
            track, association_mode = assigned_track if assigned_track is not None else (None, "NEW")
            if track is None:
                track = self._pop_reidentification_candidate(source, item, observed_at)
                if track is not None:
                    association_mode = "LONG_GAP_REIDENTIFIED"
                    was_missing = True
                    active[track.identity] = track
            if track is None:
                track = _Track(self.next_id, x, y, observed_at, observed_at, kind=detector_kind,
                               upstream_track_id=item["upstream_track_id"],
                               upstream_track_aliases=([item["upstream_track_id"]]
                                                       if item["upstream_track_id"] is not None else []))
                self.next_id += 1
                active[track.identity] = track
            else:
                unmatched.discard(track.identity)
                was_missing = was_missing or track.misses > 0
                old_x, old_y = track.x, track.y
                track.x, track.y = x, y
                track.velocity_x = .7*track.velocity_x + .3*(x-old_x-camera_nx)
                track.velocity_y = .7*track.velocity_y + .3*(y-old_y-camera_ny)
                track.last_seen = observed_at
                track.hits += 1
                track.misses = 0
            track.kind = detector_kind
            track.screen_anchored = bool(appearance.get("screen_anchored"))
            if item["upstream_track_id"] is not None:
                if item["upstream_track_id"] not in track.upstream_track_aliases:
                    track.upstream_track_aliases = (track.upstream_track_aliases +
                                                    [item["upstream_track_id"]])[-6:]
                track.upstream_track_id = item["upstream_track_id"]
            track.detector_votes[detector_kind] = track.detector_votes.get(detector_kind, 0) + 1
            track.positions = (track.positions + [(observed_at, x, y)])[-32:]
            track.confidence_history = (track.confidence_history + [float(detection.get("confidence", 0))])[-32:]
            track.observation_history = (track.observation_history + [f"{source}:{observed_at:.6f}"])[-32:]
            if isinstance(detection.get("bbox"), dict):
                track.bbox_history = (track.bbox_history + [dict(detection["bbox"])])[-32:]
            if isinstance(detection.get("appearance"), dict):
                track.appearance_history = (track.appearance_history + [dict(detection["appearance"])])[-32:]
                residual = detection["appearance"].get("residual_motion")
                if isinstance(residual, (int, float)):
                    track.residual_history = (track.residual_history + [float(residual)])[-32:]
            track.width, track.height = coordinate_width, coordinate_height
            inspectable = bool(detection.get("inspectable"))
            if detector_kind in {"unknown_subject_candidate", "unknown_subject_probe"}:
                anchor_hits = int((appearance.get("anchor_track_hits", 0) or 0))
                # The probe is a spatial inspection region, not a fresh
                # visual entity.  Its eligibility inherits the already
                # observed temporal stability of the symbol that created it.
                inspectable = track.hits >= 3 or (
                    detector_kind == "unknown_subject_probe" and anchor_hits >= 2)
            current_labels = tuple(sorted({str(value) for value in
                                           detection.get("candidate_labels") or ()}))
            track.candidate_label_history = (track.candidate_label_history +
                                             [current_labels])[-12:]
            # A discriminative appearance cue may flicker with animation/JPEG
            # noise. Keep it attached to the same temporal identity for this
            # bounded history instead of requiring rediscovery every frame.
            labels = {value for sample in track.candidate_label_history for value in sample}
            if detector_kind in {"unknown_minimap_marker", "unknown_map_marker"} and track.hits >= 3:
                inspectable = not bool(labels & {"gold_direction_like", "blue_gray_direction_like"})
            if detector_kind == "unknown_symbol_candidate":
                inspectable = False
            detector_miss_streak = int(appearance.get("detector_miss_streak", 0) or 0)
            if detector_miss_streak:
                # Patch propagation smooths a short detector dropout but is
                # prediction evidence, not a fresh observed entity. Keep it
                # visible for diagnosis without granting inspect/move authority.
                inspectable = False
                lifecycle = ("OCCLUDED" if detector_miss_streak <= 2
                             else "LOST_TEMPORARY")
                temporal_state = "PREDICTED"
            else:
                lifecycle = ("REACQUIRE_CANDIDATE" if was_missing
                             else "ACTIVE" if track.hits >= 3 else "TENTATIVE")
                temporal_state = ("CONFIRMED"
                                  if lifecycle in {"ACTIVE", "REACQUIRE_CANDIDATE"}
                                  else "TENTATIVE")
            tracked_payload = {**detection, "detector_kind": detector_kind,
                           "semantic_type": detection.get("semantic_type") or "UNKNOWN",
                           "inspectable": inspectable,
                           "track_id": f"{source}:{track.identity}",
                           "track_state": lifecycle,
                           "temporal_state": temporal_state,
                           "observed_at": observed_at,
                           "stable_frames": track.hits, "first_seen": track.first_seen,
                           "last_seen": track.last_seen,
                           "age": max(0.0, observed_at-track.first_seen), "missing_frames": track.misses,
                           "lifecycle": lifecycle,
                           "upstream_track_id": track.upstream_track_id,
                           "upstream_track_aliases": list(track.upstream_track_aliases),
                           "upstream_association": association_mode,
                           "association_evidence": self._association_evidence(
                               track, detection, association_mode, temporal_state),
                           "observations": list(track.observation_history),
                           "bbox_history": list(track.bbox_history),
                           "appearance_history": list(track.appearance_history),
                           "position_history": list(track.positions),
                           "confidence_history": list(track.confidence_history),
                           "candidate_labels": sorted(labels),
                           "candidate_label_history": [list(row) for row in track.candidate_label_history],
                           "detection_hypotheses": dict(track.detector_votes)}
            track.last_payload = dict(tracked_payload)
            if track.residual_history:
                tracked_payload.setdefault("appearance", {})["residual_motion_trend"] = round(
                    sum(track.residual_history)/len(track.residual_history), 4)
            if source in {"MINIMAP_CV", "WORLD_MAP_CV"}:
                tracked_payload.update({"marker_id": f"{source}:{track.identity}",
                                        "surface": "MINIMAP" if source == "MINIMAP_CV" else "WORLD_MAP",
                                        "belief": "SUPPORTED" if track.hits >= 3 else "CANDIDATE"})
            result.append(tracked_payload)
        # One camera motion per frame (all candidates carry the same V2
        # estimate).  A coasting box must move with the scene; a pure velocity
        # coast left boxes behind during camera turns (live 2026-09-30).
        frame_motion = sorted((item["camera_nx"], item["camera_ny"]) for item in prepared)
        frame_nx, frame_ny = (frame_motion[len(frame_motion)//2] if frame_motion else (0., 0.))
        matched_upstreams = {item["upstream_track_id"] for item in prepared
                             if item["upstream_track_id"] is not None}
        for identity in list(unmatched):
            track = active[identity]
            if track.upstream_track_id is not None and track.upstream_track_id in matched_upstreams:
                # Its upstream identity is live on another track this frame:
                # this one is a stale duplicate, not an occluded subject.
                del active[identity]
                self._retire_track(source, track, observed_at)
                continue
            track.misses += 1
            elapsed_missing = max(0., observed_at-track.last_seen)
            # A handful of frames may vanish during animation, camera motion
            # or capture jitter.  Conversely, waiting for eight misses on a
            # 2 Hz detector kept stale scenery around for four seconds. Loss
            # therefore needs a small observation quorum *and* elapsed time.
            if track.misses >= min(3, self.max_misses) and elapsed_missing >= self.lost_grace_seconds:
                del active[identity]
                self._retire_track(source, track, observed_at)
                continue
            if track.last_payload:
                lifecycle = "OCCLUDED" if track.misses <= 2 else "LOST_TEMPORARY"
                track.x += track.velocity_x + (0. if track.screen_anchored else frame_nx)
                track.y += track.velocity_y + (0. if track.screen_anchored else frame_ny)
                # Own motion is extrapolated with decay; the camera term is
                # measured every frame.
                track.velocity_x *= .85
                track.velocity_y *= .85
                if (self.present_grace_seconds is not None
                        and elapsed_missing > self.present_grace_seconds):
                    continue  # hidden but still associable
                result.append({**track.last_payload,
                    "x": track.x, "y": track.y, "inspectable": False,
                    "confidence": max(.12, float(track.last_payload.get("confidence", .5))*(.82**track.misses)),
                    "track_state": lifecycle, "lifecycle": lifecycle,
                    "temporal_state": "OCCLUDED" if lifecycle == "OCCLUDED" else "LOST",
                    "missing_frames": track.misses, "last_seen": track.last_seen,
                    "missing_seconds": round(elapsed_missing, 6),
                    "occlusion_probability": min(.95, .35+.1*track.misses),
                    "reidentification_status": "CANDIDATE"})
        if source == "WORLD3D":
            result = self.stable_objects.update(result, observed_at)
            self._relations(result)
        return result

    @staticmethod
    def _family(kind: str) -> str:
        if kind in {"quest_giver", "quest_turn_in", "quest_direction", "treasure_direction",
                    "quest_related", "quest_area", "target", "minimap_candidate",
                    "unknown_minimap_marker", "unknown_map_marker"}:
            return "map_marker"
        if "symbol" in kind:
            return "symbol"
        if "subject" in kind:
            return "subject"
        return kind

    @staticmethod
    def _appearance_distance(a: dict, b: dict) -> float:
        values = []
        for key in ("foreground_contrast", "edge_density", "body_geometry", "residual_motion"):
            av, bv = a.get(key), b.get(key)
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                values.append(abs(float(av)-float(bv)))
        return sum(values)/len(values) if values else .5

    @staticmethod
    def _bbox_iou(previous: dict, current: dict | None) -> float:
        """Geometry evidence for association; malformed boxes are neutral."""
        if not isinstance(previous, dict) or not isinstance(current, dict):
            return 0.0
        try:
            left, top = max(float(previous["left"]), float(current["left"])), max(float(previous["top"]), float(current["top"]))
            right, bottom = min(float(previous["right"]), float(current["right"])), min(float(previous["bottom"]), float(current["bottom"]))
            intersect = max(0., right-left)*max(0., bottom-top)
            prior_area = max(0., float(previous["right"])-float(previous["left"])) * max(0., float(previous["bottom"])-float(previous["top"]))
            current_area = max(0., float(current["right"])-float(current["left"])) * max(0., float(current["bottom"])-float(current["top"]))
            return intersect/(prior_area+current_area-intersect) if prior_area+current_area-intersect > 0 else 0.0
        except (KeyError, TypeError, ValueError):
            return 0.0

    @classmethod
    def _association_evidence(cls, track: _Track, detection: dict,
                              mode: str | None, temporal_state: str) -> dict:
        previous_bbox = track.bbox_history[-2] if len(track.bbox_history) >= 2 else {}
        previous_appearance = track.appearance_history[-2] if len(track.appearance_history) >= 2 else {}
        current_appearance = detection.get("appearance") if isinstance(detection.get("appearance"), dict) else {}
        return {
            "mode": mode or "NEW",
            "bbox_overlap": round(cls._bbox_iou(previous_bbox, detection.get("bbox")), 4),
            "visual_feature_similarity": round(max(0., 1.-cls._appearance_distance(previous_appearance, current_appearance)), 4),
            "motion_prediction": "camera_compensated_velocity" if track.hits > 1 else "unavailable_first_detection",
            "screen_space_proximity": "global_assignment" if mode not in {None, "NEW"} else "new_track",
            # Compatibility remains generic: raw CV cannot say NPC/hostile.
            "class_compatibility": "UNKNOWN_FAMILY_COMPATIBLE",
            "temporal_consistency_frames": track.hits,
            "temporal_state": temporal_state,
            "fact": False,
        }

    @staticmethod
    def _subject_probes(detections: list[dict], active: dict[int, _Track]) -> list[dict]:
        """Create an inspection region below an isolated symbol-like cue."""
        out = list(detections)
        subjects = [d for d in detections if "subject" in str(d.get("kind", ""))]
        for symbol in [d for d in detections if d.get("kind") == "unknown_symbol_candidate"]:
            sx, sy = symbol.get("x"), symbol.get("y")
            if not isinstance(sx, (int, float)) or not isinstance(sy, (int, float)):
                continue
            symbol_labels = {str(value) for value in symbol.get("candidate_labels") or ()}
            symbol_appearance = (symbol.get("appearance")
                                 if isinstance(symbol.get("appearance"), dict) else {})
            # A learned overhead-symbol box is already the YOLO observation.
            # Inventing a large body rectangle below every isolated learned
            # symbol turned torches and other bright scenery into inspectable
            # UNKNOWN units.  Keep the real symbol track and wait for a real
            # learned subject detection instead of manufacturing an entity.
            # The legacy colour/nameplate path may still use this bounded
            # fallback because it has no trained subject detector.
            if ("learned_symbol_like" in symbol_labels
                    or symbol_appearance.get("learned_label_hypothesis") is not None
                    or symbol_appearance.get("source_detector") is not None):
                continue
            prior = [track for track in active.values() if track.kind == "unknown_symbol_candidate"
                     and math.hypot(track.x-float(sx), track.y-float(sy)) <= .05]
            appearance = symbol_appearance
            # The high-rate World3D tracker may already have accumulated a
            # stable appearance before this source-level tracker sees its
            # first observation. Preserve that evidence instead of waiting
            # several slow agent ticks and falling through to map/TDB search.
            stable_evidence = max(
                int(symbol.get("stable_frames", 0) or 0),
                int(appearance.get("track_hits", 0) or 0),
                max((track.hits for track in prior), default=0),
            )
            if stable_evidence < 2:
                continue
            symbol_bbox = symbol.get("bbox") if isinstance(symbol.get("bbox"), dict) else {}

            def reliable_subject(subject: dict) -> bool:
                # Keep the derived body column close to the overhead anchor.
                # At 1177 px a .07 window spans ~82 px and associated Jaina's
                # glyph with a different humanoid standing beside her in the
                # live trace. A .04 normalized window is still tolerant of
                # detector jitter while rejecting that neighbouring subject.
                if abs(float(subject.get("x", 9))-sx) > .04:
                    return False
                if not (.015 <= sy-float(subject.get("y", sy)) <= .18):
                    return False
                if subject.get("kind") == "unknown_subject_probe":
                    return True
                bbox = subject.get("bbox") if isinstance(subject.get("bbox"), dict) else {}
                if not all(isinstance(bbox.get(key), (int, float))
                           for key in ("left", "top", "right", "bottom")):
                    return False
                width = float(bbox["right"])-float(bbox["left"])
                height = float(bbox["bottom"])-float(bbox["top"])
                # A tiny colour fragment directly below a glyph is not an
                # inspectable body. Nor is a large blob that contains the
                # glyph itself. In both cases derive a neutral probe below it.
                separated = (not all(isinstance(symbol_bbox.get(key), (int, float))
                                     for key in ("top", "bottom"))
                             or float(bbox["top"]) >= float(symbol_bbox["bottom"])-4)
                return width >= 16 and height >= 24 and separated

            associated = any(reliable_subject(subject) for subject in subjects)
            if associated:
                continue
            bbox = symbol_bbox
            probe_bbox = None
            probe_y = max(0.0, sy-.075)
            bbox_fraction = float(symbol.get("bbox_height_fraction", 0) or 0)
            if all(isinstance(bbox.get(k), (int, float)) for k in ("left", "top", "right", "bottom")):
                cx = (bbox["left"]+bbox["right"])/2
                symbol_h = max(1., float(bbox["bottom"])-float(bbox["top"]))
                symbol_w = max(1., float(bbox["right"])-float(bbox["left"]))
                width_fraction = float(symbol.get("bbox_width_fraction", 0) or 0)
                frame_h = symbol_h/bbox_fraction if bbox_fraction > .001 else None
                frame_w = symbol_w/width_fraction if width_fraction > .001 else None
                probe_h = max(96., min(132., symbol_h*5.0))
                probe_w = max(72., min(104., probe_h*.72))
                probe_top = float(bbox["bottom"])+3.
                # A cue at the bottom edge is usually UI or a clipped symbol;
                # there is no visible body below it to inspect.  Never invent
                # an off-frame probe: it used to publish y > 1 and could make
                # the seek servo spin indefinitely.
                if frame_h is not None and frame_h-probe_top < 24.:
                    continue
                probe_bottom = min(probe_top+probe_h, frame_h) if frame_h is not None else probe_top+probe_h
                probe_left = max(0., cx-probe_w/2)
                probe_right = min(cx+probe_w/2, frame_w) if frame_w is not None else cx+probe_w/2
                if probe_right-probe_left < 16. or probe_bottom-probe_top < 24.:
                    continue
                probe_bbox = {"left": int(probe_left), "top": int(probe_top),
                              "right": int(probe_right), "bottom": int(probe_bottom),
                              "coordinate_space": "CLIENT_PIXELS"}
                if frame_h:
                    probe_y = min(1.0, max(0.0, 1.-(probe_top+probe_bottom)/2./frame_h))
            probe_appearance = {
                "shape": "inspection_region",
                "derived_from": "overhead_symbol_like_cue",
                "anchor_track_hits": stable_evidence,
                "anchor_bbox_height_fraction": bbox_fraction,
                "anchor_candidate_labels": list(symbol.get("candidate_labels") or ()),
                "screen_center_relevance": appearance.get("screen_center_relevance", 0),
                "anchor_appearance": {key: appearance.get(key) for key in
                    ("hue_family", "brightness", "saturation", "foreground_contrast")
                    if appearance.get(key) is not None},
            }
            out.append({"kind": "unknown_subject_probe", "detector_kind": "unknown_subject_probe",
                        "semantic_type": "UNKNOWN",
                        "confidence": max(.66, min(.72, float(symbol.get("confidence", .5))*.94)),
                        "x": sx, "y": probe_y, "source": "WORLD3D", "confirmed": False,
                        "inspectable": False, "bbox": probe_bbox,
                        # The large probe rectangle is only an inspection
                        # region. Servo distance must use the observed cue's
                        # scale, never the fabricated probe height.
                        "servo_scale_fraction": bbox_fraction or None,
                        "appearance": probe_appearance,
                        "candidate_labels": ["subject_below_symbol_probe"],
                        "evidence": "stable-looking symbol has no reliable subject detection"})
        return out

    @staticmethod
    def _relations(items: list[dict]) -> None:
        symbols = [i for i in items if i.get("detector_kind") == "unknown_symbol_candidate"]
        subjects = [i for i in items if "subject" in str(i.get("detector_kind", ""))]
        for symbol in symbols:
            options = [s for s in subjects if abs(float(s.get("x", 9))-float(symbol.get("x", 0))) <= .045
                       and .01 <= float(symbol.get("y", 0))-float(s.get("y", 0)) <= .18]
            if not options:
                continue
            def relation_cost(subject: dict) -> tuple:
                bbox = subject.get("bbox") if isinstance(subject.get("bbox"), dict) else {}
                area = max(0., (float(bbox.get("right", 0))-float(bbox.get("left", 0)))
                           * (float(bbox.get("bottom", 0))-float(bbox.get("top", 0))))
                is_probe = subject.get("detector_kind") == "unknown_subject_probe"
                # Live 2026-09-30: Jaina's body had two alternating tracks; the
                # symbol kept binding to the nearer one even while it was
                # LOST_TEMPORARY, leaving the ACTIVE body ungrouped, so no quest
                # cue target existed and the agent turned away to search.
                # A currently observed body wins over a coasting prediction.
                lifecycle = str(subject.get("lifecycle") or subject.get("track_state") or "ACTIVE").upper()
                liveness = (0 if lifecycle in {"ACTIVE", "STABLE", "TENTATIVE", "REACQUIRE_CANDIDATE"}
                            else 1 if lifecycle == "OCCLUDED" else 2)
                # A real body-sized detector observation is stronger evidence
                # than a fabricated inspection region.  Retain the probe only
                # ahead of tiny colour fragments that cannot represent a body.
                # Live 2026-09-30: a small partial box (Jaina's staff tip) sat
                # nearer the symbol than her full body.  The unit under a
                # marker is the largest real body in the narrow window below
                # it, which also beats a small creature at the NPC's feet.
                return (liveness,
                        0 if not is_probe and area >= 384 else 1 if is_probe else 2,
                        -area,
                        abs(float(subject["x"])-float(symbol["x"]))
                        + abs(float(subject["y"])-float(symbol["y"])))
            subject = min(options, key=relation_cost)
            # A probe is deliberately derived only after its overhead symbol
            # has persisted.  Requiring three *new* probe frames would throw
            # away the temporal evidence that justified creating the probe in
            # the first place and delays active perception by several slow
            # detector cycles.  The relation is still supported only when the
            # anchor itself has three observations and the probe records at
            # least two prior anchor hits; an ordinary detected subject must
            # independently persist for three frames.
            probe_anchor_hits = int(((subject.get("appearance") or {})
                                     .get("anchor_track_hits", 0)) or 0)
            supported = (int(symbol.get("stable_frames", 1)) >= 3 and
                         (int(subject.get("stable_frames", 1)) >= 3
                          or (subject.get("detector_kind") == "unknown_subject_probe"
                              and probe_anchor_hits >= 2)))
            symbol_id, subject_id = symbol.get("track_id"), subject.get("track_id")
            group_id = f"WORLD3D_GROUP:{symbol_id}:{subject_id}"
            symbol_labels = list(symbol.get("candidate_labels") or ())
            anchor_labels = list((subject.get("appearance") or {}).get("anchor_candidate_labels") or ())
            appearance_labels = sorted(set(symbol_labels + anchor_labels))
            group = {
                "group_id": group_id,
                "surface": "WORLD3D",
                "semantic_type": "UNKNOWN",
                "belief": "SUPPORTED" if supported else "CANDIDATE",
                "member_track_ids": [value for value in (symbol_id, subject_id) if value],
                "symbol_track_id": symbol_id,
                "subject_track_id": subject_id,
                "appearance_labels": appearance_labels,
                "evidence": ["temporally_spatially_consistent_symbol_above_subject"],
            }
            relation = {"type": "ABOVE", "subject_track_id": subject.get("track_id"),
                        "belief": "SUPPORTED" if supported else "CANDIDATE", "semantic_type": "UNKNOWN",
                        "visual_group_id": group_id}
            symbol.setdefault("visual_relations", []).append(relation)
            subject.setdefault("visual_relations", []).append({**relation, "symbol_track_id": symbol.get("track_id")})
            symbol["visual_group_id"] = subject["visual_group_id"] = group_id
            symbol["visual_group"] = dict(group)
            subject["visual_group"] = dict(group)
            subject["information_value"] = "HIGH" if supported else "CANDIDATE"

    def snapshot(self) -> list[dict]:
        return [{"source": source, "track_id": f"{source}:{track.identity}",
                 "state": "LOST_TEMPORARY" if track.misses > 2 else "OCCLUDED" if track.misses else "ACTIVE" if track.hits >= 3 else "TENTATIVE",
                 "hits": track.hits, "misses": track.misses, "last_seen": track.last_seen,
                 "first_seen": track.first_seen, "age": max(0.0, track.last_seen-track.first_seen),
                 "missing_frames": track.misses,
                 "lifecycle": "LOST_TEMPORARY" if track.misses > 2 else "OCCLUDED" if track.misses else "ACTIVE" if track.hits >= 3 else "TENTATIVE",
                 "kind": track.kind,
                 "upstream_track_id": track.upstream_track_id,
                 "upstream_track_aliases": list(track.upstream_track_aliases),
                 "last_bbox": track.bbox_history[-1] if track.bbox_history else None,
                 "last_appearance": track.appearance_history[-1] if track.appearance_history else None,
                 "last_position": track.positions[-1] if track.positions else None,
                 "last_confidence": track.confidence_history[-1] if track.confidence_history else None,
                 "residual_motion_trend": (round(sum(track.residual_history)/len(track.residual_history), 4)
                                           if track.residual_history else None),
                 "detection_hypotheses": dict(track.detector_votes)}
                for source, tracks in self.tracks.items() for track in tracks.values()]
