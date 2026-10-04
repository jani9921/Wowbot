from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from wowbot.vision.models import NavigationVisionObservation

from .candidates import CLASS_COLORS, CLASS_COLOR_ALIASES
from .models import World3DObservationBatch


_DETECTION_CLASSES = frozenset({"NPC", "HOSTILE", "PLAYER", "CORPSE", "GAME_OBJECT",
                                "RESOURCE_NODE", "PET", "UNKNOWN"})


@dataclass(frozen=True, slots=True)
class World3DValidation:
    candidate_count: int
    visible_entity_count: int
    tracked_entity_count: int
    class_entity_count: int
    relation_entity_count: int
    invalid_metadata_count: int
    relation_transition_count: int
    class_palette_valid: bool
    fusion_present: bool
    ready_for_navigation: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "visible_entity_count": self.visible_entity_count,
            "tracked_entity_count": self.tracked_entity_count,
            "class_entity_count": self.class_entity_count,
            "relation_entity_count": self.relation_entity_count,
            "invalid_metadata_count": self.invalid_metadata_count,
            "relation_transition_count": self.relation_transition_count,
            "class_palette_valid": self.class_palette_valid,
            "fusion_present": self.fusion_present,
            "ready_for_navigation": self.ready_for_navigation,
        }


@dataclass(frozen=True, slots=True)
class World3DBatchValidation:
    """Invariant report for canonical World3D batches.

    Validation is intentionally non-mutating: a bad visual observation must
    be diagnosable, never repaired into an invented position or semantic fact.
    """
    valid: bool
    errors: tuple[str, ...]
    track_count: int
    geometry_valid: bool
    semantics_valid: bool


class World3DValidator:
    """Non-mutating validation owner for canonical World3D publications."""

    @staticmethod
    def validate(batch: World3DObservationBatch) -> World3DBatchValidation:
        return validate_batch(batch)


