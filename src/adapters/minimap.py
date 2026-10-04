from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .numpy_runtime import np

from .pixel_bridge import capture_window_bgra
from .world_map import MapPoint, _components, _mask_points
from src.adapters.windows_input import focus_window_for_pid


@dataclass(frozen=True)
class MinimapQuestObservation:
    center: MapPoint
    quest: Optional[MapPoint]
    target: Optional[MapPoint] = None

    @property
    def vector(self) -> Optional[tuple[float, float]]:
        if self.quest is None:
            return None
        return float(self.quest.x - self.center.x), float(self.quest.y - self.center.y)

    @property
    def distance_pixels(self) -> Optional[float]:
        return math.hypot(*self.vector) if self.vector is not None else None

    @property
    def target_vector(self) -> Optional[tuple[float, float]]:
        if self.target is None:
            return None
        return float(self.target.x - self.center.x), float(self.target.y - self.center.y)

    @property
    def target_distance_pixels(self) -> Optional[float]:
        vector = self.target_vector
        return math.hypot(*vector) if vector is not None else None


def observe_minimap_quest(pid: int, turn_in: bool = False) -> MinimapQuestObservation:
    if not focus_window_for_pid(pid):
        raise RuntimeError(f"could not focus pid {pid}")
    raw, width, height = capture_window_bgra(pid)
    return detect_minimap_quest(raw, width, height, turn_in=turn_in)


def detect_minimap_quest(buffer: bytes, width: int, height: int, turn_in: bool = False) -> MinimapQuestObservation:
    # The user's Retail UI has the circular minimap in the top-right corner.
    center = MapPoint(round(width * 0.921), round(height * 0.174))
    radius = height * 0.088
    target = _detect_minimap_target(buffer, width, height, center, radius)
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    yy, xx = np.ogrid[:height, :width]
    inside = (xx - center.x) ** 2 + (yy - center.y) ** 2 < radius ** 2
    if turn_in:
        # A completed tracked quest is a tiny bright yellow question mark on
        # the Retail minimap. Detect it before the blue area contour so the
        # character routes to the questgiver instead of revisiting the area.
        turn_in_inside = (xx - center.x) ** 2 + (yy - center.y) ** 2 < (height * 0.078) ** 2
        gold_mask = (
            (red > 175)
            & (green > 105)
            & (blue < 90)
            & (red.astype(np.int16) > blue.astype(np.int16) + 90)
            & turn_in_inside
        )
        turn_in_candidates: list[tuple[float, int, MapPoint]] = []
        for component in _components(_mask_points(gold_mask)):
            if not 3 <= len(component) <= 40:
                continue
            xs, ys = [point[0] for point in component], [point[1] for point in component]
            box_width, box_height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
            if not (1 <= box_width <= 9 and 2 <= box_height <= 16):
                continue
            point = MapPoint(round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))
            distance = math.hypot(point.x - center.x, point.y - center.y)
            turn_in_candidates.append((distance, -len(component), point))
        selected_turn_in = min(turn_in_candidates, default=None, key=lambda item: (item[0], item[1]))
        if selected_turn_in is not None:
            return MinimapQuestObservation(center, selected_turn_in[2], target)
    # Retail quest areas use a blue-violet contour. It is anti-aliased and can
    # be one-pixel fragmented, so dilate once before component extraction.
    mask = (
        (blue > 85)
        & (blue.astype(np.int16) > red.astype(np.int16) + 25)
        & inside
    )
    dilated = mask.copy()
    dilated[1:, :] |= mask[:-1, :]
    dilated[:-1, :] |= mask[1:, :]
    dilated[:, 1:] |= mask[:, :-1]
    dilated[:, :-1] |= mask[:, 1:]
    candidates: list[tuple[float, int, MapPoint, list[tuple[int, int]]]] = []
    for component in _components(_mask_points(dilated)):
        if not 80 <= len(component) <= 1400:
            continue
        xs, ys = [point[0] for point in component], [point[1] for point in component]
        box_width, box_height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if not (20 <= box_width <= 50 and 18 <= box_height <= 40):
            continue
        point = MapPoint(round((min(xs) + max(xs)) / 2), round((min(ys) + max(ys)) / 2))
        distance = math.hypot(point.x - center.x, point.y - center.y)
        candidates.append((distance, -len(component), point, component))
    selected = min(candidates, default=None, key=lambda item: (item[0], item[1]))
    if selected is None:
        quest = None
    elif _component_encloses(selected[3], center):
        # The player is genuinely inside a closed quest outline. A bounding
        # box check alone is insufficient for irregular/merged minimap shapes.
        quest = center
    else:
        quest = selected[2]
    return MinimapQuestObservation(center, quest, target)


def _detect_minimap_target(
    buffer: bytes,
    width: int,
    height: int,
    center: MapPoint,
    radius: float,
) -> Optional[MapPoint]:
    # Only the currently selected target is rendered as a small dot on the
    # Retail minimap. Its colour reflects the reaction: red=enemy, yellow=
    # neutral/killable (typical quest KILL target), green=friendly/questgiver.
    # Detect the most prominent such dot inside the circular minimap so the
    # character can steer toward an out-of-range target.
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    yy, xx = np.ogrid[:height, :width]
    inside = (xx - center.x) ** 2 + (yy - center.y) ** 2 < radius ** 2
    r16, g16, b16 = red.astype(np.int16), green.astype(np.int16), blue.astype(np.int16)
    red_dot = (r16 > 170) & (r16 > g16 + 45) & (r16 > b16 + 45) & inside
    yellow_dot = (r16 > 185) & (g16 > 120) & (b16 < 110) & (r16 > b16 + 80) & inside
    green_dot = (g16 > 165) & (g16 > r16 + 45) & (g16 > b16 + 45) & inside
    mask = red_dot | yellow_dot | green_dot
    candidates: list[tuple[int, float, MapPoint]] = []
    for component in _components(_mask_points(mask)):
        size = len(component)
        if not 2 <= size <= 90:
            continue
        xs, ys = [point[0] for point in component], [point[1] for point in component]
        box_width, box_height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if not (1 <= box_width <= 28 and 1 <= box_height <= 34):
            continue
        point = MapPoint(round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))
        distance = math.hypot(point.x - center.x, point.y - center.y)
        if distance < 2:
            continue
        candidates.append((size, distance, point))
    if not candidates:
        return None
    # Prefer the strongest dot; ties broken by proximity to the player.
    strongest = max(candidates, key=lambda item: item[0])
    best = min(candidates, key=lambda item: (item[1], -item[0]))
    # A clearly dominant dot is almost always the selected target.
    if strongest[0] >= 2 * max((c[0] for c in candidates if c is not strongest), default=0):
        return strongest[2]
    return best[2]


def _component_encloses(component: list[tuple[int, int]], point: MapPoint) -> bool:
    blocked = set(component)
    xs, ys = [pixel[0] for pixel in component], [pixel[1] for pixel in component]
    left, right, top, bottom = min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1
    if not (left < point.x < right and top < point.y < bottom):
        return False
    if (point.x, point.y) in blocked:
        return True
    outside = {(left, top)}
    stack = [(left, top)]
    while stack:
        x, y = stack.pop()
        for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            nx, ny = neighbor
            if left <= nx <= right and top <= ny <= bottom and neighbor not in blocked and neighbor not in outside:
                outside.add(neighbor)
                stack.append(neighbor)
    return (point.x, point.y) not in outside
