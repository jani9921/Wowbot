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
# Moved out 2026-10-05; re-exported so every existing import keeps working.
from .pixel_detectors import (  # noqa: F401
    detect_campfire, detect_enemy_nameplate, detect_friendly_nameplate, detect_quest_marker,
)
from .pixel_payload import _integer, _number, _text, payload_to_state  # noqa: F401


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
