import json
from pathlib import Path

import pytest

from adapters.pixel_bridge import (HEADER, _GRID_CACHE, decode_payload_from_bgra,
                                   pixel_strip_diagnostics, pixel_strip_profile)


ROOT = Path(__file__).resolve().parents[1]
PROFILE_FILE = ROOT / "config" / "pixel_strip_profiles.json"
COLORS = {
    0: (5, 5, 5, 255),       # BGRA black
    1: (5, 5, 255, 255),     # red
    2: (5, 255, 5, 255),     # green
    3: (255, 5, 5, 255),     # blue
}


def base4(value):
    return ((value // 64) % 4, (value // 16) % 4, (value // 4) % 4, value % 4)


def encoded_cells(payload):
    raw = payload.encode("utf-8")
    checksum = sum(raw) % 256
    values = list(HEADER) + list(base4(len(raw) // 256)) + list(base4(len(raw) % 256))
    for byte in raw:
        values.extend(base4(byte))
    values.extend(base4(checksum))
    return values


def frame(width, height, payload, *, left=12, top=12, pitch=4):
    result = bytearray(width * height * 4)
    for index, value in enumerate(encoded_cells(payload)):
        column, row = index % 128, index // 128
        x, y = round(left + column * pitch), round(top + row * pitch)
        blue, green, red, alpha = COLORS[value]
        # Solid cells model the addon texture and permit any point within a cell.
        cell = max(1, int(pitch))
        for yy in range(y, min(height, y + cell)):
            for xx in range(x, min(width, x + cell)):
                offset = (yy * width + xx) * 4
                result[offset:offset + 4] = bytes((blue, green, red, alpha))
    return bytes(result)


def test_profile_file_covers_standard_resolutions_from_vga_through_4k():
    profiles = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))["profiles"]
    dimensions = {(item["width"], item["height"]) for item in profiles}
    required = {
        (640, 480), (800, 600), (1024, 768), (1280, 720), (1280, 1024),
        (1366, 768), (1440, 900), (1536, 864), (1600, 900), (1680, 1050),
        (1920, 1080), (1920, 1200), (2560, 1080), (2560, 1440),
        (3440, 1440), (3840, 2160), (4096, 2160),
    }
    assert required <= dimensions


@pytest.mark.parametrize("width,height", [
    (640, 480), (1024, 768), (1600, 900), (1920, 1080), (3840, 2160),
])
def test_new_fixed_physical_pitch_decodes_at_representative_resolutions(width, height):
    _GRID_CACHE.clear()
    payload = f"AIPC5|resolution|{width}x{height}"
    assert decode_payload_from_bgra(frame(width, height, payload), width, height) == payload
    diagnostic = pixel_strip_diagnostics()
    assert diagnostic["status"] == "decoded"
    assert diagnostic["profile"]


def test_legacy_ui_scaled_pitch_remains_decodable():
    _GRID_CACHE.clear()
    payload = "AIPC5|legacy-scaled"
    raw = frame(1600, 900, payload, pitch=2.5)
    assert decode_payload_from_bgra(raw, 1600, 900) == payload


def test_nonstandard_window_size_uses_scaled_nearest_profile():
    profile = pixel_strip_profile(1584, 861)
    assert profile["name"].startswith("scaled:")
    assert profile["width"] == 1584 and profile["height"] == 861


def test_resolution_specific_grid_cache_is_revalidated():
    _GRID_CACHE.clear()
    first = "AIPC5|first"
    assert decode_payload_from_bgra(frame(800, 600, first), 800, 600) == first
    assert (800, 600) in _GRID_CACHE
    second = "AIPC5|moved"
    assert decode_payload_from_bgra(frame(800, 600, second, left=20, top=20), 800, 600) == second
    assert _GRID_CACHE[(800, 600)][:2] == (20, 20)


def test_adaptive_geometry_finds_strip_outside_profile_origin():
    _GRID_CACHE.clear()
    payload = "AIPC5|ui-scale-70|adaptive"
    raw = frame(1024, 768, payload, left=401, top=503, pitch=3)
    assert decode_payload_from_bgra(raw, 1024, 768) == payload
    diagnostic = pixel_strip_diagnostics()
    assert diagnostic["path"] == "adaptive_header_geometry"
    assert diagnostic["adaptive_header_candidates"] > 0


def test_missing_strip_diagnostic_distinguishes_absent_header():
    _GRID_CACHE.clear()
    assert decode_payload_from_bgra(bytes(640*480*4), 640, 480) is None
    diagnostic = pixel_strip_diagnostics()
    assert diagnostic["status"] == "not_visible"
    assert diagnostic["adaptive_header_candidates"] == 0


def test_torn_frame_at_known_strip_keeps_geometry_without_rediscovery():
    """Live 2026-09-30: rediscovery on every torn frame pinned the sensor thread."""
    _GRID_CACHE.clear()
    payload = "AIPC5|" + "x" * 300
    good = frame(892, 502, payload)
    assert decode_payload_from_bgra(good, 892, 502) == payload
    torn = bytearray(good)
    row = 12 * 892 * 4
    torn[row + 160 * 4:row + 480 * 4] = bytes([128]) * (320 * 4)  # grey body cells, header intact
    assert decode_payload_from_bgra(bytes(torn), 892, 502) is None
    assert pixel_strip_diagnostics()["status"] == "torn_frame"
    assert (892, 502) in _GRID_CACHE
    assert decode_payload_from_bgra(good, 892, 502) == payload
    assert pixel_strip_diagnostics()["cache_hit"] is True
