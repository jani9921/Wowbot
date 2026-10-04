from __future__ import annotations

import ctypes
import json
import math
import time
from ctypes import wintypes
from pathlib import Path
from typing import Optional

from src.adapters.numpy_runtime import np
from src.adapters.atomic_file import write_json_replace


HEADER = (2, 0, 1, 3, 2, 3, 1, 0)  # green, black, red, blue, green, blue, red, black
_GRID_CACHE: dict[tuple[int, int], tuple[int, int, float]] = {}
_LAST_DISCOVERY: dict[str, object] = {}
_PROFILE_PATH = Path(__file__).resolve().parents[2] / "config" / "pixel_strip_profiles.json"


def _load_strip_profiles(path: Path = _PROFILE_PATH) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("profiles"), list):
            return value
    except (OSError, ValueError, TypeError):
        pass
    return {"profiles": [], "fallback": {"name": "scaled-fallback", "search_x": 192,
            "search_y": 384, "min_pitch": .75, "max_pitch": 8.0, "expected_pitch": 4.0}}


_STRIP_PROFILES = _load_strip_profiles()


def pixel_strip_profile(width: int, height: int) -> dict:
    """Return the exact or nearest physical-client-size discovery profile."""
    profiles = [item for item in _STRIP_PROFILES.get("profiles", [])
                if isinstance(item, dict) and item.get("width") and item.get("height")]
    exact = next((item for item in profiles
                  if int(item["width"]) == width and int(item["height"]) == height), None)
    if exact:
        return dict(exact)
    if profiles:
        aspect = width / max(1, height)
        nearest = min(profiles, key=lambda item: (
            abs(math.log(width / int(item["width"])))
            + abs(math.log(height / int(item["height"])))
            + 2 * abs(aspect - int(item["width"]) / int(item["height"]))))
        result = dict(nearest)
        result["name"] = f"scaled:{nearest.get('name', 'nearest')}"
        result["width"], result["height"] = width, height
        return result
    return {**_STRIP_PROFILES.get("fallback", {}), "width": width, "height": height}


def pixel_strip_diagnostics() -> dict[str, object]:
    return dict(_LAST_DISCOVERY)


def classify_rgb(red: int, green: int, blue: int) -> Optional[int]:
    if max(red, green, blue) < 90:
        return 0
    if red > 150 and red > green * 1.7 and red > blue * 1.7:
        return 1
    if green > 150 and green > red * 1.7 and green > blue * 1.7:
        return 2
    if blue > 150 and blue > red * 1.5 and blue > green * 1.5:
        return 3
    return None


def _adaptive_header_candidates(buffer: bytes, width: int, height: int):
    """Infer strip origin/pitch from its rendered colour-run header."""
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    blue = pixels[:, :, 0].astype(np.int16)
    green = pixels[:, :, 1].astype(np.int16)
    red = pixels[:, :, 2].astype(np.int16)
    classes = np.full((height, width), -1, dtype=np.int8)
    classes[np.maximum(np.maximum(red, green), blue) < 90] = 0
    classes[(red > 150) & (red > green * 1.7) & (red > blue * 1.7)] = 1
    classes[(green > 150) & (green > red * 1.7) & (green > blue * 1.7)] = 2
    classes[(blue > 150) & (blue > red * 1.5) & (blue > green * 1.5)] = 3
    classified = int(np.count_nonzero(classes >= 0))
    candidates = []
    for y in range(max(1, int(height * .80))):
        row = classes[y]
        changes = np.flatnonzero(row[1:] != row[:-1]) + 1
        starts = np.concatenate((np.array([0]), changes))
        ends = np.concatenate((changes, np.array([width])))
        values = row[starts]
        for index in np.flatnonzero(values == HEADER[0]):
            if index + 7 > len(values) or tuple(int(v) for v in values[index:index+7]) != HEADER[:7]:
                continue
            run_widths = (ends[index:index+7] - starts[index:index+7]).astype(float)
            pitch = float(np.median(run_widths))
            if not .5 <= pitch <= 12 or np.max(np.abs(run_widths-pitch)) > max(2., pitch*.65):
                continue
            centers = (starts[index:index+7] + ends[index:index+7] - 1) / 2
            slope, intercept = np.polyfit(np.arange(7), centers, 1)
            if .5 <= slope <= 12:
                candidates.append((float(intercept), y, float(slope)))
                if len(candidates) >= 80:
                    return candidates, classified
    return candidates, classified


def _decode_adaptive(buffer: bytes, width: int, height: int):
    candidates, classified = _adaptive_header_candidates(buffer, width, height)
    seen = set()
    for origin, y, measured_pitch in candidates:
        identity = (round(origin, 1), round(measured_pitch, 2))
        if identity in seen:
            continue
        seen.add(identity)
        for x_offset in (0., -.5, .5, -1., 1.):
            for delta_milli in range(-180, 181, 2):
                pitch = measured_pitch + delta_milli / 1000.
                x = round(origin+x_offset)
                if pitch < .5 or x + (len(HEADER)-1)*pitch >= width:
                    continue
                payload = _decode_grid(buffer, width, height, x, y, pitch)
                if payload is not None:
                    return payload, (x, y, pitch), len(candidates), classified
    return None, None, len(candidates), classified


