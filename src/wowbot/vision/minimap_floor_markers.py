"""Minimap objective dots on another floor (user 2026-10-05, Hrun's pit).

User rule: inside the blue quest area we are in the zone; an objective drawn
as a **yellow** dot is in our space, a **grey** dot is in a space we are not
in, and a small triangle under / over a dot means the objective is
**lower / higher** than us (a yellow dot can carry one too).  When the arrow
disappears we are on the objective's floor.

Measured on the user's 1600x900 screenshot (16:40, disc radius ~75 px):
grey dot ~5x5 px of neutral 160-230 grey; one dark row; then a "▼" whose
rows are 4-5, 2-3 and 1 px wide; its centre ~8 px (0.1 R) under the dot's.
At the 843x475 client (radius ~45 px) dot and arrow are 2-3 px and the
arrow is not resolvable -- the minimap needs Edit Mode size or a bigger
window.  Output is in disc-normalised offsets like ``minimap_quest_dot``.
"""
from __future__ import annotations

import math

import numpy as np

from .minimap_quest_dot import _components, detect_quest_dots

DISC_FRACTION = .9
PLAYER_EXCLUSION = .12      # the player arrow (~12 px at R 75) sits at the centre
GREY_MIN_VALUE = 150
GREY_MAX_SPREAD = 24        # max(R,G,B) - min(R,G,B): neutral grey
ARROW_MIN_VALUE = 165
ARROW_DIM_MIN_VALUE = 140   # second pass for an unpaired dot: live JPEG arrows dim to ~150
ARROW_MAX_SPREAD = 34       # the arrow may overlap the blue zone outline's glow
ARROW_MAX_BLUE_OVER_RED = 32
PAIR_DX = .06               # arrow centre vs dot centre, in disc radii
PAIR_DY = (.04, .17)
ARROW_AS_DOT = .04          # a "grey dot" this close to a paired arrow is that arrow


def _disc(shape, center, radius, exclusion: float) -> np.ndarray:
    height, width = shape[:2]
    yy, xx = np.mgrid[0:height, 0:width]
    distance2 = (xx-center[0])**2 + (yy-center[1])**2
    return (distance2 <= (radius*DISC_FRACTION)**2) & (distance2 > (radius*exclusion)**2)


def _neutral(rgb: np.ndarray, minimum: int, spread: int, blue_over_red: int | None = None) -> np.ndarray:
    channels = rgb.astype(np.int16)
    high, low = channels.max(axis=2), channels.min(axis=2)
    mask = (low >= minimum) & (high-low <= spread)
    if blue_over_red is not None:
        mask &= channels[..., 2]-channels[..., 0] <= blue_over_red
    return mask


def _rows(pixels) -> list[int]:
    """Widths of a component's rows, top to bottom."""
    by_row: dict[int, list[int]] = {}
    for y, x in pixels:
        by_row.setdefault(y, []).append(x)
    return [max(xs)-min(xs)+1 for _, xs in sorted(by_row.items())]


def _triangle(pixels, *, tolerant: bool = False) -> str | None:
    """DOWN for a "▼" (rows narrowing downwards), UP for a "▲", else None.

    ``tolerant`` drops up to two 1 px rows beyond the triangle's base: the
    blue zone outline / JPEG bleed adds them (live 2026-10-05, the cocoon dot
    of Hrun's pit read [1, 5, 3, 1] and flickered to "same floor").
    """
    widths = _rows(pixels)
    if tolerant and widths:
        widest = max(widths)
        first, last = widths.index(widest), len(widths)-1-widths[::-1].index(widest)
        down = (widths[first:] if first <= 2 and all(width == 1 for width in widths[:first])
                else None)
        up = (widths[:last+1] if len(widths)-1-last <= 2
              and all(width == 1 for width in widths[last+1:]) else None)
        for candidate in (down, up):
            if candidate is not None and candidate != widths:
                direction = _shape(candidate)
                if direction:
                    return direction
    return _shape(widths)


def _shape(widths: list[int]) -> str | None:
    if not 2 <= len(widths) <= 5 or max(widths) < 3 or max(widths) > 9:
        return None
    if widths[0] == max(widths) and widths[-1] < widths[0] and all(
            a >= b for a, b in zip(widths, widths[1:])):
        return "DOWN"
    if widths[-1] == max(widths) and widths[0] < widths[-1] and all(
            a <= b for a, b in zip(widths, widths[1:])):
        return "UP"
    return None


