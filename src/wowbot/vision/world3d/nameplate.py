"""Appearance-only nameplate and soft-target evidence for World3D tracks."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

try:
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:  # pragma: no cover
    import numpy as np


def _clamp(value: object) -> float:
    try:
        return max(0., min(1., float(value)))
    except (TypeError, ValueError):
        return 0.


def attach_nameplate_observations(
        frame: tuple[bytes, int, int] | None,
        tracks: Iterable[dict[str, Any]],
        *, soft_targets: Iterable[dict[str, Any]] = (),
        ) -> list[dict[str, Any]]:
    """Attach visual plate evidence without recognizing an entity or role."""
    result = [deepcopy(track) for track in tracks]
    by_id = {str(track.get("track_id")): track for track in result}
    pixels = None
    width = height = 0
    if frame:
        raw, width, height = frame
        if width > 0 and height > 0 and len(raw) == width*height*4:
            pixels = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)

    for track in result:
        appearance = track.get("appearance") or {}
        plate = appearance.get("nameplate_bbox")
        labels = set(map(str, track.get("candidate_labels") or ()))
        if not isinstance(plate, dict) or "possible_nameplate_like" not in labels:
            continue
        if not all(isinstance(plate.get(key), (int, float))
                   for key in ("left", "top", "right", "bottom")):
            continue
        bbox = {key: int(plate[key]) for key in ("left", "top", "right", "bottom")}
        bbox["coordinate_space"] = "SCREEN_PIXELS"
        observation: dict[str, Any] = {
            "bbox": bbox,
            "bar_bbox": dict(bbox),
            "text_region": {
                "left": max(0, bbox["left"]-20), "top": max(0, bbox["top"]-18),
                "right": min(width or bbox["right"]+20, bbox["right"]+20),
                "bottom": bbox["top"], "coordinate_space": "SCREEN_PIXELS",
            },
            "relation_color_belief": {
                "label": str(appearance.get("hue_family") or "UNKNOWN").upper(),
                "confidence": round(_clamp(track.get("source_confidence", track.get("confidence")))*.55, 4),
                "source": "NAMEPLATE_COLOR_APPEARANCE", "fact": False,
            },
            "health_fraction_belief": {"value": None, "confidence": 0., "fact": False},
            "cast_state": {"state": "UNKNOWN", "confidence": 0., "fact": False},
            "selected_state": {"state": "UNKNOWN", "confidence": 0., "fact": False},
            "associated_track_id": track.get("track_id"),
            "association_evidence": ["plate_above_associated_subject", "shared_temporal_track"],
            "identity_authority": False,
            "fact": False,
        }
        if pixels is not None:
            observation.update(_pixel_cues(pixels, bbox, width, height))
        track["nameplate_observation"] = observation

    for row in soft_targets:
        track = by_id.get(str(row.get("track_id") or ""))
        if track is None:
            continue
        selected = bool(row.get("selected") or row.get("highlighted") or row.get("soft_targeted"))
        confidence = _clamp(row.get("confidence"))
        track["soft_target_evidence"] = {
            "candidate_type": str(row.get("candidate_type") or "UNKNOWN"),
            "screen_anchor": dict(row.get("screen_anchor") or track.get("screen_center") or {}),
            "selected_or_highlighted": selected,
            "confidence": confidence,
            "source": str(row.get("source") or "ACTION_TARGETING_VISUAL_CUE"),
            "identity_authority": False, "fact": False,
        }
        # It is an attention prior only. It cannot alter identity/type/role.
        track["information_value"] = min(1., float(track.get("information_value", 0.))
                                         + (.12*confidence if selected else .04*confidence))
        if track.get("nameplate_observation"):
            track["nameplate_observation"]["selected_state"] = {
                "state": "SELECTED_LIKE" if selected else "NOT_SELECTED_LIKE",
                "confidence": confidence, "fact": False,
            }
    return result


def _pixel_cues(pixels, bbox: dict[str, int], width: int, height: int) -> dict[str, Any]:
    left, top = max(0, bbox["left"]), max(0, bbox["top"])
    right, bottom = min(width, bbox["right"]), min(height, bbox["bottom"])
    plate_width = max(1, right-left)
    pad = max(4, plate_width//4)
    region = pixels[top:bottom, max(0, left-pad):min(width, right+pad), :3]
    health = {"value": None, "confidence": 0., "fact": False}
    if region.size:
        maximum = region.max(axis=2).astype(np.int16)
        minimum = region.min(axis=2).astype(np.int16)
        chromatic = (maximum > 95) & ((maximum-minimum) > 28)
        columns = chromatic.mean(axis=0) >= .20
        indexes = np.flatnonzero(columns)
        if indexes.size >= 4:
            # The surrounding plate width is only a visual denominator, so
            # this remains a low-confidence relative fill estimate.
            value = min(1., float(indexes[-1]-indexes[0]+1)/max(1., region.shape[1]))
            health = {"value": round(value, 4), "confidence": .38,
                      "unit": "RELATIVE_VISIBLE_BAR_FILL", "fact": False}
    cast_strip = pixels[min(height, bottom+1):min(height, bottom+18),
                        max(0, left-pad):min(width, right+pad), :3]
    cast = {"state": "UNKNOWN", "confidence": 0., "fact": False}
    if cast_strip.size:
        maximum = cast_strip.max(axis=2).astype(np.int16)
        minimum = cast_strip.min(axis=2).astype(np.int16)
        candidate = (maximum > 120) & ((maximum-minimum) > 32)
        longest = _longest_true_run(candidate.mean(axis=0) >= .18)
        if longest >= plate_width*.45:
            cast = {"state": "CAST_BAR_LIKE", "confidence": .46,
                    "source": "SECONDARY_HORIZONTAL_BAR_APPEARANCE", "fact": False}
    return {"health_fraction_belief": health, "cast_state": cast}


def _longest_true_run(values) -> int:
    longest = current = 0
    for value in values.tolist():
        current = current+1 if value else 0
        longest = max(longest, current)
    return longest