def decode_payload_from_bgra(buffer: bytes, width: int, height: int) -> Optional[str]:
    profile = pixel_strip_profile(width, height)
    _LAST_DISCOVERY.clear()
    _LAST_DISCOVERY.update({"resolution": f"{width}x{height}", "profile": profile.get("name"),
                            "cache_hit": False, "status": "searching"})
    def color(x: int, y: int) -> Optional[int]:
        offset = (y * width + x) * 4
        blue, green, red = buffer[offset], buffer[offset + 1], buffer[offset + 2]
        return classify_rgb(red, green, blue)

    cached = _GRID_CACHE.get((width, height))
    if cached is not None:
        payload = _decode_grid(buffer, width, height, *cached)
        if payload is not None:
            _LAST_DISCOVERY.update({"cache_hit": True, "status": "decoded",
                                    "x": cached[0], "y": cached[1], "pitch": cached[2]})
            return payload
        if _header_present(buffer, width, height, *cached):
            # The strip is still exactly where it was; only this frame's body
            # is torn or mid-update.  A full rediscovery here cost 200-280 ms
            # of pure Python per frame and starved every other agent thread.
            _LAST_DISCOVERY.update({"cache_hit": True, "status": "torn_frame",
                                    "x": cached[0], "y": cached[1], "pitch": cached[2]})
            return None
        _GRID_CACHE.pop((width, height), None)

    # New addons use a physical four-pixel pitch. Try the likely client/window
    # origins first; legacy UI-scaled strips remain supported by the fallback.
    expected = float(profile.get("expected_pitch", 4.0))
    max_x = min(width, max(32, int(profile.get("search_x", 192))))
    max_y = min(height, max(64, int(profile.get("search_y", 384))))
    fast_pitches = list(dict.fromkeys([expected, 4.0, 3.0, 2.0, 5.0, 2.5, 3.5, 4.5]))
    fast_x = min(max_x, 32)
    fast_y = min(max_y, 96)
    for y in range(fast_y):
        for x in range(fast_x):
            if color(x, y) != HEADER[0]:
                continue
            for pitch in fast_pitches:
                if x + (len(HEADER) - 1) * pitch >= width:
                    continue
                if all(color(round(x + i * pitch), y) == wanted for i, wanted in enumerate(HEADER)):
                    payload = _decode_grid(buffer, width, height, x, y, pitch)
                    if payload is not None:
                        _GRID_CACHE[(width, height)] = (x, y, pitch)
                        _LAST_DISCOVERY.update({"status": "decoded", "x": x, "y": y,
                                                "pitch": pitch, "path": "profile_fast"})
                        return payload

    payload, geometry, header_candidates, classified = _decode_adaptive(buffer, width, height)
    _LAST_DISCOVERY.update({"adaptive_header_candidates": header_candidates,
                            "classified_pixels": classified})
    if payload is not None:
        _GRID_CACHE[(width, height)] = geometry
        _LAST_DISCOVERY.update({"status": "decoded", "x": geometry[0], "y": geometry[1],
                                "pitch": geometry[2], "path": "adaptive_header_geometry"})
        return payload

    min_pitch = max(.5, float(profile.get("min_pitch", .75)))
    max_pitch = min(12., float(profile.get("max_pitch", 8.0)))
    first_pitch = max(10, round(min_pitch * 20))
    last_pitch = max(first_pitch, round(max_pitch * 20))
    for y in range(max_y):
        for x in range(max_x):
            if color(x, y) != HEADER[0]:
                continue
            for pitch_twentieths in range(first_pitch, last_pitch + 1):
                pitch = pitch_twentieths / 20.0
                if x + (len(HEADER) - 1) * pitch >= max_x:
                    break
                if all(color(round(x + i * pitch), y) == wanted for i, wanted in enumerate(HEADER)):
                    start = max(700, round((pitch - 0.30) * 1000))
                    end = min(8000, round((pitch + 0.30) * 1000))
                    for refined_milli in range(start, end + 1):
                        refined = refined_milli / 1000.0
                        if all(color(round(x + i * refined), y) == wanted for i, wanted in enumerate(HEADER)):
                            payload = _decode_grid(buffer, width, height, x, y, refined)
                            if payload is not None:
                                _GRID_CACHE[(width, height)] = (x, y, refined)
                                _LAST_DISCOVERY.update({"status": "decoded", "x": x, "y": y,
                                                        "pitch": refined, "path": "legacy_fallback"})
                                return payload
    _LAST_DISCOVERY["status"] = "not_visible"
    return None


