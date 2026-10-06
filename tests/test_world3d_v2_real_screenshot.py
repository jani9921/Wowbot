from pathlib import Path

import pytest
from PIL import Image

from wowbot.agent.visual_tracks import VisualTrackManager
from wowbot.vision.world3d.scene import build_scene_roi
from wowbot.vision.world3d.v2 import World3DPerceptionV2


SCREENSHOT = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Screenshots\WoWScrnShot_090826_101519.jpg")
FALSE_POSITIVE_REFERENCE = Path(r"C:\Users\benei\Downloads\image-1789125653376.png")


@pytest.mark.skipif(not SCREENSHOT.exists(), reason="live reference screenshot is not installed")
def test_real_exiles_reach_frame_produces_unknown_symbol_subject_relation():
    image = Image.open(SCREENSHOT).convert("RGBA")
    width, height = image.size
    raw = image.tobytes("raw", "BGRA")
    detected = World3DPerceptionV2().process(raw, width, height, build_scene_roi(width, height))
    assert any(item.kind == "unknown_symbol_candidate" for item in detected)
    assert any(item.kind == "unknown_subject_candidate" for item in detected)
    assert all(item.class_name is None for item in detected)

    manager = VisualTrackManager()
    payload = [{"kind": item.kind, "detector_kind": item.kind, "semantic_type": "UNKNOWN",
                "confidence": item.confidence,
                "x": (item.rect.left+item.rect.right)/2/width,
                "y": 1-(item.rect.top+item.rect.bottom)/2/height,
                "bbox": {"left": item.rect.left, "top": item.rect.top,
                         "right": item.rect.right, "bottom": item.rect.bottom},
                "appearance": dict(item.appearance),
                "candidate_labels": list(item.candidate_labels)} for item in detected]
    tracked = []
    for observed_at in (1., 2., 3.):
        tracked = manager.update("WORLD3D", payload, observed_at)
    subjects = [item for item in tracked if "subject" in item["detector_kind"]]
    assert any(any(relation["type"] == "ABOVE" for relation in item.get("visual_relations", ()))
               for item in subjects)
    assert all(item["semantic_type"] == "UNKNOWN" for item in tracked)


@pytest.mark.skipif(not FALSE_POSITIVE_REFERENCE.exists(), reason="false-positive reference is not installed")
def test_real_replay_frame_has_bounded_candidate_population():
    image = Image.open(FALSE_POSITIVE_REFERENCE).convert("RGBA")
    detected = World3DPerceptionV2().process(
        image.tobytes("raw", "BGRA"), image.width, image.height,
        build_scene_roi(image.width, image.height))
    assert len(detected) <= 20
    assert sum(item.kind == "visual_candidate" for item in detected) <= 2
    assert sum(item.kind == "unknown_symbol_candidate" for item in detected) <= 4
    assert all(item.class_name is None for item in detected)
