"""PerceptionWorker sources: World3D, world map, minimap, candidate merge and canonical evidence.

Split out of perception.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import math
import time
import numpy as np
from wowbot.vision.world3d.scene import build_scene_roi
from wowbot.vision.world3d.validation import validate_batch
from .obstacle_perception import tag_obstacle_candidates


def _minimap_marker_payload(marker, left, top, width, height, *, center=None, radius=None, signature=None, bbox=None,
                            heading=None):
    if center is None:
        center = type("Point", (), {"x": width/2-left, "y": height/2-top})()
    if radius is None:
        radius = min(width, height)/2
    dx = marker.position.x - center.x
    dy = marker.position.y - center.y
    payload = {"kind": "unknown_minimap_marker", "detector_kind": "unknown_minimap_marker",
            "semantic_type": "UNKNOWN", "belief": "CANDIDATE",
            "confidence": marker.confidence, "source": "MINIMAP_CV",
            "confirmed": False, "x": (marker.position.x+left)/width,
            "y": 1-(marker.position.y+top)/height, "bearing": marker.bearing_degrees,
            "appearance": {"color": marker.marker_color, "symbol": marker.symbol},
            "candidate_labels": list(marker.candidate_labels), "visual_evidence": list(marker.evidence),
            "local_position": {"dx": dx, "dy": dy, "distance": math.hypot(dx, dy),
                               "angle": (math.degrees(math.atan2(dx, -dy))+360.0) % 360.0,
                               "normalized_dx": dx/radius if radius else dx,
                               "normalized_dy": dy/radius if radius else dy},
            "coordinate_space": "MINIMAP_LOCAL", "player_local": {"x": 0.0, "y": 0.0},
            "inspectable": False}
    if heading is not None:
        payload["minimap_heading"] = {"degrees": heading.degrees, "confidence": heading.confidence,
                                      "source": "ADDON_PLAYER_ORIENTATION", "fact": False}
    if signature:
        payload["visual_signature"] = signature
    if bbox:
        payload["bbox"] = bbox
    return payload


class PerceptionSourcesMixin:
    """Methods of PerceptionWorker (perception.py); moved verbatim."""

    @classmethod
    def _live_projection(cls, item: dict) -> dict:
        """Current track state only; temporal histories remain manager-owned."""
        return {key: value for key, value in item.items()
                if key not in cls._INTERNAL_HISTORY_FIELDS}

    @staticmethod
    def _fast_debug_overlay(items: list[dict], canonical_overlay: dict | None = None,
                            *, player_name: str | None = None) -> dict:
        """Current tracker boxes plus slower canonical geometry.

        The viewer is diagnostic-only and must never force the 30 Hz tracker
        through the complete canonical scene pipeline merely to draw a box.
        """
        canonical_overlay = canonical_overlay or {}
        tracks = []
        for item in items:
            bbox = item.get("bbox") or {}
            if not all(isinstance(bbox.get(key), (int, float))
                       for key in ("left", "top", "right", "bottom")):
                continue
            appearance = dict(item.get("appearance") or {})
            relations = item.get("visual_relations") or ()
            has_independent_anchor = any(
                isinstance(relation, dict)
                and str(relation.get("type") or "").upper() in {"ABOVE", "GROUP_MEMBER"}
                and str(relation.get("belief") or "").upper() == "SUPPORTED"
                for relation in relations)
            visual_group = (item.get("visual_group")
                            if isinstance(item.get("visual_group"), dict) else {})
            has_independent_anchor = bool(
                has_independent_anchor
                or str(visual_group.get("belief") or "").upper() == "SUPPORTED")
            self_player_name = (
                str(player_name or "").strip()
                if appearance.get("self_avatar_suppression_hint") and not has_independent_anchor
                else "")
            tracks.append({
                "track_id": item.get("track_id"), "bbox": dict(bbox),
                "detector_kind": item.get("detector_kind") or item.get("kind"),
                "appearance": appearance,
                "candidate_labels": list(item.get("candidate_labels") or ()),
                "lifecycle": item.get("lifecycle") or item.get("state") or "ACTIVE",
                "confidence": float(item.get("confidence") or 0.),
                "self_player_avatar": bool(self_player_name),
                "display_name": self_player_name or None,
            })
        return {
            "tracks": tracks,
            "traversability": list(canonical_overlay.get("traversability") or ()),
            "obstacles": list(canonical_overlay.get("obstacles") or ()),
            "entrances": list(canonical_overlay.get("entrances") or ()),
            "camera": dict(canonical_overlay.get("camera") or {}),
        }

    @staticmethod
    def _world(frame, at, geometry):
        raw, width, height = frame
        if len(raw) != width*height*4:
            return []
        if (geometry or {}).get("world_map_open"):
            from wowbot.vision.adapters.world_map import detect_world_map
            return detect_world_map(raw, width, height, observed_at=at).markers
        # Compatibility entry point for offline tools. Runtime uses the
        # stateful v2 method below.
        from wowbot.vision.world3d.candidates import detect_world_candidates
        return detect_world_candidates(raw, width, height, build_scene_roi(width, height))

    def _world_map(self, frame, at, geometry):
        raw, width, height = frame
        if len(raw) != width*height*4:
            return []
        return self.world_map_resolver.process(frame, at, geometry).markers

    def _world_v2(self, frame, at, geometry):
        raw, width, height = frame
        if (geometry or {}).get("world_map_open") or len(raw) != width*height*4:
            return self._world(frame, at, geometry)
        scene = self.scene_extractor.extract(frame)
        return self.world_candidate_detector.detect(
            frame, scene, observed_at=at, ui_hints=geometry)

    @staticmethod
    def _minimap(frame, at, geometry):
        if not geometry or not geometry.get("visible"):
            return []
        from wowbot.vision.adapters.minimap import detect_minimap
        from wowbot.vision.minimap_geometry import MinimapGeometry
        geom = MinimapGeometry(geometry["center_x"], geometry["center_y"], geometry["radius_fraction"])
        if not (0 < geom.center_x_fraction < 1 and 0 < geom.center_y_fraction < 1 and .01 < geom.radius_fraction < .3):
            return []
        raw, width, height = frame
        center, radius = geom.center(width, height), geom.radius(width, height)
        # Full pixel resolution, only unused surroundings cropped. Padding keeps
        # the circular edge context. Convert results back to client coordinates.
        left, top = max(0, math.floor(center.x-radius-8)), max(0, math.floor(center.y-radius-8))
        # Existing detectors use round-to-even for centroids: an even translation
        # preserves half-pixel rounding and target-vs-glyph distance thresholds.
        left, top = left-left % 2, top-top % 2
        right, bottom = min(width, math.ceil(center.x+radius+9)), min(height, math.ceil(center.y+radius+9))
        cw, ch = right-left, bottom-top
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
        crop = pixels[top:bottom, left:right].tobytes()
        local = MinimapGeometry((center.x-left)/cw, (center.y-top)/ch, radius/ch)
        obs = detect_minimap(crop, cw, ch, observed_at=at, geometry=local,
                             heading_degrees=geometry.get("player_orientation"))
        from wowbot.vision.visual_signature import build_visual_signature
        from wowbot.vision.world3d.models import PixelRect
        markers = list(obs.markers)
        from wowbot.vision.map_markers import get_learned_map_detector, merge_minimap_markers
        learned = get_learned_map_detector("MINIMAP")
        if learned is not None and learned.status == "ready":
            learned_markers, _ = learned.detect(
                np.ascontiguousarray(pixels[top:bottom, left:right, :3]))
            # Rim arrows legitimately sit outside the heuristic usable disc.
            limit = obs.center_radius_px * 1.08
            learned_markers = [
                marker for marker in learned_markers
                if math.hypot(marker.position.x-obs.player_marker.x,
                              marker.position.y-obs.player_marker.y) <= limit]
            markers = merge_minimap_markers(learned_markers, markers)
        result = []
        for marker in markers:
            local_rect = PixelRect(max(0, int(marker.position.x)-8), max(0, int(marker.position.y)-8),
                                   min(cw, int(marker.position.x)+9), min(ch, int(marker.position.y)+9))
            signature = build_visual_signature(crop, cw, ch, local_rect, kind=marker.marker_type,
                                               representation_space="MINIMAP")
            bbox = {"left": local_rect.left+left, "top": local_rect.top+top,
                    "right": local_rect.right+left, "bottom": local_rect.bottom+top,
                    "coordinate_space": "CLIENT_PIXELS"}
            result.append(_minimap_marker_payload(marker, left, top, width, height,
                                                  center=obs.player_marker, radius=obs.usable_radius_px,
                                                  signature=signature, bbox=bbox, heading=obs.heading))
        # Quest objective area (light-blue outline), user 2026-10-03.
        try:
            from wowbot.vision.minimap_quest_area import detect_quest_area
            bgr = pixels[top:bottom, left:right, :3]
            area = detect_quest_area(np.ascontiguousarray(bgr[..., ::-1]),
                                     (center.x-left, center.y-top), radius)
        except Exception:  # noqa: BLE001 -- an optional cue must not stop perception
            area = None
        # Selected-target marker (reaction-coloured dot in a gold crosshair).
        try:
            from wowbot.vision.minimap_target_marker import detect_target_markers
            target_markers = detect_target_markers(
                np.ascontiguousarray(pixels[top:bottom, left:right, 2::-1]),
                (center.x-left, center.y-top), radius)
        except Exception:  # noqa: BLE001 -- an optional cue must not stop perception
            target_markers = []
        if target_markers:
            result.append({
                "track_id": "minimap:target_marker", "kind": "minimap_target_marker",
                "detector_kind": "minimap_target_marker", "source": "MINIMAP_CV",
                "semantic_type": "UNKNOWN", "belief": "CANDIDATE", "confirmed": False,
                "confidence": .85, "inspectable": False,
                "x": center.x/width, "y": 1-center.y/height, "observed_at": at,
                "candidate_labels": ["selected_target_marker_like"],
                "minimap_radius_px": float(radius),
                "view_radius_yards": geometry.get("view_radius_yards"),
                "rotate_minimap": geometry.get("rotate_minimap"),
                "markers": target_markers})
        # Quest objective dots (yellow), user 2026-10-04, and their floor
        # (user 2026-10-05): grey = another space, a triangle under/over a
        # dot = the objective is lower/higher than us.
        try:
            from wowbot.vision.minimap_floor_markers import detect_floor_markers
            floor_markers = detect_floor_markers(
                np.ascontiguousarray(pixels[top:bottom, left:right, 2::-1]),
                (center.x-left, center.y-top), radius)
        except Exception:  # noqa: BLE001 -- an optional cue must not stop perception
            floor_markers = []
        dots = [{"offset": marker["offset"], "pixels": marker["pixels"], "floor": marker["floor"],
                 "distance_fraction": round(float(math.hypot(*marker["offset"])), 4)}
                for marker in floor_markers if marker["colour"] == "YELLOW"]
        other_floor = [marker for marker in floor_markers
                       if marker["colour"] == "GREY" or marker["floor"] != "SAME"]
        if other_floor:
            from wowbot.vision.minimap_floor_markers import FLOOR_LABELS
            labels = sorted({label for marker in other_floor for label in FLOOR_LABELS[marker["floor"]]})
            result.append({
                "track_id": "minimap:floor_markers", "kind": "minimap_floor_markers",
                "detector_kind": "minimap_floor_markers", "source": "MINIMAP_CV",
                "semantic_type": "UNKNOWN", "belief": "CANDIDATE", "confirmed": False,
                "confidence": .75, "inspectable": False,
                "x": center.x/width, "y": 1-center.y/height, "observed_at": at,
                "candidate_labels": labels, "minimap_radius_px": float(radius),
                "view_radius_yards": geometry.get("view_radius_yards"),
                "rotate_minimap": geometry.get("rotate_minimap"),
                "markers": other_floor})
        if dots:
            result.append({
                "track_id": "minimap:quest_dots", "kind": "minimap_quest_dot",
                "detector_kind": "minimap_quest_dot", "source": "MINIMAP_CV",
                "semantic_type": "UNKNOWN", "belief": "CANDIDATE", "confirmed": False,
                "confidence": .8, "inspectable": False,
                "x": center.x/width, "y": 1-center.y/height, "observed_at": at,
                "candidate_labels": ["quest_objective_dot_like"],
                "minimap_radius_px": float(radius),
                "view_radius_yards": geometry.get("view_radius_yards"),
                "rotate_minimap": geometry.get("rotate_minimap"),
                "dots": dots})
        if area is not None:
            result.append({
                "track_id": "minimap:quest_area", "kind": "minimap_quest_area",
                "detector_kind": "minimap_quest_area", "source": "MINIMAP_CV",
                "semantic_type": "UNKNOWN", "belief": "CANDIDATE", "confirmed": False,
                "confidence": .85 if area["closed"] else .6, "inspectable": False,
                "x": center.x/width, "y": 1-center.y/height, "observed_at": at,
                "candidate_labels": ["quest_area_outline_like"],
                "minimap_radius_px": float(radius),
                "view_radius_yards": geometry.get("view_radius_yards"),
                "rotate_minimap": geometry.get("rotate_minimap"),
                "quest_area": area})
        return result

    @staticmethod
    def _timed(detector, frame, at, geometry, epoch, source_metadata, diagnostics_source=None):
        started_at = time.monotonic()
        start = time.perf_counter()
        items = detector(frame, at, geometry)
        elapsed = (time.perf_counter()-start)*1000
        # The next frame may already be running when this result is
        # post-processed, so the detector diagnostics travel with the result.
        diagnostics = dict(diagnostics_source()) if diagnostics_source is not None else {}
        geometry = {**geometry, "_started_at": started_at, "_finished_at": time.monotonic(),
                    "_detector_diagnostics": diagnostics}
        return epoch, at, items, elapsed, frame, source_metadata, geometry

    def _candidates(self, detected, width, height, at, raw=None):
        if at-self.last_world_at > 1.:
            self.hits.clear()
        # V3 already fuses the V2 detector with its high-rate patch tracker.
        # Keep the legacy tracker only for compatibility detectors which do
        # not provide stable IDs.
        tracked = tuple(detected) if detected and all(c.track_id is not None for c in detected) \
                  else self.tracker.update(detected)
        self.hits = {c.track_id: self.hits.get(c.track_id, 0)+1 for c in tracked}
        self.last_world_at = at
        result = []
        for c in tracked:
            stable = self.hits[c.track_id]
            inspectable = c.kind in {"unknown_subject_candidate", "unknown_subject_probe"} and stable >= 3
            if c.kind == "unknown_object_candidate":
                inspectable = stable >= 3 and c.confidence >= .60
            bbox = {"left": c.rect.left, "top": c.rect.top, "right": c.rect.right, "bottom": c.rect.bottom,
                    "coordinate_space": "CLIENT_PIXELS"}
            signature = None
            if raw is not None:
                from wowbot.vision.visual_signature import build_visual_signature
                signature = build_visual_signature(raw, width, height, c.rect, kind=c.kind,
                                                   relation=c.relation, class_name=c.class_name)
            result.append({"track_id": f"{self.epoch}:{c.track_id}", "kind": c.kind,
                           # The V3 tracker is the fast World3D identity
                           # authority. Keep its ID as explicit association
                           # evidence so the source-level manager never
                           # invents a second identity after a detector refresh.
                           "upstream_track_id": f"WORLD3D_V3:{c.track_id}",
                           "confidence": c.confidence, "stable_frames": stable,
                           "inspectable": inspectable, "x": (c.rect.left+c.rect.right)/2/width,
                           "y": 1-(c.rect.top+c.rect.bottom)/2/height,
                           "source": "UI_CV" if c.kind.startswith("unknown_ui_") else "WORLD3D",
                           "evidence": c.evidence, "confirmed": False,
                           "semantic_type": "UNKNOWN", "relation_hint": c.relation,
                           "belief": "SUPPORTED" if stable >= 3 else "CANDIDATE",
                           "appearance": dict(c.appearance), "candidate_labels": list(c.candidate_labels),
                           "evidence_roles": {"subject_shape": "PRIMARY",
                                              "nameplate": "SECONDARY" if "nameplate" in c.evidence else "ABSENT"},
                           "bbox": bbox,
                           "bbox_width_fraction": c.rect.width/width,
                           "bbox_height_fraction": c.rect.height/height,
                           "visual_signature": signature})
        return tag_obstacle_candidates(result)

    def _run_canonical(self, source_frame, context, items, width, height, at,
                       metadata, camera_motion, requested_at) -> bool:
        """One canonical World3D evidence batch (pump thread offline, own
        worker live).  Returns whether the batch validated."""
        started = time.perf_counter()
        with self._canonical_lock:
            batch = self.world3d_pipeline.observe(
                source_frame, context, items, build_scene_roi(width, height),
                observed_at=at, frame_id=metadata["frame_id"],
                client_id=metadata["client_id"], camera_motion=camera_motion)
        valid = validate_batch(batch).valid
        self.hard_examples.consider(source_frame[0], width, height, items, at)
        self.world3d_batch = batch
        self._last_canonical_ms = (time.perf_counter()-started)*1000
        self.canonical_rate.mark(requested_at)
        return valid
