from __future__ import annotations

import numpy as np

from wowbot.vision.adapters.minimap import detect_minimap


def blank(w=300, h=200):
    return np.zeros((h, w, 4), dtype=np.uint8)


def test_selected_target_with_light_border_is_target():
    img = blank()
    # Compact green target core at the expected minimap location.
    img[31:35, 277:281, :3] = (0, 200, 235)  # BGRA -> yellow-ish core
    # White/light halo around the compact core.
    img[29:31, 276:282, :3] = (235, 235, 235)
    img[35:37, 276:282, :3] = (235, 235, 235)
    img[30:36, 275:277, :3] = (235, 235, 235)
    img[30:36, 281:283, :3] = (235, 235, 235)
    obs = detect_minimap(img.tobytes(), 300, 200, observed_at=1.0)
    assert any("selected_target_like" in m.candidate_labels for m in obs.markers)
    assert all(m.marker_type == "unknown_minimap_marker" for m in obs.markers)


def test_plain_yellow_ring_is_quest_related_not_target():
    img = blank()
    cx, cy = 276, 35
    yy, xx = np.ogrid[:200, :300]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    ring = (d2 >= 9**2) & (d2 <= 11**2)
    img[ring, :3] = (0, 165, 205)
    obs = detect_minimap(img.tobytes(), 300, 200, observed_at=1.0)
    assert any("ring_like" in m.candidate_labels for m in obs.markers)
    assert not any("selected_target_like" in m.candidate_labels for m in obs.markers)


def test_plain_yellow_ring_does_not_create_quest_glyph():
    img = blank()
    cx, cy = 276, 35
    yy, xx = np.ogrid[:200, :300]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    ring = (d2 >= 9**2) & (d2 <= 11**2)
    img[ring, :3] = (0, 165, 205)
    obs = detect_minimap(img.tobytes(), 300, 200, observed_at=1.0)
    assert not any(m.marker_type in {"quest_giver", "quest_turn_in"} for m in obs.markers)
