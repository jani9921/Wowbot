"""Canonical World3D perception pipeline.

The existing V2 detector, V3 CPU patch tracker, and V4 semantic-evidence
enricher remain the source of low-level observations.  This module is their
single publish authority: it turns their tracked UNKNOWN candidates into a
typed, inspectable local-world batch.  It deliberately has no input, planner,
navigation, or interaction dependencies.
"""
from __future__ import annotations

from collections import deque
import math
import time
from typing import Any, Iterable

try:  # works both from installed package and repository execution
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:  # pragma: no cover - package execution path
    import numpy as np

from .models import BearingEstimate, PixelRect, ScreenPoint, World3DObservationBatch, WorldSceneROI
from .cue_beliefs import derive_cue_beliefs
from .feedback import apply_world3d_feedback
from .nameplate import attach_nameplate_observations
from .visual_memory import World3DVisualMemory
from .scene_quality import SceneQualityAnalyzer
from .semantic_fusion import SemanticEvidenceFusion
from .traversability import TemporalTraversabilityFusion


_SECTORS = ("FAR_LEFT", "LEFT", "CENTER_LEFT", "CENTER", "CENTER_RIGHT", "RIGHT", "FAR_RIGHT")
_TYPE_LABELS = {
    "unknown_subject_candidate": "UNKNOWN_UNIT",
    "unknown_subject_probe": "UNKNOWN_UNIT",
    "unknown_object_candidate": "UNKNOWN_OBJECT",
    "unknown_scene_candidate": "UNKNOWN_SCENE",
}
_DETECTION_CLASSES = ("NPC", "HOSTILE", "PLAYER", "CORPSE", "GAME_OBJECT",
                      "RESOURCE_NODE", "PET", "UNKNOWN")


