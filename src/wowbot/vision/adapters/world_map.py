from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Optional

from wowbot.vision.models import (
    DetectedFeature,
    FeatureType,
    MapPoint,
    MarkerObservation,
    WorldMapObservation,
)


def detect_world_map(buffer: bytes, width: int, height: int, *, zone: Optional[str] = None, observed_at: float = 0.0) -> WorldMapObservation:
    """Detect stable World Map facts without making navigation decisions."""
    # Retail-like full map frame used by the original detector.
    left, right = int(width * 0.055), int(width * 0.945)
    top, bottom = int(height * 0.115), int(height * 0.965)
    pixels = _rgba(buffer, width, height)
    roi = pixels[top + 8:bottom - 8, left + 8:right - 8]
    blue, green, red = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    spread = _max3(red, green, blue) - _min3(red, green, blue)
    white_mask = (red > 175) & (green > 175) & (blue > 165) & (spread < 65)
    gold_mask = (
        (red > 175) & (green > 105) & (green < 225) & (blue < 85)
        & (red.astype(float) > blue * 2.5)
    )
    # Retail paints objective search areas as translucent blue regions.  This
    # is appearance evidence only: water, a UI tint or another map overlay can
    # be blue as well, so this detector must not emit QUEST semantics.
    blue_area_mask = (
        (blue > 85)
        & (blue.astype(float) > red.astype(float) * 1.18)
        & (blue.astype(float) > green.astype(float) * 1.08)
        & ((blue.astype(int) - red.astype(int)) > 22)
    )

    white = _mask_points(white_mask, left + 8, top + 8)
    gold = _mask_points(gold_mask, left + 8, top + 8)

    player = _pick_player(_components(white))
    markers = []
    if player is not None:
        markers.extend(_quest_markers(gold, player))
    else:
        markers.extend(_quest_markers(gold, None))
    markers.extend(_blue_area_markers(
        _mask_points(blue_area_mask, left + 8, top + 8), width, height))

    return WorldMapObservation(
        width=width,
        height=height,
        player_marker=player,
        markers=tuple(markers),
        features=(),
        zone=zone,
        observed_at=observed_at,
    )


def enrich_with_addon_facts(observation: WorldMapObservation, facts: Mapping[str, object]) -> WorldMapObservation:
    """Attach exact client facts where available without changing ownership."""
    zone = facts.get("zone")
    return WorldMapObservation(
        width=observation.width,
        height=observation.height,
        player_marker=observation.player_marker,
        markers=observation.markers,
        features=observation.features,
        zone=str(zone) if zone is not None else observation.zone,
        observed_at=observation.observed_at,
    )


def _pick_player(components: list[list[tuple[int, int]]]) -> Optional[MapPoint]:
    candidates: list[tuple[int, MapPoint]] = []
    for component in components:
        xs, ys = zip(*component)
        box_w, box_h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if 2 <= box_w <= 20 and 3 <= box_h <= 28 and 3 <= len(component) <= 150:
            candidates.append((len(component), MapPoint(round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))))
    return max(candidates, default=None, key=lambda item: item[0])[1] if candidates else None


def _quest_markers(points: set[tuple[int, int]], player: Optional[MapPoint]) -> list[MarkerObservation]:
    result: list[MarkerObservation] = []
    for component in _components(points):
        xs, ys = zip(*component)
        box_w, box_h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        center = MapPoint(round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))
        if not (2 <= box_w <= 14 and 2 <= box_h <= 22 and 3 <= len(component) <= 120):
            continue
        # Discard only the tiny gold antialiasing speck next to the white
        # player arrow. A full quest-like glyph may legitimately overlap the
        # player at arrival and must remain observable.
        if (player is not None and len(component) < 6
                and math.hypot(center.x - player.x, center.y - player.y) <= 2):
            continue
        confidence = min(0.99, 0.55 + len(component) / 300.0)
        result.append(MarkerObservation(
            "unknown_world_map_marker", center, confidence,
            candidate_labels=("gold_glyph_like",),
            evidence=("appearance_only", "gold_glyph_like"),
            bbox=(min(xs), min(ys), max(xs) + 1, max(ys) + 1)))
    return result


def _blue_area_markers(points: set[tuple[int, int]], width: int,
                       height: int) -> list[MarkerObservation]:
    """Return bounded UNKNOWN blue-area observations, never quest facts."""
    result: list[MarkerObservation] = []
    frame_area = max(1, width * height)
    for component in _components(points):
        if len(component) < max(40, int(frame_area * .00035)):
            continue
        xs, ys = zip(*component)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        box_w, box_h = x1 - x0 + 1, y1 - y0 + 1
        # Reject one-pixel map rivers/lines and near-full-frame UI washes.
        if box_w < 8 or box_h < 8 or box_w * box_h > frame_area * .35:
            continue
        fill = len(component) / max(1, box_w * box_h)
        if fill < .10:
            continue
        center = MapPoint(round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))
        confidence = min(.92, .48 + min(.30, len(component) / frame_area * 8.)
                         + min(.12, fill * .12))
        result.append(MarkerObservation(
            "unknown_world_map_area", center, confidence,
            candidate_labels=("blue_region_like",),
            evidence=("appearance_only", "blue_region_like", "area_geometry"),
            bbox=(x0, y0, x1 + 1, y1 + 1)))
    return sorted(result, key=lambda marker: marker.confidence, reverse=True)[:4]


def _rgba(buffer: bytes, width: int, height: int):
    import numpy as np
    return np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)


def _max3(a, b, c):
    import numpy as np
    return np.maximum(np.maximum(a, b), c)


def _min3(a, b, c):
    import numpy as np
    return np.minimum(np.minimum(a, b), c)


def _mask_points(mask, x_offset: int = 0, y_offset: int = 0) -> set[tuple[int, int]]:
    import numpy as np
    ys, xs = np.nonzero(mask)
    return set(zip((xs + x_offset).tolist(), (ys + y_offset).tolist()))


def _components(points: set[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    remaining = set(points)
    components: list[list[tuple[int, int]]] = []
    while remaining:
        start = remaining.pop()
        component = [start]
        stack = [start]
        while stack:
            x, y = stack.pop()
            for neighbor in (
                (x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1),
                (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1),
            ):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.append(neighbor)
                    stack.append(neighbor)
        components.append(component)
    return components
