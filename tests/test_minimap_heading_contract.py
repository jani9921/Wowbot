import numpy as np

from wowbot.vision.adapters.minimap import detect_minimap
from wowbot.vision.minimap_geometry import MinimapGeometry


def test_minimap_heading_is_separate_telemetry_evidence_not_a_marker_role():
    pixels = np.zeros((100, 100, 4), dtype=np.uint8)
    pixels[:, :, 3] = 255
    observed = detect_minimap(pixels.tobytes(), 100, 100,
                               geometry=MinimapGeometry(.5, .5, .35), heading_degrees=725.)

    assert observed.heading is not None
    assert observed.heading.degrees == 5.
    assert observed.heading.confidence == .92
    assert all(marker.marker_type == "unknown_minimap_marker" for marker in observed.markers)
