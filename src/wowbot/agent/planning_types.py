"""Small, dependency-free planning value normalizers."""
from __future__ import annotations

import math

from .models import number


def point(value) -> dict | None:
    """Return a valid normalized-map point without inventing coordinates."""
    if not isinstance(value, dict):
        return None
    x, y = number(value.get("x")), number(value.get("y"))
    if x is None or y is None or not 0 <= x <= 1 or not 0 <= y <= 1 or value.get("map_id") is None:
        return None
    return {**value, "x": x, "y": y}


def world_point(value) -> dict | None:
    """Return only an explicitly API-derived WORLD_YARDS point.

    UI-map X/Y and world X/Y are intentionally never conflated.  Producers
    may attach the conversion as ``world_position`` to retain the original
    map observation and its provenance.
    """
    if not isinstance(value, dict):
        return None
    raw = value.get("world_position") if isinstance(value.get("world_position"), dict) else value
    if raw.get("coordinate_space") != "WORLD_YARDS":
        return None
    x, y = number(raw.get("x")), number(raw.get("y"))
    instance_id = raw.get("instance_id")
    if x is None or y is None or not all(math.isfinite(v) for v in (x, y)) or instance_id is None:
        return None
    return {
        **raw,
        "x": x,
        "y": y,
        "instance_id": instance_id,
        "map_id": value.get("map_id", raw.get("ui_map_id")),
        "ui_map_id": raw.get("ui_map_id", value.get("map_id")),
        "coordinate_space": "WORLD_YARDS",
    }
