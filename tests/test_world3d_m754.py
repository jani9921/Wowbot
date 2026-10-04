import numpy as np
import pytest

from wowbot.vision.world3d.candidates import detect_world_candidates
from wowbot.vision.world3d.models import PixelRect, WorldSceneROI


def _scene_with_plate(plate_bgr):
    image = np.zeros((220, 300, 4), dtype=np.uint8)
    image[110:145, 120:160, :3] = (80, 120, 160)
    image[94:99, 127:153, :3] = plate_bgr
    return image, WorldSceneROI(rect=PixelRect(0, 0, 300, 220))


@pytest.mark.parametrize("plate_bgr", [
    (20, 220, 220), (20, 20, 220), (20, 220, 20),
    (186, 140, 245), (10, 125, 255),
])
def test_nameplate_colour_never_assigns_entity_semantics(plate_bgr):
    image, roi = _scene_with_plate(plate_bgr)
    found = detect_world_candidates(image.tobytes(), 300, 220, roi)
    assert any(c.kind == "unknown_subject_candidate" for c in found)
    assert not any(c.kind in {"npc_candidate", "mob_candidate", "player_candidate"} for c in found)
    assert all(c.relation is None and c.class_name is None for c in found)
