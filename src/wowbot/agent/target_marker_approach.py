"""Walk to a selected unit by its minimap target marker (user 2026-10-11).

The selected unit is drawn on the minimap (a reaction-coloured dot in a gold
crosshair); ``WorldStateProjector`` turns it into ``target.world_position``
with ``source=MINIMAP_TARGET_MARKER``.  When the unit is not on screen, that
estimate is the only bearing and distance: walk there over the navmesh, the
local skills (visual approach, COMBAT/Charge, INTERACT) take over once it is
in view.  The GUID stays the addon's; the marker is never identity.
"""
from __future__ import annotations

import math

from .models import Proposal, number


def minimap_target_move(state: dict, target: dict, *, min_distance: float,
                        stop_distance: float, priority: float, reason: str) -> Proposal | None:
    where = target.get("world_position") if isinstance(target.get("world_position"), dict) else {}
    player = state.get("player_world_position") or {}
    px, py = number(player.get("x")), number(player.get("y"))
    tx, ty = number(where.get("x")), number(where.get("y"))
    if (where.get("source") != "MINIMAP_TARGET_MARKER" or not target.get("guid")
            or None in (px, py, tx, ty) or target.get("screen_position")
            or (where.get("instance_id") not in (None, player.get("instance_id")))):
        return None
    if math.hypot(tx-px, ty-py) <= min_distance:
        return None
    return Proposal.make(
        "MOVE", reason,
        {"x": tx, "y": ty, "coordinate_space": "WORLD_YARDS",
         "instance_id": player.get("instance_id"), "world_map_id": player.get("instance_id"),
         "map_id": state.get("map_id"), "z_known": False, "floor_hint": "SAME",
         "target_guid": target["guid"], "guid": target["guid"],
         "purpose": "APPROACH_SELECTED_TARGET", "location_source": "MINIMAP_TARGET_MARKER",
         "stop_distance": stop_distance, "require_navmesh": True},
        confidence=.7, priority=priority)
