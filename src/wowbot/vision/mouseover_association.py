from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class MouseoverAssociation:
    """Read-only association between addon-confirmed mouseover and a Vision track."""

    matched: bool
    track_id: int | None
    distance_px: float | None
    confidence: float
    reason: str


def associate_mouseover(
    mouseover: dict[str, Any] | None,
    cursor_position: dict[str, Any] | None,
    entities: Iterable[Any],
    *,
    screen_width: int,
    screen_height: int,
    max_distance_px: float = 90.0,
) -> MouseoverAssociation:
    """Associate a real mouseover unit with the nearest visible Vision entity.

    The addon remains the source of truth for identity. This helper only answers
    which already-observed Vision track is spatially closest to the cursor.
    It never creates or upgrades an entity identity by itself.
    """
    if not isinstance(mouseover, dict):
        return MouseoverAssociation(False, None, None, 0.0, "no_mouseover")
    if not isinstance(cursor_position, dict):
        return MouseoverAssociation(False, None, None, 0.0, "no_cursor_position")
    if screen_width <= 0 or screen_height <= 0:
        return MouseoverAssociation(False, None, None, 0.0, "invalid_screen_size")

    nx = _number(cursor_position.get("nx"))
    ny = _number(cursor_position.get("ny"))
    if nx is None or ny is None:
        return MouseoverAssociation(False, None, None, 0.0, "invalid_cursor_position")

    cursor_x = nx * screen_width
    cursor_y = ny * screen_height
    best: tuple[float, Any] | None = None
    for entity in entities:
        track_id = getattr(entity, "track_id", None)
        center = getattr(entity, "screen_center", None)
        entity_type = str(getattr(entity, "entity_type", ""))
        if track_id is None or not center or entity_type in {"OBJECT", "OBSTACLE_CANDIDATE", "VISUAL_CANDIDATE", "UNKNOWN"}:
            continue
        try:
            ex, ey = float(center[0]), float(center[1])
        except (TypeError, ValueError, IndexError):
            continue
        distance = hypot(cursor_x - ex, cursor_y - ey)
        if best is None or distance < best[0]:
            best = (distance, entity)

    if best is None:
        return MouseoverAssociation(False, None, None, 0.0, "no_track_candidate")

    distance, entity = best
    if distance > max_distance_px:
        return MouseoverAssociation(False, None, distance, 0.0, "cursor_too_far_from_track")

    # Distance-based confidence is deliberately capped below certainty: the
    # addon identity is certain, the Vision association is only spatial inference.
    confidence = max(0.0, min(0.95, 1.0 - distance / max_distance_px))
    return MouseoverAssociation(
        True,
        int(getattr(entity, "track_id")),
        distance,
        confidence,
        "nearest_visible_track_to_mouseover_cursor",
    )


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result
