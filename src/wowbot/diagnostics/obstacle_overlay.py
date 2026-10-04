"""Read-only M4 obstacle/traversability debug-overlay projection.

This module does not draw, classify, plan or send input. It turns canonical
World3D and NavigationService snapshots into stable rows for the GUI/debugger.
"""
from __future__ import annotations

from typing import Mapping


def obstacle_overlay(world3d: Mapping | None,
                     navigation: Mapping | None = None) -> dict:
    world3d, navigation = world3d or {}, navigation or {}
    traversability = world3d.get("traversability") or {}
    sectors = []
    for raw in traversability.get("sectors") or ():
        if not isinstance(raw, Mapping):
            continue
        sectors.append({
            "sector": raw.get("sector") or raw.get("cell_id"),
            "state": raw.get("state", "UNKNOWN"),
            "ground_confidence": raw.get("ground_confidence"),
            "free_space_confidence": raw.get("free_space_confidence"),
            "obstacle_confidence": raw.get("obstacle_confidence"),
            "danger_confidence": raw.get("danger_confidence"),
            "drop_confidence": raw.get("drop_confidence"),
            "dynamic_probability": raw.get("dynamic_probability"),
            "traversability_score": raw.get("traversability_score"),
            "traversal_cost": raw.get("traversal_cost", raw.get("cost")),
            "collision_confidence": raw.get("collision_evidence_confidence"),
            "motion_mismatch_confidence": raw.get("motion_mismatch_confidence"),
            "lifecycle": raw.get("obstacle_lifecycle"),
            "evidence": list(raw.get("evidence") or ()),
        })
    ego = world3d.get("ego_motion") or {}
    active_request = navigation.get("active_request") or {}
    local_plan = navigation.get("local_plan") or navigation.get("local") or {}
    return {
        "schema": "OBSTACLE_OVERLAY_V1",
        "frame_id": world3d.get("frame_id"),
        "timestamp": world3d.get("timestamp"),
        "coordinate_space": traversability.get(
            "coordinate_space", "WORLD_VIEWPORT_NORMALIZED"),
        "sectors": sectors,
        "dynamic_obstacles": [dict(item) for item in world3d.get("obstacles") or ()
                              if isinstance(item, Mapping)
                              and (item.get("dynamic_probability") or 0) > 0],
        "expected_ego_motion": ego.get("commanded_motion", ego.get("expected_motion")),
        "observed_ego_motion": ego.get("motion_kind", ego.get("observed_motion")),
        "motion_vector": ego.get("motion_vector") or ego.get("optical_flow_summary"),
        "selected_local_waypoint": (local_plan.get("local_waypoint")
                                    or active_request.get("local_waypoint")),
        "navigation_mode": active_request.get("mode"),
    }