def validate_batch(batch: World3DObservationBatch) -> World3DBatchValidation:
    errors: list[str] = []
    if not str(batch.frame_id).strip():
        errors.append("source_frame_id_missing")
    if not str(batch.client_id).strip():
        errors.append("source_client_id_missing")
    if not math.isfinite(float(batch.timestamp)) or batch.timestamp < 0:
        errors.append("timestamp_not_monotonic")
    detection_ids: set[str] = set()
    for detection in batch.detections:
        detection_id = str(detection.get("detection_id") or "")
        if not detection_id:
            errors.append("detection_missing_id")
        elif detection_id in detection_ids:
            errors.append(f"duplicate_detection_id:{detection_id}")
        detection_ids.add(detection_id)
        if detection.get("frame_id") != batch.frame_id:
            errors.append(f"detection_frame_mismatch:{detection_id}")
        bbox = detection.get("bbox") or {}
        if bbox.get("coordinate_space") != "SCREEN_PIXELS":
            errors.append(f"detection_bbox_coordinate_space:{detection_id}")
        distribution = detection.get("class_distribution")
        if not isinstance(distribution, dict) or set(distribution) != _DETECTION_CLASSES:
            errors.append(f"detection_class_distribution:{detection_id}")
        else:
            try:
                values = [float(value) for value in distribution.values()]
            except (TypeError, ValueError):
                errors.append(f"detection_class_distribution:{detection_id}")
            else:
                if any(not 0. <= value <= 1. for value in values) or not math.isclose(sum(values), 1., abs_tol=1e-6):
                    errors.append(f"detection_class_distribution:{detection_id}")
    for event in batch.frame_events:
        if event.get("event_type") not in {
                "FRAME_DROPPED", "SCENE_CHANGE_OBSERVED", "WORLD3D_TRACK_TERMINATED",
                "WORLD3D_DEATH_TRANSITION", "WORLD3D_BELIEF_FEEDBACK"}:
            errors.append("unknown_frame_event")
            continue
        if event.get("event_type") == "FRAME_DROPPED" and int(event.get("count", 0)) < 1:
            errors.append("invalid_dropped_frame_count")
        if event.get("event_type") == "SCENE_CHANGE_OBSERVED" and not 0. <= float(event.get("change_magnitude", -1.)) <= 1.:
            errors.append("invalid_scene_change_magnitude")
        if event.get("frame_id") != batch.frame_id or event.get("client_id") != batch.client_id:
            errors.append("frame_event_source_mismatch")
    seen: set[str] = set()
    roi = (batch.scene_roi.get("normalized_rect") or {})
    if roi.get("coordinate_space") != "SCREEN_NORMALIZED":
        errors.append("scene_roi_normalized_space_missing")
    for track in batch.entity_tracks:
        track_id = str(track.get("track_id") or "")
        if not track_id:
            errors.append("track_missing_id")
        elif track_id in seen:
            errors.append(f"duplicate_track_id:{track_id}")
        seen.add(track_id)
        bbox = track.get("bbox") or {}
        viewport = track.get("viewport_bbox") or {}
        if bbox.get("coordinate_space") != "SCREEN_PIXELS":
            errors.append(f"bbox_coordinate_space:{track_id}")
        if viewport.get("coordinate_space") != "WORLD_VIEWPORT_NORMALIZED":
            errors.append(f"viewport_coordinate_space:{track_id}")
        if not 0. <= float(track.get("confidence", -1.)) <= 1.:
            errors.append(f"confidence_range:{track_id}")
        if track.get("semantic_type") != "UNKNOWN":
            errors.append(f"cv_semantic_fact:{track_id}")
        if track.get("temporal_state") not in {"TENTATIVE", "CONFIRMED", "OCCLUDED", "LOST", "DEAD"}:
            errors.append(f"track_temporal_state:{track_id}")
        association = track.get("association_evidence") or {}
        if association and association.get("fact") is not False:
            errors.append(f"track_association_fact:{track_id}")
        bearing = track.get("bearing") or {}
        if (bearing.get("coordinate_space") != "CAMERA_RELATIVE_BEARING"
                or not -1. <= float(bearing.get("horizontal", -2.)) <= 1.
                or not -1. <= float(bearing.get("vertical", -2.)) <= 1.):
            errors.append(f"track_bearing_contract:{track_id}")
        distance = track.get("distance_belief") or {}
        if (distance.get("bucket") not in {"VERY_NEAR", "NEAR", "MID", "FAR", "UNKNOWN"}
                or distance.get("unit_or_relative_scale") != "RELATIVE_SCREEN_SCALE"
                or distance.get("metric_value") is not None):
            errors.append(f"track_distance_contract:{track_id}")
        for belief in [*(track.get("type_beliefs") or ()), *(track.get("role_beliefs") or ())]:
            if belief.get("source") in {"WORLD3D_CV", "WORLD3D_APPEARANCE"} and belief.get("fact") is True:
                errors.append(f"visual_belief_marked_fact:{track_id}")
    sectors = batch.traversability.get("sectors") if isinstance(batch.traversability, dict) else None
    geometry_valid = isinstance(sectors, list) and bool(sectors)
    if not geometry_valid:
        errors.append("traversability_sectors_missing")
    semantics_valid = not any(error.startswith(("cv_semantic_fact", "visual_belief_marked_fact")) for error in errors)
    return World3DBatchValidation(valid=not errors, errors=tuple(errors), track_count=len(batch.entity_tracks),
                                  geometry_valid=geometry_valid, semantics_valid=semantics_valid)


def validate_fusion_observation(
    fusion: NavigationVisionObservation,
    candidate_count: int,
) -> World3DValidation:
    world = fusion.world
    entities = tuple(world.visible_entities) if world is not None else ()
    tracked = [e for e in entities if e.get("track_id") is not None]
    class_entities = [e for e in entities if e.get("class_name") is not None]
    relation_entities = [e for e in entities if e.get("relation") is not None]
    transitions = [e for e in entities if bool(e.get("relation_changed"))]

    invalid = 0
    for entity in class_entities:
        class_name = str(entity.get("class_name"))
        class_color = entity.get("class_color")
        if class_name not in CLASS_COLORS:
            invalid += 1
            continue
        allowed = {CLASS_COLORS[class_name], *CLASS_COLOR_ALIASES.get(class_name, ())}
        if class_color not in allowed:
            invalid += 1

    valid_relations = {"friendly", "neutral", "hostile"}
    for entity in relation_entities:
        if entity.get("relation") not in valid_relations:
            invalid += 1

    fusion_present = world is not None and fusion.world_map is not None or world is not None and fusion.minimap is not None or world is not None
    class_palette_valid = invalid == 0
    ready = bool(world is not None and fusion_present and class_palette_valid)

    return World3DValidation(
        candidate_count=candidate_count,
        visible_entity_count=len(entities),
        tracked_entity_count=len(tracked),
        class_entity_count=len(class_entities),
        relation_entity_count=len(relation_entities),
        invalid_metadata_count=invalid,
        relation_transition_count=len(transitions),
        class_palette_valid=class_palette_valid,
        fusion_present=fusion_present,
        ready_for_navigation=ready,
    )