def _cell_classes(buffer: bytes, width: int, height: int, center_x: float, center_y: float,
                  pitch: float, start: int, count: int):
    """Vectorized classify_rgb for grid cells ``start..start+count``.

    Returns an int8 array, or None when any cell is outside the frame or has
    no colour class (exactly the per-cell rules of the former Python loop).
    Live 2026-09-30: the per-cell Python loop pinned the pixel-sensor thread at
    80-92 % of a core while strip discovery retried geometries.
    """
    columns = 128
    index = np.arange(start, start + count)
    # np.rint and Python round() both round half to even, so cell positions
    # are identical to the former scalar implementation.
    xs = np.rint(center_x + (index % columns) * pitch).astype(np.int64)
    ys = np.rint(center_y + (index // columns) * pitch).astype(np.int64)
    if count == 0:
        return np.zeros(0, dtype=np.int8)
    if xs.min() < 0 or ys.min() < 0 or xs.max() >= width or ys.max() >= height:
        return None
    pixels = np.frombuffer(buffer, dtype=np.uint8, count=width * height * 4).reshape(height, width, 4)
    sample = pixels[ys, xs]
    blue = sample[:, 0].astype(np.float64)
    green = sample[:, 1].astype(np.float64)
    red = sample[:, 2].astype(np.float64)
    classes = np.full(count, -1, dtype=np.int8)
    # Assign in reverse priority so the first matching rule of classify_rgb wins.
    classes[(blue > 150) & (blue > red * 1.5) & (blue > green * 1.5)] = 3
    classes[(green > 150) & (green > red * 1.7) & (green > blue * 1.7)] = 2
    classes[(red > 150) & (red > green * 1.7) & (red > blue * 1.7)] = 1
    classes[np.maximum(np.maximum(red, green), blue) < 90] = 0
    if (classes < 0).any():
        return None
    return classes


def _bytes_from_cells(classes) -> list[int]:
    quads = classes.reshape(-1, 4).astype(np.int64)
    return (((quads[:, 0] * 4 + quads[:, 1]) * 4 + quads[:, 2]) * 4 + quads[:, 3]).tolist()


def _header_present(buffer: bytes, width: int, height: int, center_x: float, center_y: float,
                    pitch: float) -> bool:
    classes = _cell_classes(buffer, width, height, center_x, center_y, pitch, 0, len(HEADER))
    return classes is not None and tuple(int(value) for value in classes) == HEADER


def _decode_grid(buffer: bytes, width: int, height: int, center_x: int, center_y: int, pitch: float) -> Optional[str]:
    length_cells = _cell_classes(buffer, width, height, center_x, center_y, pitch, 8, 8)
    if length_cells is None:
        return None
    high, low = _bytes_from_cells(length_cells)
    length = high * 256 + low
    if not 1 <= length <= 1000:
        return None
    body = _cell_classes(buffer, width, height, center_x, center_y, pitch, 16, (length + 1) * 4)
    if body is None:
        return None
    decoded = _bytes_from_cells(body)
    values, checksum = decoded[:length], decoded[length]
    if checksum != sum(values) % 256:
        return None
    try:
        payload = bytes(values).decode("utf-8")
    except UnicodeDecodeError:
        return None
    return payload if payload.startswith(("AIPC1|", "AIPC2|", "AIPC3|", "AIPC4|", "AIPC5|")) else None


def capture_window_bgra(pid: int, ensure_foreground: bool = False) -> tuple[bytes, int, int]:
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = _window_for_pid(pid)
    if not hwnd:
        raise RuntimeError(f"no visible window for pid {pid}")
    if ensure_foreground and user32.GetForegroundWindow() != hwnd:
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.025)
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError()
    width, height = rect.right - rect.left, rect.bottom - rect.top
    screen_dc = user32.GetDC(0)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    old = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc, rect.left, rect.top, 0x00CC0020):
            raise ctypes.WinError()
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        raw = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(memory_dc, bitmap, 0, height, raw, ctypes.byref(info), 0):
            raise ctypes.WinError()
        return raw.raw, width, height
    finally:
        gdi32.SelectObject(memory_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)


