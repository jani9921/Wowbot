from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

from .numpy_runtime import np

from .pixel_bridge import capture_window_bgra, decode_payload_from_bgra, payload_to_state, window_pixel_to_client_ratios
from .windows_input import click_window_normalized, focus_window_for_pid, move_cursor_window_pixel, send_key_sequence


_QUEST_POI_CACHE: dict[tuple[int, str], tuple[float, float]] = {}


@dataclass(frozen=True)
class MapPoint:
    x: int
    y: int


@dataclass(frozen=True)
class WorldMapObservation:
    player: Optional[MapPoint]
    quest: Optional[MapPoint]
    width: int
    height: int

    @property
    def vector(self) -> Optional[tuple[float, float]]:
        if self.player is None or self.quest is None:
            return None
        return float(self.quest.x - self.player.x), float(self.quest.y - self.player.y)

    @property
    def distance_pixels(self) -> Optional[float]:
        vector = self.vector
        return None if vector is None else math.hypot(*vector)


def detect_world_map(buffer: bytes, width: int, height: int) -> WorldMapObservation:
    left, right = int(width * 0.055), int(width * 0.945)
    top, bottom = int(height * 0.115), int(height * 0.965)
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    roi = pixels[top + 8:bottom - 8, left + 8:right - 8]
    blue, green, red = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    spread = np.maximum(np.maximum(red, green), blue) - np.minimum(np.minimum(red, green), blue)
    white_mask = (red > 175) & (green > 175) & (blue > 165) & (spread < 65)
    gold_mask = (red > 175) & (green > 105) & (green < 225) & (blue < 85) & (red.astype(np.float32) > blue * 2.5)
    white = _mask_points(white_mask, left + 8, top + 8)
    gold = _mask_points(gold_mask, left + 8, top + 8)
    white_components = _components(white)
    player_candidates = []
    for component in white_components:
        xs, ys = [p[0] for p in component], [p[1] for p in component]
        box_w, box_h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if 2 <= box_w <= 20 and 3 <= box_h <= 28 and 3 <= len(component) <= 150:
            player_candidates.append((len(component), MapPoint(sum(xs) // len(xs), sum(ys) // len(ys))))
    player = max(player_candidates, default=(0, None), key=lambda item: item[0])[1]

    quest_candidates = []
    for component in _components(gold):
        xs, ys = [p[0] for p in component], [p[1] for p in component]
        box_w, box_h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        center = MapPoint(sum(xs) // len(xs), sum(ys) // len(ys))
        if 2 <= box_w <= 28 and 2 <= box_h <= 35 and 3 <= len(component) <= 350:
            if player is None or math.hypot(center.x - player.x, center.y - player.y) > 2:
                quest_candidates.append((len(component), center))
    quest = None
    return WorldMapObservation(player, quest, width, height)


def observe_world_map(pid: int, settle_seconds: float = 0.7, quest_title: Optional[str] = None) -> WorldMapObservation:
    if not focus_window_for_pid(pid):
        raise RuntimeError(f"could not focus pid {pid}")
    raw, width, height = capture_window_bgra(pid)
    exported = _exported_state(raw, width, height)
    cache_key = _cache_key(exported, quest_title)
    cached = _QUEST_POI_CACHE.get(cache_key) if cache_key else None
    if cached is not None:
        player = _player_from_state(exported, width, height)
        if player is not None:
            quest = _map_normalized_to_pixel(cached[0], cached[1], width, height)
            return WorldMapObservation(player, quest, width, height)
    if not is_world_map_open(raw, width, height):
        send_key_sequence("M")
        time.sleep(min(settle_seconds, 0.35))
    try:
        raw, width, height = capture_window_bgra(pid)
        observation = detect_world_map(raw, width, height)
        # The first M press opens the compact Map & Quest Log. Its maximize
        # button switches to the full current-zone map used for routing.
        if observation.player is not None and observation.player.x < width * 0.46:
            click_window_normalized(pid, 0.644, 0.879)
            time.sleep(settle_seconds)
            raw, width, height = capture_window_bgra(pid)
            observation = detect_world_map(raw, width, height)
        player = _player_from_export(raw, width, height) or observation.player
        candidates = _quest_icon_candidates(raw, width, height)
        if player is not None:
            candidates.sort(key=lambda point: math.hypot(point.x - player.x, point.y - player.y))
        # A tracked objective badge sitting immediately beside the exported
        # player coordinate is unambiguous and avoids hovering over dozens of
        # decorative gold map labels.
        if quest_title and player is not None and candidates:
            nearest = candidates[0]
            if math.hypot(nearest.x - player.x, nearest.y - player.y) < 35:
                _remember_quest_poi(cache_key, nearest, width, height)
                return WorldMapObservation(player, nearest, width, height)
        for candidate in candidates[:6]:
            move_cursor_window_pixel(pid, candidate.x, candidate.y)
            for _ in range(3):
                time.sleep(0.12)
                hovered, hovered_width, hovered_height = capture_window_bgra(pid)
                payload = decode_payload_from_bgra(hovered, hovered_width, hovered_height)
                if not payload:
                    continue
                tooltip = (payload_to_state(payload).get("map_tooltip") or "").lower()
                wanted_title = (quest_title or "").lower()
                if (wanted_title and wanted_title in tooltip) or "available quest" in tooltip or "quest objective" in tooltip:
                    _remember_quest_poi(cache_key, candidate, width, height)
                    return WorldMapObservation(player, candidate, width, height)
        return observation
    finally:
        send_key_sequence("M")


def _player_from_export(buffer: bytes, width: int, height: int) -> Optional[MapPoint]:
    return _player_from_state(_exported_state(buffer, width, height), width, height)


def _exported_state(buffer: bytes, width: int, height: int) -> dict:
    payload = decode_payload_from_bgra(buffer, width, height)
    return payload_to_state(payload) if payload else {}


def _player_from_state(state: dict, width: int, height: int) -> Optional[MapPoint]:
    position = state.get("position") or {}
    x, y = position.get("x"), position.get("y")
    if x is None or y is None or not (0 <= x <= 1 and 0 <= y <= 1):
        return None
    # Full Retail zone-map canvas inside the outer frame.
    return MapPoint(
        round(width * (0.046 + float(x) * 0.908)),
        round(height * (0.109 + float(y) * 0.875)),
    )


def _cache_key(state: dict, quest_title: Optional[str]) -> Optional[tuple[int, str]]:
    map_id = state.get("map_id")
    title = (quest_title or "").strip().lower()
    return (int(map_id), title) if map_id is not None and title else None


def _remember_quest_poi(key: Optional[tuple[int, str]], point: MapPoint, width: int, height: int) -> None:
    if key is None:
        return
    _QUEST_POI_CACHE[key] = (
        (point.x / width - 0.046) / 0.908,
        (point.y / height - 0.109) / 0.875,
    )


def _map_normalized_to_pixel(x: float, y: float, width: int, height: int) -> MapPoint:
    return MapPoint(round(width * (0.046 + x * 0.908)), round(height * (0.109 + y * 0.875)))


def is_world_map_open(buffer: bytes, width: int, height: int) -> bool:
    # Retail's map has a nearly continuous dark header/frame above the map.
    # Looking for parchment colours is unreliable because ordinary terrain
    # (grass, sand and rock) uses the same palette.
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    sample = pixels[int(height * 0.052):int(height * 0.102):3, int(width * 0.06):int(width * 0.94):4, :3]
    return bool(sample.size and np.mean(np.all(sample < 65, axis=2)) > 0.72)


def _mask_points(mask: np.ndarray, x_offset: int = 0, y_offset: int = 0) -> set[tuple[int, int]]:
    ys, xs = np.nonzero(mask)
    return set(zip((xs + x_offset).tolist(), (ys + y_offset).tolist()))


def _components(points: set[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    components = []
    while points:
        start = points.pop()
        component, stack = [start], [start]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1),
                             (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1)):
                if neighbor in points:
                    points.remove(neighbor)
                    component.append(neighbor)
                    stack.append(neighbor)
        components.append(component)
    return components


def _quest_icon_candidates(buffer: bytes, width: int, height: int) -> list[MapPoint]:
    left, right = int(width * 0.07), int(width * 0.93)
    top, bottom = int(height * 0.13), int(height * 0.94)
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    roi = pixels[top:bottom, left:right]
    blue, green, red = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    mask = ((red > 145) & (green > 110) & (green < 205) & (blue < 75)
            & (red.astype(np.float32) > blue * 2.2))
    points = _mask_points(mask, left, top)
    result = []
    for component in _components(points):
        xs, ys = [p[0] for p in component], [p[1] for p in component]
        box_w, box_h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        # Retail's yellow quest badge is a dense 9x12-ish component at the
        # current UI scale (roughly 80 matching pixels), while small map text
        # fragments are generally much sparser.
        if 2 <= box_w <= 14 and 2 <= box_h <= 22 and 3 <= len(component) <= 120:
            result.append(MapPoint(sum(xs) // len(xs), sum(ys) // len(ys)))
    return result
