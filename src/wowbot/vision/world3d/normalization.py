from __future__ import annotations

from typing import Any

from wowbot.vision.models import WorldObservation

from .models import WorldFrameObservation


def world_frame_to_observation(frame: WorldFrameObservation) -> WorldObservation:
    """Normalize a 3D frame into the shared WorldObservation contract.

    Screen-space candidates are preserved as evidence-rich visible entities.
    Obstacle candidates are deliberately NOT promoted to WorldObservation.obstacles:
    a visual obstacle candidate is not proof of a blocked/traversal-prohibiting path.
    """
    entities: list[dict[str, Any]] = []
    for candidate in frame.candidates:
        cx = (candidate.rect.left + candidate.rect.right) / 2.0
        cy = (candidate.rect.top + candidate.rect.bottom) / 2.0
        entities.append(
            {
                "entity_type": "UNKNOWN",
                "candidate_kind": candidate.kind,
                "screen_space": True,
                "screen_center": {"x": cx, "y": cy},
                "screen_rect": {
                    "left": candidate.rect.left,
                    "top": candidate.rect.top,
                    "right": candidate.rect.right,
                    "bottom": candidate.rect.bottom,
                },
                "confidence": candidate.confidence,
                "relation": candidate.relation,
                "class_name": candidate.class_name,
                "class_color": candidate.class_color,
                "track_id": candidate.track_id,
                "previous_relation": candidate.previous_relation,
                "relation_changed": candidate.relation_changed,
                "evidence": candidate.evidence,
                "appearance": dict(candidate.appearance),
                "candidate_labels": list(candidate.candidate_labels),
                "observed_at": frame.observed_at,
            }
        )

    return WorldObservation(
        visible_entities=tuple(entities),
        obstacles=(),
        observed_at=frame.observed_at,
    )


def _entity_type(kind: str) -> str:
    """Compatibility helper: raw visual kinds never establish semantics."""
    return "UNKNOWN"