def payload_to_state(payload: str, previous: Optional[dict] = None, client_id: str = "client-1") -> dict:
    fields = payload.split("|")
    if len(fields) < 19 or fields[0] not in ("AIPC1", "AIPC2", "AIPC3", "AIPC4"):
        raise ValueError("invalid AIPC pixel payload")
    payload_version = fields[0]
    state = dict(previous or {})
    state.update({
        "client_id": client_id,
        "protocol_version": payload_version,
        "timestamp": _number(fields[1], time.time()),
        "character_name": _text(fields[2]),
        "map_id": _integer(fields[3]),
        "position": {"x": _number(fields[4], 0) / 100000, "y": _number(fields[5], 0) / 100000, "z": 0},
        "orientation": _number(fields[6], 0) / 1000,
        "health": _integer(fields[7]), "max_health": _integer(fields[8]),
        "power": _integer(fields[9]), "max_power": _integer(fields[10]),
        "is_in_combat": fields[11] == "1", "is_dead": fields[12] == "1", "is_mounted": fields[13] == "1",
        "current_target": _text(fields[14]),
        "nearby_nodes": [], "visible_nodes": [], "known_spells": [],
    })
    if payload_version in ("AIPC3", "AIPC4"):
        state["zone_name"] = _text(fields[15])
        state["subzone_name"] = _text(fields[16])
        state["quest_state_revision"] = _integer(fields[17])
        quest_total = _integer(fields[18]) or 0
        quest_page = _integer(fields[19]) if len(fields) > 19 else -1
        has_quest = len(fields) > 20 and fields[20] == "1"
        cursor = 21
        quest = None
        if has_quest and cursor + 3 < len(fields):
            quest_id = _integer(fields[cursor])
            title = _text(fields[cursor + 1])
            complete = fields[cursor + 2] == "1"
            objective_count = _integer(fields[cursor + 3]) or 0
            cursor += 4
            objectives = []
            for _ in range(objective_count):
                if cursor + 6 >= len(fields):
                    break
                objective = {
                    "type": fields[cursor],
                    "current": _integer(fields[cursor + 1]) or 0,
                    "required": _integer(fields[cursor + 2]) or 1,
                    "description": fields[cursor + 3],
                    "map_id": _integer(fields[cursor + 4]),
                }
                waypoint_x = _number(fields[cursor + 5], 0) / 100000
                waypoint_y = _number(fields[cursor + 6], 0) / 100000
                if waypoint_x or waypoint_y:
                    objective["position"] = {"x": waypoint_x, "y": waypoint_y, "z": 0}
                objectives.append(objective)
                cursor += 7
            quest = {
                "quest_id": quest_id,
                "title": title or "",
                "is_accepted": True,
                "is_complete": complete,
                "objectives": objectives,
            }
        previous_total = int((previous or {}).get("_quest_page_total", -1))
        pages = dict((previous or {}).get("_quest_pages", {})) if previous_total == quest_total else {}
        if quest is not None and quest_page is not None and 0 <= quest_page < quest_total:
            pages[str(quest_page)] = quest
        pages = {key: value for key, value in pages.items() if int(key) < quest_total}
        state["_quest_pages"] = pages
        state["_quest_page_total"] = quest_total
        state["active_quests"] = [pages[str(index)] for index in range(quest_total) if str(index) in pages]
    else:
        quest_id = _integer(fields[15])
        title = _text(fields[16])
        complete = fields[17] == "1"
        objective_count = _integer(fields[18]) or 0
        cursor, objectives = 19, []
        for _ in range(objective_count):
            if cursor + 3 >= len(fields):
                break
            objective = {"type": fields[cursor], "current": _integer(fields[cursor + 1]) or 0,
                         "required": _integer(fields[cursor + 2]) or 1, "description": fields[cursor + 3]}
            cursor += 4
            if payload_version == "AIPC2" and cursor + 2 < len(fields):
                objective["map_id"] = _integer(fields[cursor])
                waypoint_x = _number(fields[cursor + 1], 0) / 100000
                waypoint_y = _number(fields[cursor + 2], 0) / 100000
                if waypoint_x or waypoint_y:
                    objective["position"] = {"x": waypoint_x, "y": waypoint_y, "z": 0}
                cursor += 3
            objectives.append(objective)
        state["active_quests"] = [] if not quest_id else [{
            "quest_id": quest_id,
            "title": title or "",
            "is_accepted": True,
            "is_complete": complete,
            "objectives": objectives,
        }]
    actionbar = []
    if cursor < len(fields):
        action_count = _integer(fields[cursor]) or 0
        cursor += 1
        for _ in range(action_count):
            if cursor + 4 >= len(fields):
                break
            actionbar.append({
                "action": fields[cursor], "kind": fields[cursor + 1], "name": _text(fields[cursor + 2]),
                "spell_id": _integer(fields[cursor + 3]) if fields[cursor + 1] == "spell" else None,
                "item_id": _integer(fields[cursor + 3]) if fields[cursor + 1] == "item" else None,
                "is_usable": fields[cursor + 4] == "1",
            })
            cursor += 5
    state["actionbar"] = actionbar
    state["known_spells"] = [
        {"name": entry["name"], "spell_id": entry["spell_id"], "is_usable": entry["is_usable"]}
        for entry in actionbar if entry["kind"] == "spell" and entry["name"]
    ]
    if payload_version in ("AIPC3", "AIPC4"):
        state["quest_ui_open"] = cursor < len(fields) and fields[cursor] == "1"
        ui_count = _integer(fields[cursor + 1]) if cursor + 1 < len(fields) else 0
        cursor += 2
        ui_entries = []
        for _ in range(ui_count or 0):
            if cursor + 5 >= len(fields):
                break
            ui_entries.append({
                "kind": fields[cursor],
                "quest_id": _integer(fields[cursor + 1]),
                "title": _text(fields[cursor + 2]) or "",
                "x": (_number(fields[cursor + 3], 0) / 10000) or None,
                "y": (_number(fields[cursor + 4], 0) / 10000) or None,
                "is_acceptable": fields[cursor + 5] == "1",
            })
            cursor += 6
        state["quest_ui_entries"] = ui_entries
        if cursor + 3 < len(fields):
            state["quest_ui_action"] = _text(fields[cursor])
            state["quest_ui_x"] = (_number(fields[cursor + 1], 0) / 10000) or None
            state["quest_ui_y"] = (_number(fields[cursor + 2], 0) / 10000) or None
            state["quest_ui_quest_id"] = _integer(fields[cursor + 3])
        else:
            state["quest_ui_action"] = None
            state["quest_ui_x"] = None
            state["quest_ui_y"] = None
            state["quest_ui_quest_id"] = None
        cursor += 4
    elif cursor + 2 < len(fields):
        state["quest_ui_open"] = bool(_text(fields[cursor]))
        state["quest_ui_entries"] = []
        state["quest_ui_action"] = _text(fields[cursor])
        state["quest_ui_x"] = (_number(fields[cursor + 1], 0) / 10000) or None
        state["quest_ui_y"] = (_number(fields[cursor + 2], 0) / 10000) or None
        state["quest_ui_quest_id"] = None
        cursor += 3
    else:
        state["quest_ui_open"] = False
        state["quest_ui_entries"] = []
        state["quest_ui_action"] = None
        state["quest_ui_x"] = None
        state["quest_ui_y"] = None
        state["quest_ui_quest_id"] = None
    if cursor + 1 < len(fields):
        state["target_is_attackable"] = fields[cursor] == "1"
        state["target_is_dead"] = fields[cursor + 1] == "1"
    else:
        state["target_is_attackable"] = None
        state["target_is_dead"] = None
    mouse_cursor = cursor + 2
    state["mouseover"] = None
    if mouse_cursor < len(fields) and fields[mouse_cursor] == "1":
        # AIPC mouseover entity block. The addon only emits this block when
        # WoW currently exposes a real mouseover unit; terrain/objects never
        # become entity identities here.
        if mouse_cursor + 20 < len(fields):
            def _flag(value: str):
                return None if value == "?" else value == "1"
            state["mouseover"] = {
                "name": _text(fields[mouse_cursor + 1]),
                "realm": _text(fields[mouse_cursor + 2]),
                "guid": _text(fields[mouse_cursor + 3]),
                "npc_id": _integer(fields[mouse_cursor + 4]),
                "unit_type": _text(fields[mouse_cursor + 5]),
                "level": _integer(fields[mouse_cursor + 6]),
                "classification": _text(fields[mouse_cursor + 7]),
                "creature_type": _text(fields[mouse_cursor + 8]),
                "creature_family": _text(fields[mouse_cursor + 9]),
                "reaction": _text(fields[mouse_cursor + 10]),
                "reaction_value": _integer(fields[mouse_cursor + 11]),
                "class_name": _text(fields[mouse_cursor + 12]),
                "class_token": _text(fields[mouse_cursor + 13]),
                "is_player": fields[mouse_cursor + 14] == "1",
                "is_dead": fields[mouse_cursor + 15] == "1",
                "is_attackable": _flag(fields[mouse_cursor + 16]),
                "is_tap_denied": _flag(fields[mouse_cursor + 17]),
                "is_connected": _flag(fields[mouse_cursor + 18]),
            }
            wx = _number(fields[mouse_cursor + 19], None)
            wy = _number(fields[mouse_cursor + 20], None)
            wz = _number(fields[mouse_cursor + 21], None) if mouse_cursor + 21 < len(fields) else None
            if wx is not None and wy is not None:
                state["mouseover"]["world_position"] = {"x": wx / 100, "y": wy / 100, "z": (wz or 0) / 100}
        mouse_cursor += 22
    elif mouse_cursor < len(fields):
        # The presence flag is always emitted, including when there is no
        # mouseover unit. Cursor/map fields start immediately after it.
        mouse_cursor += 1
    if mouse_cursor + 1 < len(fields):
        cursor_nx = _number(fields[mouse_cursor], None)
        cursor_ny = _number(fields[mouse_cursor + 1], None)
        if cursor_nx is not None and cursor_ny is not None:
            state["cursor_position"] = {
                "nx": cursor_nx / 100000,
                "ny": cursor_ny / 100000,
            }
        else:
            state["cursor_position"] = None
        mouse_cursor += 2
    else:
        state["cursor_position"] = None
    state["map_mouseover"] = None
    if payload_version == "AIPC4" and mouse_cursor + 10 < len(fields):
        surface = _text(fields[mouse_cursor])
        semantic = _text(fields[mouse_cursor + 1])
        map_id = _integer(fields[mouse_cursor + 2])
        mx = _number(fields[mouse_cursor + 3], None)
        my = _number(fields[mouse_cursor + 4], None)
        lx = _number(fields[mouse_cursor + 5], None)
        ly = _number(fields[mouse_cursor + 6], None)
        tooltip = _text(fields[mouse_cursor + 7])
        unit_name = _text(fields[mouse_cursor + 8])
        unit_npc_id = _integer(fields[mouse_cursor + 9])
        unit_guid = _text(fields[mouse_cursor + 10])
        if surface:
            state["map_mouseover"] = {
                "surface": surface,
                "semantic_type": semantic or "UNKNOWN",
                "map_id": map_id,
                "x": mx / 100000 if mx is not None else None,
                "y": my / 100000 if my is not None else None,
                "local_x": lx / 100000 if lx is not None else None,
                "local_y": ly / 100000 if ly is not None else None,
                "tooltip": tooltip,
                "unit": ({"name": unit_name, "npc_id": unit_npc_id, "guid": unit_guid}
                         if unit_name or unit_npc_id is not None or unit_guid else None),
            }
        mouse_cursor += 11
    state["ui_error"] = _text(fields[mouse_cursor]) if mouse_cursor < len(fields) else None
    state["map_tooltip"] = _text(fields[mouse_cursor + 1]) if mouse_cursor + 1 < len(fields) else None
    state["tutorial_hint"] = _text(fields[mouse_cursor + 2]) if mouse_cursor + 2 < len(fields) else None
    state["dead_corpses"] = []
    corps_cursor = mouse_cursor + 3
    if corps_cursor < len(fields):
        corpse_count = _integer(fields[corps_cursor]) or 0
        corps_cursor += 1
        for _ in range(corpse_count):
            if corps_cursor + 2 >= len(fields):
                break
            cx = _number(fields[corps_cursor], None)
            cy = _number(fields[corps_cursor + 1], None)
            cguid = _text(fields[corps_cursor + 2])
            if cx is not None and cy is not None:
                state["dead_corpses"].append({"x": cx / 100000, "y": cy / 100000, "guid": cguid})
            corps_cursor += 3
    if payload_version == "AIPC4" and corps_cursor + 5 < len(fields):
        state["addon_version"] = _text(fields[corps_cursor])
        state["schema_version"] = _integer(fields[corps_cursor + 1])
        event_sequence = _integer(fields[corps_cursor + 2])
        event_type = _text(fields[corps_cursor + 3])
        event_source = _text(fields[corps_cursor + 4])
        event_timestamp = _number(fields[corps_cursor + 5], None)
        state["latest_event"] = ({
            "sequence": event_sequence,
            "event_type": event_type,
            "source": event_source,
            "timestamp": event_timestamp,
        } if event_type or event_sequence is not None else None)
    state["heartbeat"] = {
        "timestamp": state.get("timestamp"),
        "addon_version": state.get("addon_version"),
        "protocol_version": payload_version,
        "schema_version": state.get("schema_version"),
        "player_present": bool(state.get("character_name")),
        "map_id": state.get("map_id"),
    }
    target = state.get("current_target")
    has_target = target is not None
    if not has_target:
        state["target_is_attackable"] = None
        state["target_is_dead"] = None
    state["visible_units"] = [] if not has_target else [{
        "name": target or "Selected target",
        "is_attackable": state.get("target_is_attackable"),
        "is_interactable": state.get("target_is_attackable") is False,
        "is_dead": state.get("target_is_dead"),
    }]
    state["telemetry_source"] = "retail_pixel_bridge"
    return state