def _number(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else default


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class World3DPipeline:
    """Read-only temporal local-world view constructed from existing tracks.

    The object owns *World3D batch publication*, not candidate detection and
    not game semantics.  Unknown remains a useful state throughout the API.
    """

    def __init__(self, *, lost_grace_seconds: float = 1.2, history_size: int = 8) -> None:
        self.lost_grace_seconds = max(0.1, float(lost_grace_seconds))
        self.history_size = max(2, int(history_size))
        self._frames = 0
        self._last_at = 0.0
        self._track_history: dict[str, deque[dict[str, float]]] = {}
        self._locks: dict[str, dict[str, Any]] = {}
        self._probe_requests: deque[dict[str, Any]] = deque(maxlen=32)
        self._scan_requests: deque[dict[str, Any]] = deque(maxlen=16)
        self._last_batch: World3DObservationBatch | None = None
        self._invalidations: deque[dict[str, Any]] = deque(maxlen=16)
        self._traversability_fusion = TemporalTraversabilityFusion()
        self._scene_quality = SceneQualityAnalyzer()
        self._semantic_fusion = SemanticEvidenceFusion()
        self._visual_memory = World3DVisualMemory()

    # ------------------------------ public read-only perception API --------
    def observe(self, frame: tuple[bytes, int, int] | None, context: dict | None,
                tracks: Iterable[dict[str, Any]], scene: WorldSceneROI,
                *, observed_at: float, frame_id: str | None = None,
                client_id: str | None = None,
                camera_motion: dict | None = None) -> World3DObservationBatch:
        """Build one normalized batch from one completed tracked World3D frame."""
        started = time.perf_counter()
        context = context or {}
        if not math.isfinite(float(observed_at)) or observed_at < 0:
            raise ValueError("world3d observation timestamp must be finite monotonic time")
        if self._last_at and observed_at < self._last_at:
            # A late worker result cannot be made safe by reordering its
            # tracks.  Reject it before it can refresh temporal beliefs.
            raise ValueError("world3d observation timestamp regressed")
        source_frame_id = str(frame_id or f"world3d:{self._frames + 1}").strip()
        if not source_frame_id:
            raise ValueError("world3d observation requires source frame_id")
        source_client_id = str(client_id or context.get("client_id") or
                               context.get("session_id") or "offline:unbound").strip()
        if not source_client_id:
            raise ValueError("world3d observation requires client_id")
        try:
            dropped_frames = max(0, int(context.get("dropped_frames") or 0))
        except (TypeError, ValueError):
            dropped_frames = 0
        width = frame[1] if frame else max(1, scene.rect.right)
        height = frame[2] if frame else max(1, scene.rect.bottom)
        self._frames += 1
        self._last_at = observed_at
        roi_payload = self._roi_payload(scene, width, height)
        camera_state, ego_motion = self._motion(camera_motion or {}, context)
        visual_condition, scene_change = self._scene_quality.observe(
            frame, scene, observed_at=observed_at, camera_state=camera_state)
        visual_condition_payload = visual_condition.to_dict()
        normalized_tracks = self._normalize_tracks(
            tracks, scene, width, height, observed_at, ego_motion,
            visual_condition=visual_condition_payload, camera_state=camera_state,
            semantic_evidence=context.get("world3d_semantic_evidence") or (),
            quest_context_active=bool(
                context.get("quest_search") or context.get("quest_local_search")
                or context.get("quest_area_context")))
        normalized_tracks = self._visual_memory.update_tracks(
            normalized_tracks, now=observed_at)
        normalized_tracks = attach_nameplate_observations(
            frame, normalized_tracks,
            soft_targets=context.get("world3d_soft_targets") or ())
        normalized_tracks, feedback_events = apply_world3d_feedback(
            normalized_tracks, context, observed_at=observed_at)
        lifecycle_events = self._track_lifecycle_events(
            normalized_tracks, observed_at=observed_at, scene_change=scene_change)
        detections = self._detections(normalized_tracks, source_frame_id)
        obstacles = self._obstacles(normalized_tracks)
        raw_traversability = self._traversability(scene, width, height, obstacles, frame)
        traversability = self._traversability_fusion.update(
            raw_traversability, observed_at=observed_at, ego_motion=ego_motion,
            motion_feedback=context.get("motion_feedback") or {})
        entrances = self._entrances(normalized_tracks, scene, width, height, frame, context)
        landmarks = self._landmarks(normalized_tracks)
        interactions = self._interactions(normalized_tracks)
        negative = self._negative_evidence(context, observed_at, normalized_tracks)
        geometry = {
            "coordinate_space": "WORLD_VIEWPORT_NORMALIZED",
            "ground_region": {"left": 0.0, "top": .55, "right": 1.0, "bottom": 1.0,
                              "coordinate_space": "WORLD_VIEWPORT_NORMALIZED", "belief": "UNKNOWN"},
            "traversable_regions": [item for item in traversability["sectors"]
                                    if item["free_probability"] >= item["blocked_probability"]],
            "blocked_regions": [item for item in traversability["sectors"]
                                if item["blocked_probability"] > item["free_probability"]],
            "vertical_boundaries": [item for item in obstacles if item["kind_belief"] in {"WALL", "TREE", "ROCK", "UNKNOWN"}],
            "door_candidates": [item for item in entrances if item["kind"] == "DOOR"],
            "entrance_candidates": entrances,
            "unknown_regions": [item for item in traversability["sectors"]
                                if item["unknown_probability"] >= .45],
        }
        diagnostics = {
            "pipeline": "world3d_canonical_v1",
            "frame_index": self._frames,
            "active_tracks": sum(track["lifecycle"] in {"ACTIVE", "REACQUIRED", "TENTATIVE"}
                                 for track in normalized_tracks),
            "detections": len(detections),
            "occluded_tracks": sum(track["lifecycle"] in {"PARTIALLY_OCCLUDED", "OCCLUDED", "LOST_TEMPORARY"}
                                  for track in normalized_tracks),
            "obstacles": len(obstacles), "entrances": len(entrances),
            "nameplates": sum(bool(track.get("nameplate_observation"))
                              for track in normalized_tracks),
            "soft_targets": sum(bool(track.get("soft_target_evidence"))
                                for track in normalized_tracks),
            "landmarks": len(landmarks), "interaction_candidates": len(interactions),
            "identity_probe_requests": list(self._probe_requests),
            "local_scan_requests": list(self._scan_requests),
            "invalidations": list(self._invalidations)[-3:],
            "brightness": visual_condition_payload["brightness"],
            "contrast": visual_condition_payload["contrast"],
            "motion_blur_estimate": visual_condition_payload["motion_blur_estimate"],
            "ui_occlusion_fraction": visual_condition_payload["ui_occlusion_fraction"],
            "scene_visibility_quality": visual_condition_payload["scene_visibility_quality"],
            # Compatibility key used by older diagnostics consumers.
            "visibility_quality": visual_condition_payload["scene_visibility_quality"],
            "scene_change": dict(scene_change) if scene_change else None,
            "perception_profile": dict(context.get("world3d_profile") or {}),
            "source_frame_id": source_frame_id,
            "source_client_id": source_client_id,
            "dropped_frames": dropped_frames,
        }
        frame_event_rows: list[dict[str, Any]] = []
        if dropped_frames:
            frame_event_rows.append({"event_type": "FRAME_DROPPED", "count": dropped_frames,
                                     "timestamp_monotonic": observed_at,
                                     "client_id": source_client_id,
                                     "frame_id": source_frame_id,
                                     "source": "WORLD3D_FRAME_SOURCE"})
        if scene_change:
            frame_event_rows.append({**scene_change, "client_id": source_client_id,
                                     "frame_id": source_frame_id})
        frame_event_rows.extend({**event, "client_id": source_client_id,
                                 "frame_id": source_frame_id}
                                for event in [*lifecycle_events, *feedback_events])
        frame_events = tuple(frame_event_rows)
        batch = World3DObservationBatch(
            frame_id=source_frame_id, timestamp=observed_at, client_id=source_client_id,
            scene_roi=roi_payload, camera_state=camera_state, ego_motion=ego_motion,
            entity_tracks=tuple(normalized_tracks), detections=tuple(detections), scene_geometry=geometry,
            traversability=traversability, obstacles=tuple(obstacles), entrances=tuple(entrances),
            landmarks=tuple(landmarks), interaction_candidates=tuple(interactions),
            negative_evidence=tuple(negative), diagnostics=diagnostics, frame_events=frame_events,
            processing_latency_ms=(time.perf_counter()-started)*1000)
        self._last_batch = batch
        return batch

    def get_track(self, track_id: str) -> dict[str, Any] | None:
        if self._last_batch is None:
            return None
        for track in self._last_batch.entity_tracks:
            if track.get("track_id") == track_id:
                return dict(track)
        return None

    def get_active_tracks(self) -> list[dict[str, Any]]:
        return self.find_candidates({"visible_only": False, "include_occluded": True})

    def find_candidates(self, query: dict | None = None) -> list[dict[str, Any]]:
        query = query or {}
        if self._last_batch is None:
            return []
        minimum = _number(query.get("minimum_confidence"))
        visible_only = bool(query.get("visible_only"))
        include_occluded = bool(query.get("include_occluded", False))
        kind = query.get("kind") or query.get("type")
        role = query.get("role")
        identity = query.get("identity")
        screen_region = query.get("screen_region") or {}
        requested_interactable = query.get("interactable")
        interaction_ids = {item.get("track_id") for item in self.get_interactables()}
        result = []
        for track in self._last_batch.entity_tracks:
            if kind and kind not in {track.get("detector_kind"), track.get("type_beliefs", [{}])[0].get("label")}:
                continue
            if role and not any(belief.get("label") == role for belief in track.get("role_beliefs", [])):
                continue
            if identity and track.get("identity_belief", {}).get("identity") != identity:
                continue
            if requested_interactable is True and track.get("track_id") not in interaction_ids:
                continue
            center = track.get("screen_center") or {}
            if screen_region and not (float(screen_region.get("left", 0.)) <= _number(center.get("x")) <= float(screen_region.get("right", 1.))
                                      and float(screen_region.get("top", 0.)) <= _number(center.get("y")) <= float(screen_region.get("bottom", 1.))):
                continue
            if _number(track.get("confidence")) < minimum:
                continue
            lifecycle = track.get("lifecycle")
            if visible_only and lifecycle not in {"ACTIVE", "REACQUIRED", "TENTATIVE"}:
                continue
            if not include_occluded and lifecycle in {"OCCLUDED", "LOST_TEMPORARY"}:
                continue
            result.append(dict(track))
        return sorted(result, key=lambda item: (-_number(item.get("information_value")), -_number(item.get("confidence"))))

    def get_interactables(self) -> list[dict[str, Any]]:
        return [dict(item) for item in (self._last_batch.interaction_candidates if self._last_batch else ())]

    def get_hostiles(self) -> list[dict[str, Any]]:
        # CV colour/shape does not establish hostility. Only externally fused
        # evidence could populate a HOSTILE_UNIT belief in a future adapter.
        return [track for track in self.find_candidates({"include_occluded": True})
                if any(belief.get("label") == "HOSTILE_UNIT" and belief.get("source") != "WORLD3D_CV"
                       for belief in track.get("type_beliefs", []))]

    def get_corpses(self) -> list[dict[str, Any]]:
        return [track for track in self.find_candidates({"include_occluded": True})
                if (any(belief.get("label") == "CORPSE" for belief in track.get("type_beliefs", []))
                    or _number((track.get("corpse_belief") or {}).get("confidence")) >= .35)]

    def get_quest_objects(self) -> list[dict[str, Any]]:
        return [track for track in self.find_candidates({"include_occluded": True})
                if (any(belief.get("label") == "QUEST_OBJECT" for belief in track.get("type_beliefs", []))
                    or ((track.get("object_belief") or {}).get("quest_role_belief") == "CANDIDATE"))]

    def get_entrances(self) -> list[dict[str, Any]]:
        return [dict(item) for item in (self._last_batch.entrances if self._last_batch else ())]

    def get_traversability(self) -> dict[str, Any]:
        return dict(self._last_batch.traversability) if self._last_batch else {"sectors": []}

    def get_obstacles(self) -> list[dict[str, Any]]:
        return [dict(item) for item in (self._last_batch.obstacles if self._last_batch else ())]

    def get_local_landmarks(self) -> list[dict[str, Any]]:
        return [dict(item) for item in (self._last_batch.landmarks if self._last_batch else ())]

    def get_camera_state(self) -> dict[str, Any]:
        return dict(self._last_batch.camera_state) if self._last_batch else {}

    def get_ego_motion(self) -> dict[str, Any]:
        return dict(self._last_batch.ego_motion) if self._last_batch else {}

    def request_identity_probe(self, track_id: str) -> dict[str, Any]:
        request = {"kind": "IDENTITY_PROBE", "track_id": str(track_id), "requested_at": self._last_at,
                   "status": "REQUESTED", "owner": "WORLD3D_ACTIVE_PERCEPTION"}
        self._probe_requests.append(request)
        return dict(request)

    def request_local_scan(self, query: dict) -> dict[str, Any]:
        request = {"kind": "LOCAL_SCAN", "query": dict(query), "requested_at": self._last_at,
                   "status": "REQUESTED", "owner": "WORLD3D_ACTIVE_PERCEPTION"}
        self._scan_requests.append(request)
        return dict(request)

    def invalidate(self, reason: str) -> None:
        self._track_history.clear()
        self._locks.clear()
        self._traversability_fusion.reset()
        self._scene_quality.reset()
        self._semantic_fusion.reset()
        self._visual_memory.reset()
        self._last_batch = None
        self._invalidations.append({"reason": str(reason), "at": self._last_at})

    def diagnostics(self) -> dict[str, Any]:
        return dict(self._last_batch.diagnostics) if self._last_batch else {
            "pipeline": "world3d_canonical_v1", "status": "no_batch"}

    def debug_overlay(self) -> dict[str, Any]:
        """Renderer-independent overlay primitives for debugger/replay tools.

        Rendering stays outside perception; this provides the annotated data
        (rather than adding a second detector or storing raw screenshots).
        """
        if self._last_batch is None:
            return {"tracks": [], "traversability": [], "obstacles": [], "entrances": [], "camera": {}}
        return {
            "tracks": [{"track_id": track["track_id"], "bbox": dict(track["bbox"]),
                        "detector_kind": track.get("detector_kind"),
                        "appearance": dict(track.get("appearance") or {}),
                        "candidate_labels": list(track.get("candidate_labels") or []),
                        "lifecycle": track["lifecycle"], "confidence": track["confidence"],
                        "bearing": dict(track["bearing"]), "distance": dict(track["distance_belief"]),
                        "occlusion_probability": track["occlusion_probability"],
                        "motion": dict(track["motion"]),
                        "identity_belief": dict(track["identity_belief"]),
                        "interactability": dict(track.get("semantic_interactability") or {}),
                        "type_beliefs": list(track["type_beliefs"]), "role_beliefs": list(track["role_beliefs"])}
                       for track in self._last_batch.entity_tracks],
            "traversability": list(self._last_batch.traversability.get("sectors") or []),
            "obstacles": [dict(item) for item in self._last_batch.obstacles],
            "entrances": [dict(item) for item in self._last_batch.entrances],
            "camera": dict(self._last_batch.camera_state),
        }

    def replay_record(self) -> dict[str, Any]:
        """Deterministic JSON record; the raw-frame owner may attach a path/hash."""
        if self._last_batch is None:
            return {"kind": "WORLD3D_REPLAY", "status": "no_batch"}
        payload = self._last_batch.to_payload()
        records = [
            {"record_type": "FRAME_META", "frame_id": payload["frame_id"],
             "timestamp": payload["timestamp"], "scene_roi": payload["scene_roi"],
             "client_id": payload["client_id"]},
            {"record_type": "DETECTOR_OUTPUT", "detections": payload["detections"]},
            {"record_type": "TRACK_UPDATE", "tracks": payload["entity_tracks"]},
            {"record_type": "CAMERA_MOTION", "camera_state": payload["camera_state"]},
            {"record_type": "EGO_MOTION", "ego_motion": payload["ego_motion"]},
            {"record_type": "GEOMETRY", "scene_geometry": payload["scene_geometry"],
             "traversability": payload["traversability"], "obstacles": payload["obstacles"],
             "entrances": payload["entrances"]},
            {"record_type": "SEMANTIC_FUSION", "entities": [
                {"track_id": track["track_id"], "type_beliefs": track["type_beliefs"],
                 "role_beliefs": track["role_beliefs"], "identity_belief": track["identity_belief"],
                 "evidence_refs": track.get("evidence_refs") or []}
                for track in payload["entity_tracks"]]},
            {"record_type": "NEGATIVE_EVIDENCE", "items": payload["negative_evidence"]},
            {"record_type": "PROBE_REQUEST", "items": list(self._probe_requests)},
            {"record_type": "PROBE_RESULT", "items": [item for item in payload["negative_evidence"]
                                                       if item.get("kind") == "LOCAL_SCAN_UNOBSERVED"]},
        ]
        return {"kind": "WORLD3D_REPLAY", "schema_version": 1,
                "records": records, "debug_overlay": self.debug_overlay(),
                "frame_meta": {"frame_id": payload["frame_id"],
                "timestamp": payload["timestamp"], "scene_roi": payload["scene_roi"]},
                "track_update": payload["entity_tracks"], "camera_motion": payload["camera_state"],
                "ego_motion": payload["ego_motion"], "geometry": payload["scene_geometry"],
                "semantic_fusion": [{"track_id": track["track_id"], "type_beliefs": track["type_beliefs"],
                                     "role_beliefs": track["role_beliefs"], "identity_belief": track["identity_belief"]}
                                    for track in payload["entity_tracks"]],
                "negative_evidence": payload["negative_evidence"],
                "probe_requests": list(self._probe_requests)}

    def set_visual_lock(self, track_id: str, importance: str = "ACTIVE_SKILL_TARGET",
                        expected_duration: float = 2.0) -> None:
        """Retention hint only; it cannot select/control a target."""
        self._locks[str(track_id)] = {"importance": importance,
                                      "expires_at": self._last_at+max(.1, expected_duration)}

    def _track_lifecycle_events(self, tracks: list[dict[str, Any]], *, observed_at: float,
                                scene_change: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Publish termination evidence while preserving historical identity."""
        previous = {str(track.get("track_id")): track
                    for track in (self._last_batch.entity_tracks if self._last_batch else ())}
        current = {str(track.get("track_id")): track for track in tracks}
        events: list[dict[str, Any]] = []
        for track_id, track in current.items():
            if track.get("lifecycle") == "TERMINATED":
                events.append({"event_type": "WORLD3D_TRACK_TERMINATED",
                               "track_id": track_id, "reason": "EXPLICIT_TERMINATION",
                               "timestamp_monotonic": observed_at, "fact": False})
        for track_id, track in previous.items():
            if track_id in current:
                continue
            lifecycle = str(track.get("lifecycle") or "")
            if lifecycle not in {"LOST_TEMPORARY", "LOST", "TERMINATED"} and not scene_change:
                continue
            events.append({
                "event_type": "WORLD3D_TRACK_TERMINATED", "track_id": track_id,
                "reason": "MAJOR_CONTEXT_RESET" if scene_change else "EXPIRED_AFTER_LOSS",
                "timestamp_monotonic": observed_at,
                "identity_history_retained": True, "fact": False,
            })
            self._track_history.pop(track_id, None)
            self._locks.pop(track_id, None)
        return events

    # ------------------------------ normalization and evidence -------------
    @staticmethod
    def _roi_payload(scene: WorldSceneROI, width: int, height: int) -> dict[str, Any]:
        rect = scene.rect
        return {"pixel_rect": rect.to_dict(space="SCREEN_PIXELS"),
                "normalized_rect": {"left": rect.left/width, "top": rect.top/height,
                                    "right": rect.right/width, "bottom": rect.bottom/height,
                                    "coordinate_space": "SCREEN_NORMALIZED"},
                "profile_id": scene.profile, "confidence": 1.0,
                "excluded_rects": [item.to_dict(space="SCREEN_PIXELS") for item in scene.excluded_rects],
                "learned_pixel_rect": (scene.learned_rect or rect).to_dict(
                    space="SCREEN_PIXELS"),
                "hard_excluded_rects": [item.to_dict(space="SCREEN_PIXELS")
                                         for item in scene.hard_excluded_rects]}

    @staticmethod
    def _motion(camera_motion: dict, context: dict) -> tuple[dict[str, Any], dict[str, Any]]:
        dx, dy = _number(camera_motion.get("dx")), _number(camera_motion.get("dy"))
        confidence = _clamp(_number(camera_motion.get("confidence")))
        magnitude = math.hypot(dx, dy)
        motion_kind = str(camera_motion.get("motion_kind") or camera_motion.get("kind") or "").upper()
        if camera_motion.get("rotation_only") is True or camera_motion.get("is_rotation") is True:
            motion_kind = "ROTATION"
        if motion_kind not in {"ROTATION", "LEFT_ROTATION", "RIGHT_ROTATION", "TRANSLATION", "UNKNOWN"}:
            motion_kind = "UNKNOWN"
        movement = context.get("movement") or {}
        player_moving = bool(movement.get("forward") or movement.get("moving") or movement.get("is_moving"))
        player_confidence = .75 if player_moving else .35 if movement else 0.
        camera_state = {"state": "MOVING" if magnitude > .5 and confidence >= .15 else "STABLE",
                        "translation_screen": ScreenPoint(dx, dy, "SCREEN_PIXELS").to_dict(),
                        "yaw_delta": None, "pitch_delta": None, "zoom_change": False,
                        "estimated_from_visual_flow": True, "confidence": confidence,
                        "camera_motion_evidence": {"kind": motion_kind, "confidence": confidence,
                                                   "source": "WORLD3D_GLOBAL_PATCH_FLOW", "fact": False},
                        "optical_flow_summary": {"dx": dx, "dy": dy, "magnitude": round(magnitude, 4),
                                                 "confidence": confidence, "fact": False}}
        ego_motion = {"translation_screen": ScreenPoint(dx, dy, "SCREEN_PIXELS").to_dict(),
                      "rotation_yaw": None, "rotation_pitch": None,
                      "forward_motion_belief": bool(movement.get("forward") or movement.get("moving")),
                      "strafe_belief": bool(movement.get("strafe")), "confidence": confidence,
                      # Preserve a camera rotation label. It is evidence that
                      # screen flow is not collision evidence even if W is held.
                      "motion_kind": motion_kind,
                      "source": "WORLD3D_GLOBAL_PATCH_FLOW",
                      "player_motion_evidence": {"moving": player_moving, "speed": movement.get("speed"),
                                                  "confidence": player_confidence,
                                                  "source": "ADDON_MOVEMENT_TELEMETRY" if movement else "UNAVAILABLE",
                                                  "fact": False}}
        return camera_state, ego_motion

    def _normalize_tracks(self, tracks: Iterable[dict[str, Any]], scene: WorldSceneROI,
                          width: int, height: int, observed_at: float,
                          ego_motion: dict[str, Any], *, visual_condition: dict[str, Any],
                          camera_state: dict[str, Any],
                          semantic_evidence: Iterable[dict[str, Any]],
                          quest_context_active: bool = False) -> list[dict[str, Any]]:
        result = []
        # Entity bboxes are expressed in client pixels, including detections
        # from the learned ROI outside the narrower heuristic scene ROI.
        # WORLD_VIEWPORT_NORMALIZED therefore uses the complete client frame.
        # Normalising against scene.rect produced coordinates above 1 after
        # the learned view was expanded and sent the approach servo astray.
        rw, rh = max(1, width), max(1, height)
        for source in tracks:
            if source.get("source") not in {None, "WORLD3D", "UI_CV"}:
                continue
            item = dict(source)
            track_id = str(item.get("track_id") or f"untracked:{len(result)}")
            bbox = dict(item.get("bbox") or {})
            if not all(isinstance(bbox.get(key), (int, float)) for key in ("left", "top", "right", "bottom")):
                # V3 candidates always have bboxes. A malformed input is not a
                # reason to invent a spatial fact; omit it from the batch.
                continue
            bbox["coordinate_space"] = "SCREEN_PIXELS"
            cx = (float(bbox["left"])+float(bbox["right"]))/2.
            cy = (float(bbox["top"])+float(bbox["bottom"]))/2.
            # A stale or fabricated box wholly outside the current frame has
            # no actionable screen position.  Partial edge boxes are retained
            # and clipped in the normalised view.
            if not (0. <= cx <= width and 0. <= cy <= height):
                continue
            viewport = {"left": _clamp(float(bbox["left"])/rw),
                        "top": _clamp(float(bbox["top"])/rh),
                        "right": _clamp(float(bbox["right"])/rw),
                        "bottom": _clamp(float(bbox["bottom"])/rh),
                        "coordinate_space": "WORLD_VIEWPORT_NORMALIZED"}
            raw_x, raw_y = _clamp(cx/rw), _clamp(cy/rh)
            history = self._track_history.setdefault(track_id, deque(maxlen=self.history_size))
            scale = max(0., (float(bbox["right"])-float(bbox["left"]))/rw *
                        (float(bbox["bottom"])-float(bbox["top"]))/rh)
            prior = history[-1] if history else None
            # Raw detector geometry remains separately available. The smoothed
            # view is only temporal evidence; it never becomes a world point.
            alpha = .45
            smooth_x = raw_x if prior is None else _clamp(alpha*raw_x + (1-alpha)*prior["smooth_x"])
            smooth_y = raw_y if prior is None else _clamp(alpha*raw_y + (1-alpha)*prior["smooth_y"])
            smooth_scale = scale if prior is None else max(0., alpha*scale + (1-alpha)*prior["smooth_scale"])
            dt = max(.001, observed_at-prior["at"]) if prior is not None else 0.
            velocity_x = 0. if prior is None else (smooth_x-prior["smooth_x"])/dt
            velocity_y = 0. if prior is None else (smooth_y-prior["smooth_y"])/dt
            history.append({"at": observed_at, "scale": scale, "x": raw_x, "y": raw_y,
                            "smooth_x": smooth_x, "smooth_y": smooth_y,
                            "smooth_scale": smooth_scale})
            center = ScreenPoint(smooth_x, smooth_y, "WORLD_VIEWPORT_NORMALIZED")
            bearing = BearingEstimate((center.x-.5)*2., (center.y-.5)*2.,
                                      _clamp(_number(item.get("confidence"))*.85)).to_dict()
            scale_delta = history[-1]["smooth_scale"]-history[0]["smooth_scale"] if len(history) > 1 else 0.
            raw_width = max(0., viewport["right"]-viewport["left"])
            raw_height = max(0., viewport["bottom"]-viewport["top"])
            smooth_viewport = {"left": _clamp(smooth_x-raw_width/2), "top": _clamp(smooth_y-raw_height/2),
                               "right": _clamp(smooth_x+raw_width/2), "bottom": _clamp(smooth_y+raw_height/2),
                               "coordinate_space": "WORLD_VIEWPORT_NORMALIZED"}
            distance = self._distance(smooth_scale, scale_delta, item, height=raw_height)
            lifecycle = str(item.get("lifecycle") or item.get("track_state") or "TENTATIVE")
            if lifecycle == "REACQUIRE_CANDIDATE":
                lifecycle = "REACQUIRED"
            if lifecycle not in {"TENTATIVE", "ACTIVE", "PARTIALLY_OCCLUDED", "OCCLUDED", "LOST_TEMPORARY", "REACQUIRED", "LOST", "TERMINATED"}:
                lifecycle = "TENTATIVE"
            temporal_state = str(item.get("temporal_state") or {
                "TENTATIVE": "TENTATIVE", "ACTIVE": "CONFIRMED", "REACQUIRED": "CONFIRMED",
                "PARTIALLY_OCCLUDED": "OCCLUDED", "OCCLUDED": "OCCLUDED",
                "LOST_TEMPORARY": "LOST", "LOST": "LOST",
            }.get(lifecycle, "TENTATIVE"))
            appearance = dict(item.get("appearance") or {})
            residual = _number(appearance.get("residual_motion_trend", appearance.get("residual_motion")))
            motion = "STATIC" if abs(residual) < .08 and len(history) >= 3 else "MOVING" if abs(residual) >= .18 else "UNKNOWN"
            labels = list(item.get("candidate_labels") or [])
            kind = str(item.get("detector_kind") or item.get("kind") or "visual_candidate")
            visual_type = _TYPE_LABELS.get(kind, "UNKNOWN")
            # These are strictly appearance-derived beliefs, never confirmed
            # identity, NPC, hostile, questgiver, or interactable facts.
            type_beliefs = [{"label": visual_type, "confidence": _clamp(_number(item.get("confidence"))),
                             "belief": "CANDIDATE", "source": "WORLD3D_CV", "fact": False}]
            role_beliefs = []
            if any("quest" in str(label) or "overhead" in str(label) for label in labels):
                role_beliefs.append({"label": "QUEST_RELATED_LIKE", "confidence": _clamp(_number(item.get("confidence"))*.78),
                                     "belief": "CANDIDATE", "source": "WORLD3D_APPEARANCE", "fact": False})
            occlusion = _clamp(_number(item.get("occlusion_probability"), .45 if lifecycle in {"OCCLUDED", "LOST_TEMPORARY"} else 0.))
            source_confidence = _clamp(_number(item.get("confidence")))
            source_reliability = _clamp(_number(item.get("source_reliability"), .90))
            freshness_factor = {
                "ACTIVE": 1., "REACQUIRED": .90, "TENTATIVE": .78,
                "PARTIALLY_OCCLUDED": .68, "OCCLUDED": .52,
                "LOST_TEMPORARY": .28, "LOST": .12, "TERMINATED": 0.,
            }.get(lifecycle, .60)
            visibility_factor = _clamp(_number(visual_condition.get("confidence_multiplier"), 1.))
            occlusion_factor = _clamp(1.-.55*occlusion)
            camera_penalty = (.82 if camera_state.get("state") == "MOVING"
                              and _number(camera_state.get("confidence")) >= .45 else 1.)
            contradiction_penalty = _clamp(1.-_number(item.get("contradiction_confidence")))
            effective_confidence = _clamp(
                source_confidence*source_reliability*freshness_factor*visibility_factor
                * occlusion_factor*camera_penalty*contradiction_penalty)
            lock = self._locks.get(track_id)
            priority = lock.get("importance") if lock and lock.get("expires_at", 0.) >= observed_at else "BACKGROUND"
            cue_beliefs = derive_cue_beliefs(
                detector_kind=kind, candidate_labels=labels,
                appearance=appearance, confidence=_number(item.get("confidence")),
                quest_context_active=quest_context_active)
            fused = self._semantic_fusion.fuse(
                track_id, [*(item.get("semantic_evidence") or ()), *semantic_evidence],
                now=observed_at)
            # Appearance remains a candidate even when authoritative evidence
            # confirms another label. It is never silently promoted to fact.
            fused_type_beliefs = [*type_beliefs, *fused["type_beliefs"]]
            fused_role_beliefs = [*role_beliefs, *fused["role_beliefs"]]
            result.append({
                "track_id": track_id, "detector_kind": kind, "semantic_type": "UNKNOWN",
                "confirmed": False, "confidence": effective_confidence,
                "source_confidence": source_confidence,
                "effective_confidence": effective_confidence,
                "confidence_model": {
                    "source_reliability": source_reliability,
                    "freshness_factor": freshness_factor,
                    "visibility_factor": visibility_factor,
                    "occlusion_factor": occlusion_factor,
                    "camera_instability_factor": camera_penalty,
                    "contradiction_factor": contradiction_penalty,
                    "multi_source_agreement": "UNAVAILABLE_OR_NEUTRAL",
                },
                "lifecycle": lifecycle, "temporal_state": temporal_state, "observed_at": observed_at,
                # Provenance only. An upstream-ID restart may be linked by the
                # presentation tracker, but neither ID is an entity identity.
                "upstream_track_id": item.get("upstream_track_id"),
                "upstream_track_aliases": list(item.get("upstream_track_aliases") or []),
                "upstream_association": item.get("upstream_association"),
                "association_evidence": dict(item.get("association_evidence") or {}),
                "bbox": bbox, "viewport_bbox": viewport, "smoothed_viewport_bbox": smooth_viewport,
                "screen_center": center.to_dict(), "raw_screen_center": ScreenPoint(raw_x, raw_y, "WORLD_VIEWPORT_NORMALIZED").to_dict(),
                "bearing": bearing, "distance_belief": distance, "scale_history": list(history),
                "scale_trend": "APPROACHING" if scale_delta > .00035 else "RETREATING" if scale_delta < -.00035 else "STABLE_OR_UNKNOWN",
                "motion": {"class": motion, "residual_screen_motion": residual,
                           "smoothed_velocity": ScreenPoint(velocity_x, velocity_y, "WORLD_VIEWPORT_NORMALIZED_PER_SECOND").to_dict(),
                           "ego_motion_compensated": True, "confidence": _clamp(_number(item.get("confidence"))*.65)},
                "type_beliefs": fused_type_beliefs, "role_beliefs": fused_role_beliefs,
                "identity_belief": fused["identity_belief"],
                "hostility_belief": fused["hostility_belief"],
                "alive_belief": fused["alive_belief"],
                "semantic_interactability": fused["interactability"],
                "evidence_refs": fused["evidence_refs"],
                "field_freshness": {"screen_position": "FRESH", **fused["field_freshness"]},
                "last_visual_seen": observed_at,
                "last_semantic_confirmed": (observed_at if fused["evidence_refs"] else None),
                "last_identity_confirmed": (observed_at
                                            if fused["identity_belief"]["state"] == "CONFIRMED"
                                            else None),
                "appearance": appearance, "candidate_labels": labels,
                "visual_signature": dict(item.get("visual_signature") or {}),
                **cue_beliefs,
                "visual_relations": list(item.get("visual_relations") or []),
                "occlusion_probability": occlusion, "visibility": "OCCLUDED" if occlusion >= .5 else "VISIBLE",
                "track_priority": priority,
                "information_value": self._information_value(item, labels, lifecycle, distance),
                "source": "WORLD3D",
            })
        return result

    @staticmethod
    def _detections(tracks: list[dict[str, Any]], frame_id: str) -> list[dict[str, Any]]:
        """Materialize current-frame detector evidence without recognition.

        The V5 detection contract intentionally does *not* promote a visual
        candidate to NPC/HOSTILE/etc.  Until a separate non-CV ground-truth
        source confirms a class, the normalized probability mass stays on
        UNKNOWN.  Candidate salience remains in ``confidence`` instead.
        """
        result: list[dict[str, Any]] = []
        for index, track in enumerate(tracks, start=1):
            detection_id = f"{frame_id}:detection:{index}"
            distribution = {label: (1.0 if label == "UNKNOWN" else 0.0)
                            for label in _DETECTION_CLASSES}
            detection = {
                "detection_id": detection_id,
                "frame_id": frame_id,
                "track_id": track["track_id"],
                "class_distribution": distribution,
                "bbox": dict(track["bbox"]),
                "confidence": track["confidence"],
                "optional_features": {
                    "detector_kind": track["detector_kind"],
                    "candidate_labels": list(track.get("candidate_labels") or []),
                    "appearance": dict(track.get("appearance") or {}),
                },
                "source": "WORLD3D_CV",
                "fact": False,
            }
            track["latest_detection_id"] = detection_id
            track["latest_detection_frame_id"] = frame_id
            result.append(detection)
        return result

    @staticmethod
    def _distance(scale: float, scale_delta: float, item: dict[str, Any], *, height: float | None = None) -> dict[str, Any]:
        height = _number(item.get("bbox_height_fraction")) if height is None else max(0., float(height))
        if height >= .30:
            bucket = "VERY_NEAR"
        elif height >= .16:
            bucket = "NEAR"
        elif height >= .07:
            bucket = "MID"
        elif height > .01:
            bucket = "FAR"
        else:
            bucket = "UNKNOWN"
        evidence = ["bbox_scale"]
        if scale_delta > .00035:
            evidence.append("scale_increasing")
        elif scale_delta < -.00035:
            evidence.append("scale_decreasing")
        return {"bucket": bucket, "unit_or_relative_scale": "RELATIVE_SCREEN_SCALE",
                "metric_value": None, "confidence": _clamp(.35+min(.45, height*2.2)),
                "evidence": evidence, "fact": False}

    @staticmethod
    def _information_value(item: dict[str, Any], labels: list[Any], lifecycle: str,
                           distance: dict[str, Any]) -> float:
        score = _number(item.get("confidence"))*.45
        if lifecycle in {"ACTIVE", "REACQUIRED"}:
            score += .15
        if any("overhead" in str(label) or "quest" in str(label) for label in labels):
            score += .25
        if distance.get("bucket") in {"NEAR", "MID"}:
            score += .1
        if item.get("detector_kind") == "unknown_subject_probe":
            score += .12
        return round(_clamp(score), 4)

    @staticmethod
    def _obstacles(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        obstacles = []
        for track in tracks:
            appearance = track.get("appearance") or {}
            static = _number(appearance.get("static_scene_score"))
            bbox = track["viewport_bbox"]
            height = max(0., _number(bbox.get("bottom"))-_number(bbox.get("top")))
            lower = _number(bbox.get("bottom")) >= .58
            explicit = track.get("detector_kind") == "obstacle_candidate"
            if not explicit and not (static >= .18 and height >= .18 and lower):
                continue
            kind = "UNKNOWN"
            shape = str(appearance.get("shape") or "")
            if "tree" in shape:
                kind = "TREE"
            elif "rock" in shape:
                kind = "ROCK"
            obstacles.append({"track_id": track["track_id"], "bbox": dict(bbox), "kind_belief": kind,
                              "blocking_probability": _clamp(.40+static*.45+height*.15),
                              "center_path_overlap": bool(_number(bbox["left"]) <= .56 and _number(bbox["right"]) >= .44),
                              "persistence_frames": len(track.get("scale_history") or []),
                              "confidence": _clamp(track["confidence"]*.75+static*.2),
                              "timestamp": track["observed_at"], "source": "WORLD3D_GEOMETRY", "fact": False})
        return obstacles

    @staticmethod
    def _traversability(scene: WorldSceneROI, width: int, height: int, obstacles: list[dict[str, Any]],
                        frame: tuple[bytes, int, int] | None) -> dict[str, Any]:
        sectors = []
        # A cheap lower-viewport texture visibility measurement. It modulates
        # uncertainty only: it cannot claim collision-free world geometry.
        texture = .5
        if frame and len(frame[0]) == width*height*4:
            pixels = np.frombuffer(frame[0], dtype=np.uint8).reshape(height, width, 4)
            crop = pixels[max(scene.rect.top, int(scene.rect.top+scene.rect.height*.58)):scene.rect.bottom,
                          scene.rect.left:scene.rect.right, :3]
            if crop.size:
                texture = _clamp(float(np.std(crop.astype(np.float32)))/80.)
        for index, name in enumerate(_SECTORS):
            left, right = index/len(_SECTORS), (index+1)/len(_SECTORS)
            overlap = [item for item in obstacles
                       if _number(item["bbox"].get("right")) > left and _number(item["bbox"].get("left")) < right]
            blocked = _clamp(max((item["blocking_probability"] for item in overlap), default=0.)*.85)
            unknown = _clamp(.48*(1-texture)+(.16 if not overlap else 0.))
            free = _clamp(1.-blocked-unknown)
            sectors.append({"sector": name, "region": {"left": left, "top": .55, "right": right, "bottom": 1.,
                                                          "coordinate_space": "WORLD_VIEWPORT_NORMALIZED"},
                            "free_probability": round(free, 4), "blocked_probability": round(blocked, 4),
                            "unknown_probability": round(unknown, 4), "obstacle_refs": [item["track_id"] for item in overlap],
                            "evidence": ["lower_view_texture_visibility", *(["obstacle_overlap"] if overlap else [])],
                            "fact": False})
        return {"coordinate_space": "WORLD_VIEWPORT_NORMALIZED", "sectors": sectors,
                "confidence": round(_clamp(.25+texture*.45), 4), "fact": False}

    @staticmethod
    def _entrances(tracks: list[dict[str, Any]], scene: WorldSceneROI, width: int, height: int,
                   frame: tuple[bytes, int, int] | None, context: dict) -> list[dict[str, Any]]:
        found = []
        for track in tracks:
            labels = [str(label) for label in track.get("candidate_labels") or []]
            if not any(any(term in label.casefold() for term in ("door", "entrance", "stairs", "ramp", "portal")) for label in labels):
                continue
            found.append({"track_id": track["track_id"], "bbox": dict(track["viewport_bbox"]), "kind": "UNKNOWN",
                          "open_probability": .5, "traversable_probability": .5,
                          "depth_cue": "candidate_label_context", "context": "detector_hint",
                          "confidence": track["confidence"]*.65, "fact": False})
        # Context-gated darkness/opening heuristic. It is intentionally off in
        # ordinary frames so shadows cannot fill the agent with false doors.
        if not found and frame and context.get("entrance_search") and len(frame[0]) == width*height*4:
            arr = np.frombuffer(frame[0], dtype=np.uint8).reshape(height, width, 4)
            roi = scene.rect
            patch = arr[int(roi.top+roi.height*.36):int(roi.top+roi.height*.82),
                        int(roi.left+roi.width*.28):int(roi.left+roi.width*.72), :3]
            if patch.size and float(patch.max(axis=2).mean()) < 78.:
                found.append({"track_id": None, "bbox": {"left": .28, "top": .36, "right": .72, "bottom": .82,
                                                            "coordinate_space": "WORLD_VIEWPORT_NORMALIZED"},
                              "kind": "UNKNOWN", "open_probability": .42, "traversable_probability": .36,
                              "depth_cue": "dark_cavity_like", "context": "entrance_search", "confidence": .32, "fact": False})
        return found

    @staticmethod
    def _landmarks(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for track in tracks:
            appearance = track.get("appearance") or {}
            if _number(appearance.get("static_scene_score")) < .18 or len(track.get("scale_history") or []) < 3:
                continue
            result.append({"landmark_id": f"WORLD3D:{track['track_id']}", "track_id": track["track_id"],
                           "appearance_signature": dict(appearance), "screen_position": dict(track["screen_center"]),
                           "type_belief": "UNKNOWN", "first_seen": track["scale_history"][0]["at"],
                           "last_seen": track["observed_at"], "confidence": track["confidence"]*.65, "fact": False})
        return result

    @staticmethod
    def _interactions(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for track in tracks:
            labels = [str(item) for item in track.get("candidate_labels") or []]
            distance = track["distance_belief"]
            cue_belief = track.get("interactability_belief") or {}
            cue = (any("interact" in label.casefold() for label in labels)
                   or _number(cue_belief.get("confidence")) >= .5)
            possible = cue or (track["detector_kind"] in {"unknown_subject_candidate", "unknown_subject_probe"}
                               and distance.get("bucket") in {"VERY_NEAR", "NEAR"})
            if not possible:
                continue
            state = "INTERACTION_READY" if cue and distance.get("bucket") == "VERY_NEAR" else "POSSIBLE"
            result.append({"track_id": track["track_id"], "state": state,
                           "probability": round(_clamp(track["confidence"]*(.88 if cue else .46)), 4),
                           "bearing": dict(track["bearing"]), "distance_belief": dict(distance),
                           "evidence": (list(cue_belief.get("evidence") or ())
                                        if cue else ["near_unknown_subject"]),
                           "fact": False})
        return result

    def _negative_evidence(self, context: dict, observed_at: float,
                           tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output = []
        for request in list(self._scan_requests):
            if request.get("status") != "REQUESTED":
                continue
            if observed_at-request["requested_at"] < .7:
                continue
            query = request.get("query") or {}
            label = str(query.get("label") or query.get("kind") or "requested_candidate")
            if not any(label in str(track.get("detector_kind")) or label in map(str, track.get("candidate_labels") or [])
                       for track in tracks):
                request["status"] = "UNOBSERVED"
                output.append({"kind": "LOCAL_SCAN_UNOBSERVED", "query": dict(query), "observed_at": observed_at,
                               "coverage": context.get("search_coverage"), "confidence": .35, "fact": False})
        return output
