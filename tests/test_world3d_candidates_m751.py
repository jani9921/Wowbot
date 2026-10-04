import numpy as np

from wowbot.vision.world3d.candidates import detect_world_candidates
from wowbot.vision.world3d.models import PixelRect, WorldSceneROI


def test_candidate_detector_finds_salient_component():
    width, height = 160, 120
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[50:62, 70:82, :3] = (210, 70, 20)  # BGR colourful block
    roi = WorldSceneROI(rect=PixelRect(0, 0, width, height))
    found = detect_world_candidates(image.tobytes(), width, height, roi)
    assert found
    assert found[0].kind in {"visual_candidate", "unknown_symbol_candidate", "unknown_object_candidate", "unknown_scene_candidate"}


def test_candidate_detector_does_not_classify_full_dark_frame():
    width, height = 160, 120
    image = np.zeros((height, width, 4), dtype=np.uint8)
    roi = WorldSceneROI(rect=PixelRect(0, 0, width, height))
    assert detect_world_candidates(image.tobytes(), width, height, roi) == ()
