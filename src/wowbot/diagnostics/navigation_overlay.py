"""Route view for LIVE VISION (design doc §11; user 2026-10-05: "berajzolni a
waypointokat meg összekötni őket, hogy az agent így fog közlekedni").

Exact, no camera model: a heading-up top-down inset (bottom right) with the
active mmap route, its next waypoint, the quest-zone sweep hops and the
destination, coloured by height against the player's tracked layer (blue =
lower, orange = higher, green = same floor), plus a bearing line at the
bottom of the image ("WP 12 yd, 35° jobbra, ↓8 yd").  The packet comes from
``NavigationService.overlay_snapshot``; drawing never feeds back into
control.  A ground-projected line needs a camera estimate (§11b, later).
"""
from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

INSET_SIZE = 220
INSET_RADIUS_YARDS = 60.
SAME_FLOOR_YARDS = 4.


def _xyz(value) -> tuple[float, float, float | None] | None:
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError):
        return None
    z = value[2] if len(value) > 2 and isinstance(value[2], (int, float)) else None
    return x, y, z


def _frame(player: dict) -> tuple[float, float, float] | None:
    try:
        return float(player["x"]), float(player["y"]), float(player.get("facing") or 0.)
    except (KeyError, TypeError, ValueError):
        return None


def to_heading_up(player: dict, point) -> tuple[float, float] | None:
    """(right, forward) yards of a world point, facing = up.

    Retail world X is north, Y is west; facing 0 looks north and grows
    counter-clockwise, so forward = (cos f, sin f) and right = (sin f, -cos f).
    """
    origin, target = _frame(player), _xyz(point)
    if origin is None or target is None:
        return None
    dx, dy = target[0]-origin[0], target[1]-origin[1]
    facing = origin[2]
    return (dx*math.sin(facing) - dy*math.cos(facing),
            dx*math.cos(facing) + dy*math.sin(facing))


def _colour(z, player_z) -> tuple[int, int, int]:
    if z is None or player_z is None:
        return (200, 200, 200)
    if z < player_z - SAME_FLOOR_YARDS:
        return (255, 150, 40)        # BGR: blue, lower
    if z > player_z + SAME_FLOOR_YARDS:
        return (40, 150, 255)        # orange, higher
    return (60, 220, 60)             # same floor


def bearing_text(navigation: dict[str, Any]) -> str | None:
    player = navigation.get("player") or {}
    route = navigation.get("route") or []
    index = int(navigation.get("next_index") or 0)
    if not route or not 0 <= index < len(route):
        return None
    offset = to_heading_up(player, route[index])
    if offset is None:
        return None
    right, forward = offset
    distance = math.hypot(right, forward)
    angle = math.degrees(math.atan2(right, forward))
    side = "egyenesen" if abs(angle) < 8 else f"{abs(angle):.0f}° {'jobbra' if angle > 0 else 'balra'}"
    text = f"WP {distance:.0f} yd, {side}"
    point, player_z = _xyz(route[index]), player.get("z")
    if point is not None and point[2] is not None and isinstance(player_z, (int, float)):
        dz = point[2]-float(player_z)
        if abs(dz) >= 2:
            text += f", {'↓' if dz < 0 else '↑'}{abs(dz):.0f} yd"
    purpose = navigation.get("purpose")
    return f"{text}  [{purpose}]" if purpose else text


def draw_navigation(canvas: np.ndarray, navigation: dict[str, Any] | None) -> None:
    """Draw the inset and the bearing line onto ``canvas`` in place."""
    if not navigation:
        return
    player = navigation.get("player") or {}
    if _frame(player) is None:
        return
    height, width = canvas.shape[:2]
    size = min(INSET_SIZE, width // 3, height // 3)
    if size < 80:
        return
    left, top = width - size - 10, height - size - 70
    inset = canvas[top:top+size, left:left+size]
    inset[:] = (inset * .35).astype(inset.dtype)
    centre = size // 2
    scale = (size/2 - 8) / INSET_RADIUS_YARDS
    player_z = player.get("z") if isinstance(player.get("z"), (int, float)) else None

    def pixel(point) -> tuple[int, int] | None:
        offset = to_heading_up(player, point)
        if offset is None:
            return None
        right, forward = offset
        x, y = centre + right*scale, centre - forward*scale
        reach = size - 3
        return (int(max(2, min(reach, x))), int(max(2, min(reach, y))))

    sweep = navigation.get("sweep") or {}
    visited = {int(index) for index in sweep.get("visited") or ()}
    for index, hop in enumerate(sweep.get("hops") or ()):
        at = pixel(hop)
        if at is not None:
            point = _xyz(hop)
            colour = (110, 110, 110) if index in visited else _colour(point[2] if point else None, player_z)
            cv2.circle(inset, at, 2, colour, -1, cv2.LINE_AA)
    route = navigation.get("route") or []
    previous = (centre, centre)
    next_index = int(navigation.get("next_index") or 0)
    for index, anchor in enumerate(route):
        at = pixel(anchor)
        if at is None:
            continue
        point = _xyz(anchor)
        colour = _colour(point[2] if point else None, player_z)
        if index >= next_index:
            cv2.line(inset, previous, at, colour, 2, cv2.LINE_AA)
            previous = at
        cv2.circle(inset, at, 3, colour, -1, cv2.LINE_AA)
        if index == next_index:
            cv2.circle(inset, at, 7, (255, 255, 255), 1, cv2.LINE_AA)
    destination = navigation.get("destination")
    if destination:
        at = pixel(destination)
        if at is not None:
            cv2.drawMarker(inset, at, (0, 0, 255), cv2.MARKER_CROSS, 12, 2, cv2.LINE_AA)
    arrow = np.array([[centre, centre-9], [centre-6, centre+6], [centre+6, centre+6]], np.int32)
    cv2.fillPoly(inset, [arrow], (255, 220, 0), cv2.LINE_AA)
    cv2.rectangle(inset, (0, 0), (size-1, size-1), (230, 230, 230), 1)
    label = f"{INSET_RADIUS_YARDS:.0f} yd"
    if player_z is not None:
        label += f"  z {player_z:.0f}"
    cv2.putText(inset, label, (5, 14), cv2.FONT_HERSHEY_SIMPLEX, .4, (240, 240, 240), 1, cv2.LINE_AA)
    text = bearing_text(navigation)
    if text:
        # cv2 has no arrow glyphs in its Hershey fonts.
        text = text.replace("↓", "le ").replace("↑", "fel ").replace("°", " fok")
        (text_width, text_height), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, .6, 1)
        x, y = max(5, (width-text_width)//2), height - 52
        cv2.rectangle(canvas, (x-6, y-text_height-6), (x+text_width+6, y+6), (15, 15, 15), -1)
        cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, .6, (90, 255, 255), 1, cv2.LINE_AA)