def detect_quest_marker(buffer: bytes, width: int, height: int) -> Optional[tuple[int, int]]:
    """Return a click point below a yellow quest exclamation marker."""
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    mask = (red > 210) & (green > 145) & (blue < 65) & (red.astype(np.int16) > blue.astype(np.int16) * 3)
    mask[:45, :] = False
    mask[int(height * 0.70):, :] = False
    mask[:, :8] = False
    mask[:, width - 8:] = False
    # At long range the dot and hook/stem of a quest marker are separate
    # components. A one-pixel dilation joins them without merging ordinary
    # torches or the fixed objective tracker text.
    dilated = mask.copy()
    dilated[1:, :] |= mask[:-1, :]
    dilated[:-1, :] |= mask[1:, :]
    dilated[:, 1:] |= mask[:, :-1]
    dilated[:, :-1] |= mask[:, 1:]
    ys, xs = np.nonzero(dilated)
    candidates = set(zip(xs.tolist(), ys.tolist()))
    if not candidates:
        return None
    groups: list[list[tuple[int, int]]] = []
    while candidates:
        start = candidates.pop()
        group, stack = [start], [start]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1),
                             (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1)):
                if neighbor in candidates:
                    candidates.remove(neighbor); group.append(neighbor); stack.append(neighbor)
        if len(group) >= 5:
            groups.append(group)
    matches = []
    compact_matches = []
    distant_world_matches = []
    for group in groups:
        xs, ys = [p[0] for p in group], [p[1] for p in group]
        box_width, box_height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        center_x = sum(xs) // len(xs)
        center_y = sum(ys) // len(ys)
        # Ignore the retail objective tracker/tutorial flyout region. Those
        # fixed yellow arrows otherwise look like world-space quest markers.
        in_right_side_ui = center_x > width * 0.70 and center_y < height * 0.72
        density = len(group) / max(1, box_width * box_height)
        aspect = box_height / max(1, box_width)
        if (
            not in_right_side_ui
            and 6 <= box_width <= 24
            and 14 <= box_height <= 35
            and 1.15 <= aspect <= 2.6
            and density >= 0.52
        ):
            # Retail's world quest marker is a dense, vertically oriented
            # badge. This rejects quest-tracker text, the large completion
            # arrow, and yellow ship geometry.
            matches.append((len(group), sum(xs) // len(xs), min(ys), max(ys)))
        elif (
            width < 400
            and not in_right_side_ui
            and 3 <= box_width <= 8
            and 6 <= box_height <= 12
        ):
            # Preserve recognition of genuinely tiny markers in low-resolution
            # replay fixtures; Retail's normal client render uses the stronger
            # badge geometry above.
            compact_matches.append((len(group), sum(xs) // len(xs), min(ys), max(ys)))
        elif (
            width >= 400
            and width * 0.18 <= center_x <= width * 0.70
            and height * 0.10 <= center_y <= height * 0.58
            and 5 <= box_width <= 10
            and 5 <= box_height <= 13
            and len(group) >= 14
        ):
            # A distant world marker on the island can render as only a few
            # yellow pixels. Restrict this fallback to the central 3D view so
            # taskbar icons and the objective tracker cannot match it.
            distant_world_matches.append(
                (len(group), sum(xs) // len(xs), min(ys), max(ys))
            )
    if not matches:
        matches = compact_matches or distant_world_matches
    if not matches:
        return None
    _, center_x, _top, bottom = max(matches, key=lambda item: item[0])
    return center_x, min(height - 1, bottom + 35)


def detect_campfire(buffer: bytes, width: int, height: int) -> Optional[tuple[int, int]]:
    """Find the strongest nearby orange fire cluster in the playable world area."""
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    red16, green16 = red.astype(np.int16), green.astype(np.int16)
    mask = (
        (red > 170)
        & (green > 65)
        & (green < 200)
        & (blue < 80)
        & (red16 > green16 * 1.25)
    )
    # Exclude the addon strip, action bars and edge UI. Nearby campfires occupy
    # the central/lower world view; distant torches usually form smaller blobs.
    mask[:int(height * 0.30), :] = False
    mask[int(height * 0.78):, :] = False
    mask[:, :int(width * 0.10)] = False
    mask[:, int(width * 0.85):] = False
    ys, xs = np.nonzero(mask)
    points = set(zip(xs.tolist(), ys.tolist()))
    matches: list[tuple[float, int, int]] = []
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
        if len(component) < 10:
            continue
        component_xs, component_ys = [p[0] for p in component], [p[1] for p in component]
        box_width = max(component_xs) - min(component_xs) + 1
        box_height = max(component_ys) - min(component_ys) + 1
        if box_width <= 35 and box_height <= 35:
            center_x = round(sum(component_xs) / len(component_xs))
            center_y = round(sum(component_ys) / len(component_ys))
            center_penalty = abs(center_x - width / 2) / max(1, width)
            matches.append((len(component) - center_penalty * 8, center_x, center_y))
    if not matches:
        return None
    # Without OCR several neutral mobs can have identical gold bars. Accept a
    # fresh bearing only near the central interaction corridor; the temporal
    # tracker may then follow small subsequent motion. This prevents a restart
    # from locking onto an unrelated edge nameplate and circling toward it.
    central_matches = [
        match for match in matches
        if width * 0.28 <= match[1] <= width * 0.72
    ]
    if not central_matches:
        return None
    _, center_x, center_y = max(
        central_matches,
        key=lambda match: match[0] - abs(match[1] - width / 2) * 2.0 + match[2] * 0.15,
    )
    return center_x, center_y


def detect_friendly_nameplate(buffer: bytes, width: int, height: int) -> Optional[tuple[int, int]]:
    """Find the strongest bright-green world name and return a point on the unit below it."""
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    mask = (
        (green > 165)
        & (green.astype(np.float32) > red * 1.8)
        & (green.astype(np.float32) > blue * 1.45)
        & (red < 125)
    )
    mask[:42, :] = False
    mask[int(height * 0.70):, :] = False
    mask[:, :6] = False
    mask[:, width - 6:] = False
    mask[int(height * 0.22):int(height * 0.50), :int(width * 0.42)] = False
    # The addon transport contains dense green pixel rows. World-name text
    # is sparse, so drop only rows that are too dense to be text.
    dense_limit = max(35, int(width * 0.075))
    row_counts = mask.sum(axis=1)
    mask[row_counts >= dense_limit, :] = False
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    bin_x, bin_y = xs // 64, ys // 22
    keys = bin_y * ((width + 63) // 64) + bin_x
    unique, counts = np.unique(keys, return_counts=True)
    best = unique[int(np.argmax(counts))]
    bx, by = int(best % ((width + 63) // 64)), int(best // ((width + 63) // 64))
    selected = (np.abs(bin_x - bx) <= 1) & (np.abs(bin_y - by) <= 1)
    if int(selected.sum()) < 8:
        return None
    center_x = int(xs[selected].mean())
    bottom = int(ys[selected].max())
    return center_x, min(height - 1, bottom + 46)


def detect_enemy_nameplate(buffer: bytes, width: int, height: int) -> Optional[tuple[int, int]]:
    """Find the selected enemy's long gold world-nameplate, excluding fixed UI."""
    pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    # A close selected neutral/hostile unit uses a large red world-name
    # instead of a gold health bar. This text band provides its screen bearing.
    red_name = (
        (red > 170)
        & (green < 105)
        & (blue < 105)
        & (red.astype(np.int16) > green.astype(np.int16) * 2)
    )
    red_name[:int(height * 0.49), :] = False
    red_name[int(height * 0.70):, :] = False
    red_name[:, :int(width * 0.08)] = False
    red_name[:, int(width * 0.78):] = False
    row_counts = red_name.sum(axis=1)
    active_rows = np.flatnonzero(row_counts >= 10)
    if active_rows.size:
        bands: list[list[int]] = [[int(active_rows[0])]]
        for row in active_rows[1:]:
            row = int(row)
            if row <= bands[-1][-1] + 1:
                bands[-1].append(row)
            else:
                bands.append([row])
        red_matches: list[tuple[int, float, int, int]] = []
        for band in bands:
            y0, y1 = band[0], band[-1]
            ys, xs = np.nonzero(red_name[y0:y1 + 1])
            if not xs.size:
                continue
            box_width = int(xs.max() - xs.min() + 1)
            box_height = y1 - y0 + 1
            if 35 <= box_width <= 300 and 5 <= box_height <= 28:
                center_x = int(xs.mean())
                center_y = int(y0 + ys.mean())
                center_penalty = abs(center_x - width / 2) / max(1, width)
                red_matches.append((int(xs.size), center_penalty, center_x, center_y))
        if red_matches:
            _, _, center_x, center_y = max(
                red_matches, key=lambda item: item[0] - item[1] * 80
            )
            return center_x, center_y
    mask = (
        (red > 100)
        & (green > 80)
        & (blue < 70)
    )
    mask[:int(height * 0.05), :] = False
    mask[int(height * 0.72):, :] = False
    mask[:, :int(width * 0.04)] = False
    mask[:, int(width * 0.78):] = False
    # The fixed selected-target frame has the same gold fill but is not a
    # world-space bearing.
    mask[:int(height * 0.16), int(width * 0.62):] = False
    ys, xs = np.nonzero(mask)
    points = set(zip(xs.tolist(), ys.tolist()))
    matches: list[tuple[int, int, int]] = []
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
        if len(component) < 180:
            continue
        component_xs, component_ys = [p[0] for p in component], [p[1] for p in component]
        box_width = max(component_xs) - min(component_xs) + 1
        box_height = max(component_ys) - min(component_ys) + 1
        if 80 <= box_width <= 135 and 5 <= box_height <= 18:
            matches.append((len(component), round((min(component_xs) + max(component_xs)) / 2),
                            round((min(component_ys) + max(component_ys)) / 2)))
    if not matches:
        return None
    _, center_x, center_y = max(matches)
    return center_x, center_y


def window_pixel_to_client_ratios(pid: int, x: int, y: int, window_width: int, window_height: int) -> tuple[float, float]:
    user32 = ctypes.windll.user32
    hwnd = _window_for_pid(pid)
    window_rect, client_rect = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(window_rect))
    user32.GetClientRect(hwnd, ctypes.byref(client_rect))
    client_origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(client_origin))
    client_x = x - (client_origin.x - window_rect.left)
    client_y = y - (client_origin.y - window_rect.top)
    client_width, client_height = client_rect.right, client_rect.bottom
    return max(0.0, min(1.0, client_x / client_width)), max(0.0, min(1.0, 1.0 - client_y / client_height))


def write_state_atomic(path: Path, state: dict) -> None:
    write_json_replace(path, state, ensure_ascii=False)


def _text(value: str) -> Optional[str]:
    return None if value in ("", "?") else value


def _integer(value: str) -> Optional[int]:
    try: return int(value)
    except (TypeError, ValueError): return None


def _number(value: str, fallback: float = 0) -> float:
    try: return float(value)
    except (TypeError, ValueError): return fallback


def _window_for_pid(pid: int) -> Optional[int]:
    user32 = ctypes.windll.user32
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _):
        current = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(current))
        if current.value == pid and user32.IsWindowVisible(hwnd):
            found.append(int(hwnd)); return False
        return True
    user32.EnumWindows(callback, 0)
    return found[0] if found else None


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


# Backward-compatible HWND-named entry point used by the passive 3D probe.
def capture_hwnd_bgra(hwnd: int, ensure_foreground: bool = False) -> tuple[bytes, int, int]:
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    if not hwnd:
        raise RuntimeError("invalid window handle")
    if ensure_foreground and user32.GetForegroundWindow() != hwnd:
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.025)
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError()
    width, height = rect.right - rect.left, rect.bottom - rect.top
    screen_dc = user32.GetDC(0)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    old = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc, rect.left, rect.top, 0x00CC0020):
            raise ctypes.WinError()
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        raw = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(memory_dc, bitmap, 0, height, raw, ctypes.byref(info), 0):
            raise ctypes.WinError()
        return raw.raw, width, height
    finally:
        gdi32.SelectObject(memory_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)
