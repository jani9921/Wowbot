"""Quest objective area on the minimap (user 2026-10-03).

Retail draws the active quest's objective area on the minimap as a light-blue
outline (the API exposes only the POI centre point).  This detector finds the
outline inside the minimap disc and, when it is closed, its interior.  Output
is in minimap-local units (offsets / disc radius, +x right, +y down); the
quest-area memory converts it to WORLD_YARDS with the addon's view radius and
the player position.  Offline (2026-10-03, 181 Exile's Reach frames): north-up,
~3.6 yd per pixel at a 44.7 px disc radius (~160 yd view radius), outline
direction within ~4 degrees of the API POI bearing.
"""
from __future__ import annotations

from collections import deque

import numpy as np

# Light-blue outline colour measured on live captures (RGB ~73/115/146).
MIN_BLUE = 110
BLUE_OVER_RED = 30
GREEN_OVER_RED = 15
DISC_FRACTION = .93          # ignore the rim art / outside-the-disc sky
SAMPLE_STRIDE = 2


def quest_area_mask(rgb: np.ndarray, center: tuple[float, float], radius: float) -> np.ndarray:
    """Boolean mask of the blue quest-area outline inside the minimap disc."""
    height, width = rgb.shape[:2]
    red, green, blue = (rgb[..., index].astype(np.int16) for index in range(3))
    yy, xx = np.mgrid[0:height, 0:width]
    inside = (xx-center[0])**2 + (yy-center[1])**2 <= (radius*DISC_FRACTION)**2
    return ((blue > MIN_BLUE) & (blue > red+BLUE_OVER_RED)
            & (green > red+GREEN_OVER_RED) & inside)


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """Pixels enclosed by the outline (not reachable from the image border)."""
    height, width = mask.shape
    outside = np.zeros_like(mask)
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        for y in (0, height-1):
            if not mask[y, x] and not outside[y, x]:
                outside[y, x] = True
                queue.append((y, x))
    for y in range(height):
        for x in (0, width-1):
            if not mask[y, x] and not outside[y, x]:
                outside[y, x] = True
                queue.append((y, x))
    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
            if 0 <= ny < height and 0 <= nx < width and not mask[ny, nx] and not outside[ny, nx]:
                outside[ny, nx] = True
                queue.append((ny, nx))
    return ~outside


def detect_quest_area(rgb: np.ndarray, center: tuple[float, float], radius: float) -> dict | None:
    """Return the minimap quest area in disc-normalised offsets, or None."""
    if radius <= 4:
        return None
    mask = quest_area_mask(rgb, center, radius)
    disc_area = np.pi * (radius*DISC_FRACTION)**2
    if mask.sum() < max(12, disc_area*.004):
        return None
    filled = _fill_holes(mask)
    interior = filled & ~mask
    closed = bool(interior.sum() >= 6)
    area = filled if closed else mask
    ys, xs = np.nonzero(area)
    keep = (ys % SAMPLE_STRIDE == 0) & (xs % SAMPLE_STRIDE == 0)
    ys, xs = ys[keep], xs[keep]
    offsets = [[round(float((x-center[0])/radius), 4), round(float((y-center[1])/radius), 4)]
               for x, y in zip(xs, ys)]
    cy, cx = int(round(center[1])), int(round(center[0]))
    player_inside = bool(closed and 0 <= cy < filled.shape[0] and 0 <= cx < filled.shape[1]
                         and filled[cy, cx])
    return {"closed": closed, "offsets": offsets, "player_inside": player_inside,
            "outline_pixels": int(mask.sum()), "area_pixels": int(area.sum())}


def offsets_to_world(offsets, *, player_x: float, player_y: float, view_radius_yards: float,
                     rotate: bool = False, facing: float | None = None) -> list[tuple[float, float]]:
    """Minimap offsets -> WORLD_YARDS (x = north, y = west; facing 0 = +x).

    North-up minimap: screen up is north (+x) and screen left is west (+y).
    A rotating minimap puts the player's facing up instead.
    """
    import math
    heading = float(facing) if rotate and facing is not None else 0.
    forward = (math.cos(heading), math.sin(heading))
    right = (math.sin(heading), -math.cos(heading))
    result = []
    for dx, dy in offsets:
        up, across = -float(dy)*view_radius_yards, float(dx)*view_radius_yards
        result.append((player_x + up*forward[0] + across*right[0],
                       player_y + up*forward[1] + across*right[1]))
    return result
