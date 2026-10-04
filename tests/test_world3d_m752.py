import numpy as np

from wowbot.vision.world3d.candidates import detect_world_candidates
from wowbot.vision.world3d.models import PixelRect, WorldSceneROI
from wowbot.vision.world3d.scene import WorldSceneProfile, build_scene_roi


def test_ui_exclusion_removes_lower_left_hud_region():
    width, height = 953, 657
    roi = build_scene_roi(width, height)
    assert roi.rect.top == 92
    assert roi.rect.bottom < 500
    assert any(r.right >= 220 and r.top >= 340 for r in roi.excluded_rects)


def test_green_nameplate_plus_subject_stays_unknown():
    width, height = 260, 220
    image = np.zeros((height, width, 4), dtype=np.uint8)
    # Body-like colourful block.
    image[110:145, 100:120, :3] = (70, 140, 170)
    # Small green nameplate directly above.
    image[94:99, 100:120, :3] = (20, 220, 20)
    roi = WorldSceneROI(rect=PixelRect(0, 0, width, height))
    found = detect_world_candidates(image.tobytes(), width, height, roi)
    assert any(c.kind == "unknown_subject_candidate" for c in found)
    assert not any(c.kind in {"npc_candidate", "mob_candidate", "player_candidate"} for c in found)


def test_red_nameplate_plus_subject_stays_unknown():
    width, height = 260, 220
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[110:145, 140:160, :3] = (80, 120, 170)
    image[94:99, 140:160, :3] = (20, 20, 220)
    roi = WorldSceneROI(rect=PixelRect(0, 0, width, height))
    found = detect_world_candidates(image.tobytes(), width, height, roi)
    assert any(c.kind == "unknown_subject_candidate" for c in found)


def test_excluded_ui_candidate_is_not_emitted():
    width, height = 320, 260
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[200:220, 30:120, :3] = (210, 70, 20)
    roi = WorldSceneROI(
        rect=PixelRect(0, 0, width, height),
        excluded_rects=(PixelRect(0, 180, 150, 260),),
    )
    assert detect_world_candidates(image.tobytes(), width, height, roi) == ()


def test_low_saturation_mass_is_unknown_scene_candidate():
    width, height = 220, 180
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[70:125, 70:135, :3] = (125, 130, 135)
    roi = WorldSceneROI(rect=PixelRect(0, 0, width, height))
    found = detect_world_candidates(image.tobytes(), width, height, roi)
    assert any(c.kind == "unknown_scene_candidate" for c in found)
