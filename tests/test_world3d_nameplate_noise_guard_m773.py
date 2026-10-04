import numpy as np

from wowbot.vision.world3d.candidates import detect_world_candidates
from wowbot.vision.world3d.models import PixelRect, WorldSceneROI


def test_nameplate_like_bar_without_subject_body_is_not_promoted():
    width, height = 300, 240
    image = np.zeros((height, width, 4), dtype=np.uint8)
    # A yellow-ish terrain/UI strip that resembles a nameplate but has no
    # nearby subject-shaped body component.
    image[104:109, 135:205, :3] = (30, 205, 215)  # BGR -> yellow-ish
    roi = WorldSceneROI(rect=PixelRect(0, 0, width, height))
    found = detect_world_candidates(image.tobytes(), width, height, roi)
    assert not any(c.kind == "mob_candidate" for c in found)
    assert not any(c.kind == "npc_candidate" for c in found)
    assert not any(c.kind == "player_candidate" for c in found)
