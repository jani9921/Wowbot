"""Quest objective NPC dots on the minimap (user 2026-10-04).

Retail draws the tracked quest's objective NPCs as small yellow dots on the
minimap.  No Lua API exposes their position (nor any NPC position), so this
detector finds them in the minimap disc.  Output is in minimap-local units
(offsets / disc radius, +x right, +y down), like ``minimap_quest_area``; the
planner converts them to WORLD_YARDS with the addon's view radius and the
player position (``offsets_to_world``).

Measured live 2026-10-04 00:28 (Enhanced Combat Tactics, Captain Garrick):
a 4-6 px dot of RGB ~(207-254, 170-223, 64-106) at a 44.7 px disc radius.
"""
from __future__ import annotations

import numpy as np

MIN_RED = 190
MIN_GREEN = 150
MAX_BLUE = 120
RED_OVER_BLUE = 90
GREEN_OVER_BLUE = 60
MAX_RED_OVER_GREEN = 60      # yellow, not the orange autumn foliage
DISC_FRACTION = .9           # the gold rim art is outside this
PLAYER_EXCLUSION = .05       # the player arrow sits at the centre
MIN_PIXELS, MAX_PIXELS = 2, 40
# MAX_PIXELS was measured at a 44.7 px disc radius (843x475 client); a bigger
# minimap (Edit Mode size, higher resolution; user 2026-10-05) draws bigger
# dots, so the upper limit grows with the disc area.  The lower limit and the
# 4 px "!"/"?" glyph height stay: at a 76 px radius the "?" is ~5-6 px tall.
REFERENCE_RADIUS_PX = 44.7


def quest_dot_mask(rgb: np.ndarray, center: tuple[float, float], radius: float) -> np.ndarray:
    height, width = rgb.shape[:2]
    red, green, blue = (rgb[..., index].astype(np.int16) for index in range(3))
    yy, xx = np.mgrid[0:height, 0:width]
    distance2 = (xx-center[0])**2 + (yy-center[1])**2
    inside = ((distance2 <= (radius*DISC_FRACTION)**2)
              & (distance2 > (radius*PLAYER_EXCLUSION)**2))
    return ((red >= MIN_RED) & (green >= MIN_GREEN) & (blue <= MAX_BLUE)
            & (red-blue >= RED_OVER_BLUE) & (green-blue >= GREEN_OVER_BLUE)
            & (red-green <= MAX_RED_OVER_GREEN) & inside)


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    seen = np.zeros_like(mask)
    result = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        stack, pixels = [(y, x)], []
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            pixels.append((cy, cx))
            for ny in (cy-1, cy, cy+1):
                for nx in (cx-1, cx, cx+1):
                    if (0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1]
                            and mask[ny, nx] and not seen[ny, nx]):
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        result.append(pixels)
    return result


def detect_quest_dots(rgb: np.ndarray, center: tuple[float, float], radius: float) -> list[dict]:
    """Yellow quest dots in disc-normalised offsets, nearest first."""
    if radius <= 4:
        return []
    from .minimap_target_marker import _bright, _pip_directions
    bright = _bright(rgb)
    dots = []
    scale = max(1., radius / REFERENCE_RADIUS_PX)
    for pixels in _components(quest_dot_mask(rgb, center, radius)):
        if not MIN_PIXELS <= len(pixels) <= MAX_PIXELS * scale * scale:
            continue
        ys = [p[0] for p in pixels]
        xs = [p[1] for p in pixels]
        height, width = max(ys)-min(ys)+1, max(xs)-min(xs)+1
        if height >= 4 and height > width:
            # The yellow "?"/"!" glyph of a quest giver/ender icon is a thin
            # tall stroke (live 2026-10-04: the turn-in "?" was walked to).
            continue
        if _pip_directions(bright, sum(ys)/len(ys), sum(xs)/len(xs), radius) >= 3:
            continue        # the selected target's crosshair marker, not a quest dot
        dx = (sum(xs)/len(xs) - center[0]) / radius
        dy = (sum(ys)/len(ys) - center[1]) / radius
        dots.append({"offset": [round(float(dx), 4), round(float(dy), 4)],
                     "distance_fraction": round(float(np.hypot(dx, dy)), 4),
                     "pixels": len(pixels)})
    return sorted(dots, key=lambda dot: dot["distance_fraction"])
