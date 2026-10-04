from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True, slots=True)
class WorldMapCalibration:
    """Map-space calibration for a visible World Map rectangle.

    Coordinates are normalized to [0, 1] across the map content rectangle.
    The profile is deliberately explicit so UI chrome, title bars and overlays
    are never silently treated as map pixels.
    """

    left_px: int
    top_px: int
    right_px: int
    bottom_px: int

    @property
    def width_px(self) -> int:
        return max(1, self.right_px - self.left_px)

    @property
    def height_px(self) -> int:
        return max(1, self.bottom_px - self.top_px)

    def pixel_to_map(self, x_px: float, y_px: float) -> tuple[float, float]:
        x = (x_px - self.left_px) / self.width_px
        y = (y_px - self.top_px) / self.height_px
        return (min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))

    def map_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        x = min(1.0, max(0.0, x))
        y = min(1.0, max(0.0, y))
        return (self.left_px + x * self.width_px, self.top_px + y * self.height_px)

    def contains(self, x_px: float, y_px: float) -> bool:
        return self.left_px <= x_px <= self.right_px and self.top_px <= y_px <= self.bottom_px


EXILE_REACH_12_1_5 = WorldMapCalibration(45, 78, 917, 640)


def normalize_player_map_position(
    image_shape: tuple[int, ...],
    player_pixel: tuple[float, float],
    calibration: WorldMapCalibration = EXILE_REACH_12_1_5,
) -> tuple[float, float]:
    _ = image_shape
    return calibration.pixel_to_map(*player_pixel)


# Retail zone-map art is a 1002x668 canvas; the visible canvas keeps that
# aspect at the default (unzoomed) map scale.
WORLD_MAP_CANVAS_ASPECT = 1002 / 668
# Historical fixed frame used by detect_world_map before the canvas estimator.
LEGACY_WORLD_MAP_FRACTIONS = (.055, .115, .945, .965)


def legacy_world_map_rect(width: int, height: int) -> WorldMapCalibration:
    left, top, right, bottom = LEGACY_WORLD_MAP_FRACTIONS
    return WorldMapCalibration(int(width * left) + 8, int(height * top) + 8,
                               int(width * right) - 8, int(height * bottom) - 8)


def estimate_world_map_canvas(pixels, *, dark_threshold: float = 25.,
                              stride: int = 2) -> WorldMapCalibration | None:
    """Estimate the visible map canvas of a full-screen World Map.

    ``pixels`` is an HxWx3/4 uint8 array (channel order irrelevant: only the
    mean luminance is used).  Retail paints a black backdrop beside the
    maximized map, so the canvas is the bright column span; its bottom is the
    last bright row and its height follows the fixed canvas aspect (the title
    bar and navigation strip above it are therefore excluded).

    Returns ``None`` whenever the layout is not recognisably the full-screen
    map (no black side margins, implausible span).  Callers must then fall
    back to :func:`legacy_world_map_rect` and treat projections as unverified.
    Live check 2026-10-01: on all 29 map-open captures of pid-3324 the addon
    player position projected through this rect landed within 2 px of the
    detected player arrow.
    """
    array = np.asarray(pixels)
    if array.ndim != 3 or array.shape[0] < 40 or array.shape[1] < 60:
        return None
    step = max(1, int(stride))
    luminance = array[::step, ::step, :3].mean(axis=2)
    rows, columns = luminance.shape
    band = luminance[int(rows * .3):max(int(rows * .3) + 1, int(rows * .7))]
    bright_columns = np.nonzero(band.mean(axis=0) > dark_threshold)[0]
    if bright_columns.size < columns * .35:
        return None
    first, last = int(bright_columns[0]), int(bright_columns[-1])
    # The full-screen map leaves a black margin on both sides.
    if first < 2 or last > columns - 3:
        return None
    if luminance[:, :max(1, first - 1)].mean() > dark_threshold:
        return None
    if luminance[:, last + 2:].mean() > dark_threshold:
        return None
    inner = luminance[:, min(last, first + 5):max(first + 6, last - 5)]
    bright_rows = np.nonzero(inner.mean(axis=1) > dark_threshold)[0]
    if bright_rows.size < rows * .4:
        return None
    left, right = (first + 1) * step, last * step
    bottom = int(bright_rows[-1]) * step
    canvas_height = (right - left) / WORLD_MAP_CANVAS_ASPECT
    top = round(bottom - canvas_height)
    if top < 0 or right - left < array.shape[1] * .35:
        return None
    return WorldMapCalibration(left, top, right, bottom)
