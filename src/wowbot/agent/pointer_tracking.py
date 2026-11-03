"""Pointer-only following helpers; the active skill and dispatcher keep ownership.

A box permits aiming, not recognition or clicking. Never follow a coasting,
stale or self-player box, and never move a world pointer over an open UI.
"""
from __future__ import annotations

import math

from .models import Command, number
from .self_avatar import is_self_avatar_box
from .server_mode import server_profile
from .track_motion import candidate_for_track, predicted_point

POINTER_INTERVAL = 1 / 30
POINTER_EPSILON = .003
LIVE_STATES = frozenset({"ACTIVE", "STABLE", "TENTATIVE", "REACQUIRE_CANDIDATE"})


def world_pointer_blocked(state: dict) -> bool:
    return bool(
        state.get("player_present") is False or state.get("loading")
        or state.get("input_blocked") or state.get("is_dead") or state.get("is_ghost")
        or state.get("world_map_open") or state.get("quest_ui_open") or state.get("gossip_open")
        or any((state.get(key) or {}).get("open") for key in (
            "quest_ui", "gossip_ui", "vendor_ui", "taxi_ui", "loot_ui")))


def live_pointer_point(state: dict, track_id, now: float, *, candidate=None):
    """Fresh point for one explicit track, never a replacement-track guess."""
    if server_profile(state):
        return None                          # REV4: no screen-box pointer aim in SERVER
    item = candidate if candidate is not None else candidate_for_track(state, track_id)
    if not item or world_pointer_blocked(state):
        return None
    at = number(item.get("observed_at"))
    if (item.get("source") != "WORLD3D" or str(item.get("track_id")) != str(track_id)
            or at is None or not 0 <= now-at <= .45 or item.get("coasting")
            or str(item.get("lifecycle") or item.get("track_state") or "ACTIVE").upper() not in LIVE_STATES
            or is_self_avatar_box(item)
            or (item.get("visual_identity") or {}).get("kind") == "SELF_PLAYER"):
        return None
    point = predicted_point(item, state, now)
    if point is None or not all(math.isfinite(v) and .02 < v < .98 for v in point):
        return None
    return point


def follow_pointer(context: dict, state: dict, track_id, now: float, *, point=None) -> Command | None:
    """Prepare a bounded pointer update without spending a movement update."""
    if now-context.get("sent_at", -math.inf) < POINTER_INTERVAL or server_profile(state):
        return None
    point = point if point is not None else live_pointer_point(state, track_id, now)
    if point is None:
        return None
    cursor = state.get("cursor_position") or {}
    cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
    if cx is not None and cy is not None and math.hypot(cx-point[0], cy-point[1]) <= POINTER_EPSILON:
        return None
    previous = context.get("point")
    if (context.get("track_id") == track_id and previous is not None
            and math.hypot(previous[0]-point[0], previous[1]-point[1]) <= POINTER_EPSILON
            and now-context["sent_at"] < .25):
        return None                          # cursor telemetry can lag our command
    context.setdefault("started_at", now)
    context.update(sent_at=now, point=point, track_id=track_id)
    return Command("POINTER", x=point[0], y=point[1], duration=.001)