def _centre(pixels) -> tuple[float, float]:
    return (sum(p[1] for p in pixels)/len(pixels), sum(p[0] for p in pixels)/len(pixels))


def detect_floor_markers(rgb: np.ndarray, center: tuple[float, float], radius: float) -> list[dict]:
    """Yellow and grey objective dots with their floor: SAME, BELOW or ABOVE."""
    if radius <= 4:
        return []
    disc = _disc(rgb.shape, center, radius, PLAYER_EXCLUSION)
    size = radius/75.             # the grey dot measured 19-21 px, 5x5, at R 75
    # Yellow dots come from the existing detector: it already drops the "!"/"?"
    # glyphs and the selected target's crosshair marker.
    dots = [{"colour": "YELLOW", "pixels": dot["pixels"],
             "centre": (center[0]+dot["offset"][0]*radius, center[1]+dot["offset"][1]*radius)}
            for dot in detect_quest_dots(rgb, center, radius)]
    for pixels in _components(_neutral(rgb, GREY_MIN_VALUE, GREY_MAX_SPREAD) & disc):
        widths = _rows(pixels)
        height, width = len(widths), max(widths)
        if (not max(4, 8*size*size) <= len(pixels) <= 40*size*size
                or height > 2*width+1 or width > 2*height+1
                or max(height, width) > max(4, 8*size)):
            continue
        if _triangle(pixels):
            continue                          # an arrow, not a dot
        dots.append({"colour": "GREY", "centre": _centre(pixels), "pixels": len(pixels)})
    def arrows_at(minimum: int) -> list:
        found = []
        for pixels in _components(_neutral(rgb, minimum, ARROW_MAX_SPREAD,
                                           ARROW_MAX_BLUE_OVER_RED) & disc):
            direction = _triangle(pixels, tolerant=True)
            if direction:
                found.append((direction, _centre(pixels)))
        return found

    def pair(dot, arrows) -> tuple[str, tuple | None]:
        dx_px, dy_px = dot["centre"]
        floor, used = "SAME", None
        for direction, (ax, ay) in arrows:
            if abs(ax-dx_px) > PAIR_DX*radius:
                continue
            below = (ay-dy_px)/radius
            if direction == "DOWN" and PAIR_DY[0] <= below <= PAIR_DY[1]:
                floor, used = "BELOW", (ax, ay)
            elif direction == "UP" and PAIR_DY[0] <= -below <= PAIR_DY[1]:
                floor, used = "ABOVE", (ax, ay)
        return floor, used

    strict, dim = arrows_at(ARROW_MIN_VALUE), None
    for dot in dots:
        dot["floor"], dot["arrow"] = pair(dot, strict)
        if dot["floor"] == "SAME":
            dim = arrows_at(ARROW_DIM_MIN_VALUE) if dim is None else dim
            dot["floor"], dot["arrow"] = pair(dot, dim)
    # A bright arrow can also pass the grey-dot mask: it is not a dot.
    paired = [dot["arrow"] for dot in dots if dot["arrow"] is not None]
    dots = [dot for dot in dots if not (dot["colour"] == "GREY" and any(
        math.hypot(dot["centre"][0]-ax, dot["centre"][1]-ay) <= ARROW_AS_DOT*radius
        for ax, ay in paired))]
    result = []
    for dot in dots:
        dx_px, dy_px = dot["centre"]
        floor = dot["floor"]
        if dot["colour"] == "GREY" and floor == "SAME":
            floor = "OTHER_SPACE"            # grey without an arrow: inside a space we are not in
        result.append({"offset": [round(float((dx_px-center[0])/radius), 4),
                                  round(float((dy_px-center[1])/radius), 4)],
                       "colour": dot["colour"], "floor": floor, "pixels": dot["pixels"]})
    return sorted(result, key=lambda item: item["offset"][0]**2 + item["offset"][1]**2)


FLOOR_LABELS = {
    "BELOW": ("quest_objective_dot_like", "other_space_like", "objective_below_like"),
    "ABOVE": ("quest_objective_dot_like", "other_space_like", "objective_above_like"),
    "OTHER_SPACE": ("quest_objective_dot_like", "other_space_like"),
    "SAME": ("quest_objective_dot_like", "same_space_like"),
}
