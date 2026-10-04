"""Normalized, evidence-only tooltip observations.

The addon remains the authority for tooltip identity.  This adapter merely
preserves the source frame, hover geometry and bounded visual-track association
so downstream fusion can distinguish a current tooltip from an old string.
"""
from __future__ import annotations

import math
from typing import Any


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def _name_from_text(text: str) -> str | None:
    first = text.split("~", 1)[0].strip()
    return first or None


def tooltip_observation(payload: dict[str, Any], *, frame_id: str, observed_at: float,
                        cursor: dict[str, Any] | None = None,
                        candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return one TooltipObservation-shaped, non-factual dictionary.

    A candidate link is spatial evidence only.  It does not turn CV output
    into an entity, and it is omitted when cursor/candidate coordinates are
    stale or ambiguous.
    """
    unit = payload.get("mouseover") or {}
    metadata = unit.get("tooltip_data") if isinstance(unit.get("tooltip_data"), dict) else {}
    text = str(unit.get("tooltip_text") or unit.get("tooltip") or "").strip()
    parsed_name = metadata.get("unit_name") or unit.get("name") or _name_from_text(text)
    parsed_type = metadata.get("raw_type") or metadata.get("object_type") or unit.get("type")
    relation = unit.get("relation") or unit.get("reaction")
    hover = cursor or payload.get("cursor_position") or {}
    x, y = _number(hover.get("nx", hover.get("x"))), _number(hover.get("ny", hover.get("y")))
    visible = bool(text or parsed_name or metadata)
    confidence = (1.0 if metadata.get("guid") or metadata.get("unit_guid") or unit.get("guid")
                  else .88 if parsed_name and text else .65 if text else .0)
    result: dict[str, Any] = {
        "visible": visible,
        "text": text,
        "parsed_name": parsed_name,
        "parsed_type": parsed_type,
        "relation": relation,
        "confidence": confidence,
        "frame_id": str(frame_id),
        "timestamp_monotonic": float(observed_at),
        "source": "ADDON_MOUSEOVER_TOOLTIP",
        "fact": False,
    }
    if x is not None and y is not None:
        result["hover_screen_point"] = {"x": x, "y": y,
                                        "coordinate_space": "CLIENT_BOTTOM_LEFT"}
    else:
        result["hover_screen_point"] = None
    if not visible or x is None or y is None:
        return result
    eligible = [item for item in candidates or ()
                if item.get("source") == "WORLD3D"
                and "subject" in str(item.get("detector_kind") or item.get("kind") or "")
                and _number(item.get("x")) is not None and _number(item.get("y")) is not None]
    if not eligible:
        return result
    nearest = min(eligible, key=lambda item: math.hypot(float(item["x"])-x, float(item["y"])-y))
    distance = math.hypot(float(nearest["x"])-x, float(nearest["y"])-y)
    if distance <= .09:
        result["candidate_track_id"] = nearest.get("track_id")
        result["candidate_frame_id"] = nearest.get("latest_detection_frame_id")
        result["candidate_association"] = "SPATIAL_HYPOTHESIS"
        result["candidate_association_distance"] = round(distance, 6)
    return result
