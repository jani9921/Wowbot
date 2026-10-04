"""Frame-stamped World Map state, independent of raster marker hypotheses."""
from __future__ import annotations

from typing import Any


def world_map_state(payload: dict[str, Any], *, frame_id: str, observed_at: float,
                    zoom_revision: int = 0) -> dict[str, Any]:
    """Normalize map telemetry without converting cursors into NPC locations."""
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    map_mouseover = payload.get("map_mouseover") if isinstance(payload.get("map_mouseover"), dict) else {}
    quest_locations = payload.get("quest_locations") if isinstance(payload.get("quest_locations"), list) else []
    open_state = bool(payload.get("world_map_open"))
    pan = payload.get("world_map_pan") if isinstance(payload.get("world_map_pan"), dict) else None
    player_marker = None
    if position.get("x") is not None and position.get("y") is not None:
        player_marker = {"x": position["x"], "y": position["y"],
                         "coordinate_space": "MAP_NORMALIZED", "confidence": .9,
                         "source": "ADDON_MAP_POSITION", "fact": False}
    return {
        "open": open_state,
        "map_id": payload.get("map_id"),
        "zone": payload.get("zone") or payload.get("zone_name"),
        "zoom_revision": max(0, int(zoom_revision)),
        "pan": pan,
        "player_marker": player_marker,
        "quest_objective_regions": [dict(item) for item in quest_locations if isinstance(item, dict)],
        "map_mouseover": {"surface": map_mouseover.get("surface"),
                            "tooltip": map_mouseover.get("tooltip"),
                            "x": map_mouseover.get("x"), "y": map_mouseover.get("y"),
                            "semantic_type": "UNKNOWN"},
        "frame_id": str(frame_id),
        "timestamp_monotonic": float(observed_at),
        "source": "ADDON_WORLD_MAP_TELEMETRY",
        "layout_calibration": "RUNTIME_GEOMETRY_OR_ADDON_MAP_NORMALIZED",
        "fact": False,
    }
