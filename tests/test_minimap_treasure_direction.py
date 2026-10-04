from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from wowbot.vision.adapters.minimap import _detect_treasure_direction_arrow
from wowbot.vision.models import MapPoint


FIXTURE = Path(__file__).parents[1] / "samples" / "minimap_references_treasure_direction_arrow.png"


def test_treasure_direction_reference_detects_blue_gray_arrow():
    if not FIXTURE.exists():
        pytest.skip("optional minimap screenshot fixture is not included in this source archive")
    rgb = np.array(Image.open(FIXTURE).convert("RGB"))
    img = np.dstack((rgb[:, :, ::-1], np.full(rgb.shape[:2] + (1,), 255, dtype=np.uint8)))
    h, w = img.shape[:2]
    marker = _detect_treasure_direction_arrow(img, w, h, MapPoint(118, 104), 78.0)
    assert marker is not None
    assert marker.marker_type == "unknown_minimap_marker"
    assert marker.candidate_labels == ("blue_gray_direction_like",)
    assert marker.marker_color == "blue_gray"
    assert marker.symbol == "arrow"
    assert marker.bearing_degrees is not None
    assert 330 <= marker.bearing_degrees <= 360


def test_center_blue_gray_dot_does_not_create_treasure_direction_arrow():
    img = np.zeros((182, 196, 4), dtype=np.uint8)
    img[89:94, 96:101, :3] = (120, 135, 150)
    marker = _detect_treasure_direction_arrow(img, 196, 182, MapPoint(98, 91), 75.0)
    assert marker is None
