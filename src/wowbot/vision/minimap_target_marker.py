"""Selected-target marker on the minimap (user 2026-10-04).

While a unit is targeted, Retail draws it on the minimap as a small dot in
its reaction colour (red hostile, yellow neutral, green friendly) inside four
light gold "crosshair" pips (north, south, east, west).  The marker exists only
for the current target, so it gives that unit's bearing and distance even when
it is off screen (e.g. a caster shooting from range).

Measured on three user screenshots (1600x900, minimap disc radius ~75 px): a
~3x3 px core -- green #3cac1f, yellow #dfb125, red #7f1804..#9c0b05 -- and
cream pips (~#f0e9cb) 3-4 px from the core centre.  Output is in minimap-local
units (offsets / disc radius), like ``minimap_quest_dot``.
"""
from __future__ import annotations

import numpy as np

DISC_FRACTION = .92
PIP_MIN, PIP_MAX = .03, .085        # pip distance from the core, in disc radii


def core_masks(rgb: np.ndarray) -> dict[str, np.ndarray]:
    red, green, blue = (rgb[..., index].astype(np.int16) for index in range(3))
    return {
        "GREEN": (green >= 120) & (green-red >= 55) & (green-blue >= 55),
        "YELLOW": (red >= 190) & (green >= 140) & (blue <= 90) & (red-blue >= 120) & (red-green <= 60),
        "RED": (red >= 100) & (red-green >= 75) & (red-blue >= 75) & (green <= 70),
    }


def _bright(rgb: np.ndarray) -> np.ndarray:
    red, green, blue = (rgb[..., index].astype(np.int16) for index in range(3))
    return (red >= 190) & (green >= 180) & (blue >= 120) & (red-blue <= 90)


def _components(mask: np.ndarray, limit: int = 30) -> list[list[tuple[int, int]]]:
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
        if len(pixels) <= limit:
            result.append(pixels)
    return result


def _pip_directions(bright: np.ndarray, cy: float, cx: float, radius: float) -> int:
    """How many of N/S/E/W have a bright pip at crosshair distance."""
    near, far = max(2, int(round(radius*PIP_MIN))), max(3, int(round(radius*PIP_MAX)))
    height, width = bright.shape
    found = 0
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        hit = False
        for step in range(near, far+1):
            for side in (-1, 0, 1):
                y = int(round(cy + dy*step + dx*side))
                x = int(round(cx + dx*step + dy*side))
                if 0 <= y < height and 0 <= x < width and bright[y, x]:
                    hit = True
                    break
            if hit:
                break
        found += hit
    return found


def detect_target_markers(rgb: np.ndarray, center: tuple[float, float], radius: float) -> list[dict]:
    """Reaction-coloured crosshair markers, best first."""
    if radius <= 8:
        return []
    height, width = rgb.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width]
    inside = (xx-center[0])**2 + (yy-center[1])**2 <= (radius*DISC_FRACTION)**2
    bright = _bright(rgb)
    markers = []
    for colour, mask in core_masks(rgb).items():
        for pixels in _components(mask & inside):
            if len(pixels) < 2:
                continue
            cy = sum(p[0] for p in pixels)/len(pixels)
            cx = sum(p[1] for p in pixels)/len(pixels)
            pips = _pip_directions(bright, cy, cx, radius)
            if pips < 3:
                continue
            dx, dy = (cx-center[0])/radius, (cy-center[1])/radius
            markers.append({"colour": colour, "offset": [round(float(dx), 4), round(float(dy), 4)],
                            "distance_fraction": round(float(np.hypot(dx, dy)), 4),
                            "pixels": len(pixels), "pips": pips})
    return sorted(markers, key=lambda marker: (-marker["pips"], -marker["pixels"]))
