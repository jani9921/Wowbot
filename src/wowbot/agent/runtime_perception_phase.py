from __future__ import annotations

from typing import Any


def update_runtime_perception(runtime: Any, payload: dict | None, current: float) -> list[dict]:
    """Update the selected client's passive visual projection.

    This phase owns neither input nor planning.  It only translates the latest
    runtime/world state into the geometry contract consumed by PerceptionWorker
    and returns its UNKNOWN-first candidates.
    """
    if not runtime.perception or not runtime.sensor.frame:
        return []

    visual_state = (
        {**runtime.agent.world.state, **payload}
        if payload is not None and payload.get("transport_kind") == "FAST"
        else payload if payload is not None else runtime.agent.world.state
    )
    pending = runtime.agent.pending
    pending_skill = pending.proposal.skill if pending else None
    request = {
        "allow": not visual_state.get("loading", False),
        "geometry": {
            **(visual_state.get("minimap_geometry") or {}),
            "quest_ui_open": bool(
                (visual_state.get("quest_ui") or {}).get("open")
                or visual_state.get("quest_ui_open")
            ),
            "gossip_open": bool(
                (visual_state.get("gossip_ui") or {}).get("open")
                or visual_state.get("gossip_open")
            ),
            "ui_scale": visual_state.get("ui_scale"),
            "camera_zoom": (visual_state.get("camera_state") or {}).get("zoom_estimate"),
            "vehicle_camera": bool(
                visual_state.get("vehicle_camera") or visual_state.get("vehicle_ui")
            ),
            # Evidence-only feedback for World3D.  Navigation remains the
            # sole movement owner.
            "movement": visual_state.get("movement") or {},
            "motion_feedback": visual_state.get("motion_feedback") or {},
            "navigation_active": pending_skill
            in {"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"},
            "client_id": visual_state.get("client_id"),
            "session_id": visual_state.get("session_id"),
            "character_name": visual_state.get("character_name"),
            "character_guid": visual_state.get("character_guid"),
            "player_orientation": visual_state.get("orientation"),
            "cursor_position": visual_state.get("cursor_position") or {},
            "fast_visual_servo": pending_skill
            in {"VISUAL_APPROACH", "SEEK_VISUAL_CUE", "COMBAT", "DEFEND"},
            "tooltip_probe": pending_skill == "INSPECT",
            # Diagnostics only (not part of the perception context key).
            "payload_kind": (payload.get("transport_kind") if payload is not None
                             else "WORLD_STATE"),
        },
        "world_map_open": visual_state.get("world_map_open", False),
        "context": (
            visual_state.get("session_id"),
            visual_state.get("character_guid"),
            visual_state.get("map_id"),
            runtime.agent.planner.map_zoom_count,
        ),
    }
    if getattr(runtime.perception, "background_active", False):
        return runtime.perception.submit_latest(**request)
    return runtime.perception.update(runtime.sensor.frame, current, **request)
