"""Read-only fast view of the canonical world plus freshest sensor fields.

This is a control projection, not a second WorldModel. It neither learns
identity, reassigns track IDs nor re-stamps old boxes as fresh observations.
"""
from __future__ import annotations

from .models import number
from .world_addon_reducer import WorldAddonReducer


def control_view(base, payload, vision, now):
    state = dict(base)
    for key in WorldAddonReducer.FAST_KEYS:
        if key in payload:
            state[key] = payload[key]
    state["monotonic_time"] = now
    if "soft_targets" not in payload:
        state.update(soft_targets=[], soft_targets_sample_time=None)
    if "quest_item_target" not in payload:
        state["quest_item_target"] = None
    # UI detail pages can lag the FAST edge. A fresh explicit false closes
    # stale modal detail too; never invent true/false when FAST omitted it.
    for flag, key in (("quest_ui_open", "quest_ui"), ("gossip_open", "gossip_ui")):
        if flag in payload:
            state[key] = {**(state.get(key) or {}), "open": bool(payload[flag])}
    if "quest_ui_npc_guid" in payload:
        state["quest_ui"] = {**(state.get("quest_ui") or {}), "npc_guid": payload["quest_ui_npc_guid"]}
    if vision is not None:
        previous = {str(item.get("track_id")): item for item in base.get("visual_candidates") or ()}
        items = []
        for raw in vision.get("items") or ():
            item = dict(raw)
            old = previous.get(str(item.get("track_id"))) or {}
            # Enrich only the SAME observed ID, not a similar-looking neighbour.
            for key in ("visual_identity", "self_player_avatar", "screen_velocity"):
                if key not in item and key in old:
                    item[key] = old[key]
            items.append(item)
        state["visual_candidates"] = items
        if "camera_state" in vision:
            state["camera_state"] = dict(vision["camera_state"] or {})
    old_target, target = base.get("target") or {}, state.get("target") or {}
    if target.get("guid") and target.get("guid") == old_target.get("guid"):
        target = {**old_target, **target}
        anchor = old_target.get("screen_position") or {}
        track = target.get("visual_track_id") or anchor.get("track_id")
        box = next((item for item in state.get("visual_candidates") or ()
                    if item.get("track_id") == track and item.get("source") == "WORLD3D"), None)
        if box is not None:
            target["screen_position"] = {**anchor, "x": box.get("x"), "y": box.get("y"),
                                         "bbox": box.get("bbox"), "sample_time": box.get("observed_at")}
        state["target"] = target
    # Stamp each present unit with the packet's REAL sampling time, not the
    # control clock. A delayed packet is not a post-hover confirmation.
    for key, time_key in WorldAddonReducer.SAMPLE_TIME_KEYS:
        if key in payload:
            state[time_key] = payload.get(time_key, WorldAddonReducer.packet_sample_time(payload))
        elif time_key in base and key != "soft_targets":
            state[time_key] = base[time_key]
    return state


def control_safety(base, payload, received_at, now, *, flight_control=False):
    """A fresh receive is necessary, but not sufficient, for input authority."""
    if received_at is None or not 0 <= now-received_at <= .5:
        return "telemetry_gap"
    if payload.get("session_id") != base.get("session_id"):
        return "session_changed"
    for key in ("map_id", "character_guid"):
        if payload.get(key) is not None and base.get(key) is not None and payload[key] != base[key]:
            return f"{key}_changed"
    sampled = number(payload.get("monotonic_time"))
    if sampled is None or not 0 <= now-sampled <= .75:
        return "stale_addon_sample"
    current = {**base, **payload}
    if current.get("loading") or current.get("input_blocked") or current.get("player_present") is False:
        return "client_blocked"
    # Live 2026-11-01 (Westfall corpse runs): the ghost *state* stopped W on
    # every 30 Hz sample, so the ghost ran stop-go at 3.5 of its 9.1 yd/s
    # (253 s for 900 yd).  Only the release/resurrect edge is a transition;
    # a corpse run started as a ghost keeps its lease (as fast_movement_lane).
    ghost_edge = (payload.get("is_ghost") is not None
                  and bool(payload["is_ghost"]) != (base.get("is_ghost") is True))
    if current.get("is_dead") or ghost_edge:
        return "death_transition"
    if (current.get("movement") or {}).get("falling") and not flight_control:
        return "fall_transition"
    if (current.get("world_map_open") or current.get("quest_ui_open") or current.get("gossip_open")
            or any((current.get(key) or {}).get("open") for key in ("vendor_ui", "taxi_ui"))
            or any((current.get(key) or {}).get("open") and payload.get(flag) is not False
                   for key, flag in (("quest_ui", "quest_ui_open"), ("gossip_ui", "gossip_open")))):
        return "modal_ui"
    return None
