from __future__ import annotations

import numpy as np

from wowbot.vision.adapters.minimap import _detect_quest_direction_arrow
from wowbot.vision.models import MapPoint


def blank(w=196, h=182):
    return np.zeros((h, w, 4), dtype=np.uint8)


def test_gold_direction_arrow_reference_shape_is_reported():
    img = blank()
    pts = [(82,33),(83,33),(84,33),(82,34),(84,34),(85,34),(82,35),(83,35),(84,35),(85,35),(86,35),
           (81,36),(82,36),(83,36),(85,36),(86,36),(87,36),(81,37),(82,37),(83,37),(85,37),(86,37),(87,37),(88,37),
           (81,38),(82,38),(83,38),(86,38),(87,38),(88,38),(81,39),(82,39),(83,39),(84,39),(85,39),(86,39),
           (80,40),(81,40),(82,40),(85,40),(86,40),(80,41),(81,41),(85,41),(86,41),(87,41),(80,42),(85,42),(86,42),(87,42),(88,42),(89,42),
           (85,43),(86,43),(89,43),(90,43),(84,44),(85,44),(84,45)]
    for x, y in pts:
        img[y, x, :3] = (0, 165, 205)
    marker = _detect_quest_direction_arrow(img, 196, 182, MapPoint(98, 91), 75.0)
    assert marker is not None
    assert marker.marker_type == "unknown_minimap_marker"
    assert marker.candidate_labels == ("gold_direction_like",)
    assert marker.bearing_degrees is not None
    assert 330 <= marker.bearing_degrees <= 360


def test_target_like_center_marker_does_not_create_direction_arrow():
    img = blank()
    img[89:94, 96:101, :3] = (0, 165, 205)
    marker = _detect_quest_direction_arrow(img, 196, 182, MapPoint(98, 91), 75.0)
    assert marker is None
