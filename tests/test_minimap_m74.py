from __future__ import annotations

import numpy as np

from wowbot.vision.adapters.minimap import detect_minimap
from wowbot.vision.minimap_geometry import MinimapGeometry


def bgra(width: int, height: int) -> np.ndarray:
    return np.zeros((height, width, 4), dtype=np.uint8)


def bytes_of(image: np.ndarray) -> bytes:
    return image.tobytes()


def test_minimap_geometry_defaults_to_known_retail_center() -> None:
    geometry = MinimapGeometry()
    center = geometry.center(300, 200)
    assert center.x == 276
    assert center.y == 35
    assert abs(geometry.radius(300, 200) - 17.6) < 1e-9


def test_minimap_reports_relative_target_geometry() -> None:
    image = bgra(300, 200)
    image[31:36, 264:269, :3] = (0, 30, 230)
    obs = detect_minimap(bytes_of(image), 300, 200, observed_at=10.0)
    target = next(m for m in obs.markers if "selected_target_like" in m.candidate_labels)
    dx, dy = obs.marker_relative(target)
    nx, ny = obs.marker_normalized(target)
    assert dx < 0
    assert dy < 0
    assert obs.marker_distance_px(target) > 0
    assert nx < 0 and ny < 0


def test_minimap_observation_does_not_execute_any_input() -> None:
    image = bgra(300, 200)
    obs = detect_minimap(bytes_of(image), 300, 200)
    assert obs.markers == ()
    assert obs.features == ()


def test_marker_observation_preserves_semantic_hints() -> None:
    from wowbot.vision.models import MapPoint, MarkerObservation
    marker = MarkerObservation("target", MapPoint(1, 2), 0.9, marker_color="yellow", relation="neutral")
    assert marker.marker_color == "yellow"
    assert marker.relation == "neutral"
