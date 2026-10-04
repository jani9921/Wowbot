"""Human-reviewed annotation primitives for the World3D YOLO dataset.

Machine candidates remain proposals until a reviewer explicitly accepts them.
This module contains no GUI and no runtime authority; tools build on these
deterministic conversion and suppression functions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable
from uuid import uuid4

from .models import PixelRect, WorldCandidate
from .video_dataset import WORLD3D_YOLO_CLASSES


COCO_BOOTSTRAP_CLASSES: dict[str, int] = {
    "person": WORLD3D_YOLO_CLASSES.index("humanoid_unit_like"),
    "bird": WORLD3D_YOLO_CLASSES.index("creature_unit_like"),
    "cat": WORLD3D_YOLO_CLASSES.index("creature_unit_like"),
    "dog": WORLD3D_YOLO_CLASSES.index("creature_unit_like"),
    "horse": WORLD3D_YOLO_CLASSES.index("creature_unit_like"),
    "sheep": WORLD3D_YOLO_CLASSES.index("creature_unit_like"),
    "cow": WORLD3D_YOLO_CLASSES.index("creature_unit_like"),
    "elephant": WORLD3D_YOLO_CLASSES.index("creature_unit_like"),
    "bear": WORLD3D_YOLO_CLASSES.index("creature_unit_like"),
    "zebra": WORLD3D_YOLO_CLASSES.index("creature_unit_like"),
    "giraffe": WORLD3D_YOLO_CLASSES.index("creature_unit_like"),
}
ANNOTATION_ASSIST_CLASSES: dict[str, int] = {
    name: index for index, name in enumerate(WORLD3D_YOLO_CLASSES)
}


@dataclass(slots=True)
class AnnotationBox:
    box_id: str
    left: int
    top: int
    right: int
    bottom: int
    class_id: int
    confidence: float
    status: str = "PROPOSED"
    source: str = "WORLD3D_V3_PROPOSAL"
    candidate_kind: str = ""

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "AnnotationBox":
        return cls(**{key: payload[key] for key in cls.__dataclass_fields__ if key in payload})


def suggested_class(candidate: WorldCandidate) -> int | None:
    """Map only appearance families to a review suggestion, never semantics."""
    labels = {str(label).lower() for label in candidate.candidate_labels}
    kind = candidate.kind.lower()
    if "symbol" in kind:
        return WORLD3D_YOLO_CLASSES.index("overhead_symbol_like")
    if "object" in kind:
        if "outline_like_cue" in labels:
            return WORLD3D_YOLO_CLASSES.index("quest_object_outline_like")
        return WORLD3D_YOLO_CLASSES.index("world_object_like")
    if "subject" in kind:
        if "learned_corpse_like" in labels:
            return WORLD3D_YOLO_CLASSES.index("corpse_like")
        # Geometry alone cannot decide humanoid versus creature. Humanoid is
        # merely the initial review cursor and must be confirmed or changed.
        return WORLD3D_YOLO_CLASSES.index("humanoid_unit_like")
    if "scene" in kind and "entrance" in " ".join(labels):
        return WORLD3D_YOLO_CLASSES.index("entrance_or_door_like")
    return None


def supported_review_proposal(candidate: WorldCandidate) -> bool:
    """Require corroborating appearance evidence before burdening a reviewer.

    The runtime keeps broad UNKNOWN proposals for active perception. Annotation
    seeding has a different cost model: low recall is acceptable because the
    reviewer can draw a missing box, while hundreds of scenery boxes defeat
    the purpose of semi-automatic labelling.
    """
    labels = {str(label).lower() for label in candidate.candidate_labels}
    appearance = candidate.appearance
    kind = candidate.kind.lower()
    learned = bool(appearance.get("source_detector"))
    track_hits = int(appearance.get("track_hits") or 0)
    if learned:
        return True
    if "subject" in kind:
        # Sparse video sampling makes camera residuals unsafe as pseudo-label
        # evidence. Require a stable overhead/nameplate relation instead.
        return track_hits >= 2 and bool(labels.intersection({
            "possible_nameplate_like", "overhead_cue", "subject_probe_like",
            "learned_subject_like",
        }))
    if "symbol" in kind:
        badge = float(appearance.get("quest_badge_likeness") or 0.0)
        return ("quest_badge_like" in labels and badge >= .70
                and bool(appearance.get("dark_badge_surround")))
    if "object" in kind:
        return bool(labels.intersection({"learned_object_like", "outline_like_cue",
                                         "interact_cue_like"}))
    return False


def proposal_from_candidate(candidate: WorldCandidate, width: int, height: int,
                            *, minimum_confidence: float = .54,
                            require_support: bool = True) -> AnnotationBox | None:
    class_id = suggested_class(candidate)
    if (class_id is None or candidate.confidence < minimum_confidence
            or (require_support and not supported_review_proposal(candidate))):
        return None
    rect = candidate.rect
    left, top = max(0, rect.left), max(0, rect.top)
    right, bottom = min(width, rect.right), min(height, rect.bottom)
    if right - left < 8 or bottom - top < 8:
        return None
    return AnnotationBox(
        box_id=uuid4().hex[:12], left=left, top=top, right=right, bottom=bottom,
        class_id=class_id, confidence=round(float(candidate.confidence), 4),
        candidate_kind=candidate.kind,
    )


def intersection_over_union(first: AnnotationBox, second: AnnotationBox) -> float:
    width = max(0, min(first.right, second.right) - max(first.left, second.left))
    height = max(0, min(first.bottom, second.bottom) - max(first.top, second.top))
    intersection = width * height
    union = first.width * first.height + second.width * second.height - intersection
    return intersection / union if union else 0.0


def suppress_overlapping_proposals(boxes: Iterable[AnnotationBox], *, threshold: float = .65,
                                   limit: int = 14) -> list[AnnotationBox]:
    """Confidence-ordered, class-agnostic NMS for noisy review proposals."""
    kept: list[AnnotationBox] = []
    for box in sorted(boxes, key=lambda item: item.confidence, reverse=True):
        if any(intersection_over_union(box, accepted) >= threshold for accepted in kept):
            continue
        kept.append(box)
        if len(kept) >= limit:
            break
    return kept


def yolo_line(box: AnnotationBox, width: int, height: int) -> str:
    if not 0 <= box.class_id < len(WORLD3D_YOLO_CLASSES):
        raise ValueError("invalid class id")
    if width < 1 or height < 1 or box.width < 1 or box.height < 1:
        raise ValueError("invalid image or box dimensions")
    center_x = (box.left + box.right) / (2.0 * width)
    center_y = (box.top + box.bottom) / (2.0 * height)
    box_width = box.width / width
    box_height = box.height / height
    return f"{box.class_id} {center_x:.6f} {center_y:.6f} {box_width:.6f} {box_height:.6f}"


def contains(box: AnnotationBox, x: int, y: int) -> bool:
    return box.left <= x <= box.right and box.top <= y <= box.bottom


def bootstrap_box(label: str, confidence: float, coordinates: Iterable[float],
                  width: int, height: int, *, excluded: Iterable[PixelRect] = (),
                  minimum_confidence: float = .20) -> AnnotationBox | None:
    """Convert an allowed generic pretrained detection into a review proposal."""
    normalized_label = label.strip().lower()
    class_id = COCO_BOOTSTRAP_CLASSES.get(normalized_label)
    source = "COCO_BOOTSTRAP_REVIEW"
    if class_id is None:
        class_id = ANNOTATION_ASSIST_CLASSES.get(normalized_label)
        source = "LEARNED_ANNOTATION_ASSIST_REVIEW"
    values = tuple(float(value) for value in coordinates)
    if class_id is None or len(values) != 4 or confidence < minimum_confidence:
        return None
    left, top, right, bottom = values
    left, top = max(0, round(left)), max(0, round(top))
    right, bottom = min(width, round(right)), min(height, round(bottom))
    if right - left < 8 or bottom - top < 12:
        return None
    center_x, center_y = (left + right) // 2, (top + bottom) // 2
    if any(rect.left <= center_x <= rect.right and rect.top <= center_y <= rect.bottom
           for rect in excluded):
        return None
    return AnnotationBox(
        box_id=uuid4().hex[:12], left=left, top=top, right=right, bottom=bottom,
        class_id=class_id, confidence=round(float(confidence), 4), status="PROPOSED",
        source=source, candidate_kind=f"pretrained_{normalized_label}",
    )
