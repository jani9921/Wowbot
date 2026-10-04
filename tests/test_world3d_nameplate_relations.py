import numpy as np
import pytest

from wowbot.vision.world3d.candidates import detect_world_candidates
from wowbot.vision.world3d.models import PixelRect, WorldSceneROI


@pytest.mark.parametrize("plate_bgr", [(20, 220, 220), (170, 40, 220)])
def test_nameplate_is_secondary_appearance_evidence_only(plate_bgr):
    image = np.zeros((220, 280, 4), dtype=np.uint8)
    image[110:145, 120:150, :3] = (80, 120, 160)
    image[94:99, 125:145, :3] = plate_bgr
    found = detect_world_candidates(image.tobytes(), 280, 220,
                                    WorldSceneROI(PixelRect(0, 0, 280, 220)))
    subjects = [c for c in found if c.kind == "unknown_subject_candidate"]
    assert subjects
    assert all(c.relation is None for c in subjects)


def test_overhead_cue_without_a_segmented_body_makes_unknown_subject_probe():
    image = np.zeros((220, 280, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    # Yellow horizontal cue, deliberately with no foreground mass below it.
    # It is an inspection region, never an entity/role classification.
    image[94:99, 125:145, :3] = (20, 220, 220)
    found = detect_world_candidates(image.tobytes(), 280, 220,
                                    WorldSceneROI(PixelRect(0, 0, 280, 220)))
    probes = [c for c in found if c.kind == "unknown_subject_probe"]
    assert probes
    assert all(c.class_name is None and c.relation is None for c in probes)
    assert all(c.appearance.get("proposal_semantics") == "UNKNOWN" for c in probes)
