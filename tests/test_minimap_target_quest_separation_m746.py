from __future__ import annotations
import numpy as np
from wowbot.vision.adapters.minimap import detect_minimap


def test_yellow_target_dot_does_not_become_quest_glyph():
    # Synthetic minimap-sized frame with a single yellow target dot. The dot
    # must remain a target observation and must not create a !/? marker.
    img = np.zeros((200, 300, 4), dtype=np.uint8)
    # geometry default for 300x200 -> center ~276,35
    img[43:47, 284:288, :3] = (0, 210, 210)
    obs = detect_minimap(img.tobytes(), 300, 200, observed_at=1.0)
    assert any("selected_target_like" in m.candidate_labels for m in obs.markers)
    assert all(m.marker_type == "unknown_minimap_marker" for m in obs.markers)
