from __future__ import annotations

import numpy as np

from wowbot.agent.active_perception import ActivePerception
from wowbot.agent.models import Goal, Observation
from wowbot.agent.world import WorldModel
from wowbot.vision.entity_memory import EntityMemory
from wowbot.vision.visual_signature import build_visual_signature
from wowbot.vision.world3d.models import PixelRect, WorldCandidate, WorldSceneROI
from wowbot.vision.world3d.tracking import WorldCandidateTracker
from wowbot.vision.world3d.v2 import (
    World3DPerceptionV2, _annotate_self_avatar_attention,
    _same_vertical_attention_region,
)


def _frame(width=320, height=240):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    for y in range(height):
        image[y, :, :3] = 35 + y // 7
    return image


def _world():
    world = WorldModel()
    world.ingest(Observation.create({"session_id": "s", "frame_id": "f", "timestamp": 1,
        "map_id": 1409, "position": {"x": .5, "y": .5}, "orientation": 0,
        "player_present": True}, 1))
    return world


def test_neutral_gray_subject_proposal_does_not_need_nameplate_or_semantic_color():
    image = _frame()
    image[75:175, 140:180, :3] = 150
    image[85:165, 148:172, :3] = 65
    found = World3DPerceptionV2().process(
        image.tobytes(), 320, 240, WorldSceneROI(PixelRect(0, 0, 320, 240)))
    subjects = [item for item in found if item.kind == "unknown_subject_candidate"]
    assert subjects
    assert any("generic_subject_like" in item.candidate_labels for item in subjects)
    assert all(item.class_name is None and item.relation is None for item in subjects)
    assert all(item.appearance.get("proposal_semantics") == "UNKNOWN" for item in subjects)


def test_camera_translation_is_removed_before_residual_motion_evidence():
    rng = np.random.default_rng(7)
    small = rng.integers(20, 210, (60, 80), dtype=np.uint8)
    first = np.repeat(np.repeat(small, 4, 0), 4, 1)
    image = np.empty((240, 320, 4), dtype=np.uint8)
    image[:, :, :3] = first[:, :, None]
    image[:, :, 3] = 255
    shifted = np.zeros_like(image)
    shifted[:, 8:] = image[:, :-8]
    shifted[:, :8] = image[:, :8]
    detector = World3DPerceptionV2()
    roi = WorldSceneROI(PixelRect(0, 0, 320, 240))
    detector.process(image.tobytes(), 320, 240, roi)
    detector.process(shifted.tobytes(), 320, 240, roi)
    motion = detector.last_diagnostics["camera_motion_px"]
    assert abs(motion["dx"] - 8) <= 4 and abs(motion["dy"]) <= 4
    assert motion["confidence"] > .5


def test_camera_aware_tracker_keeps_subject_identity_across_pan():
    from wowbot.vision.world3d.models import WorldCandidate
    tracker = WorldCandidateTracker(max_distance=20)
    first = WorldCandidate("unknown_subject_candidate", PixelRect(100, 80, 140, 160), .7,
                           appearance={"foreground_contrast": .7})
    second = WorldCandidate("unknown_subject_candidate", PixelRect(132, 80, 172, 160), .7,
                            appearance={"foreground_contrast": .69, "camera_motion_dx": 32})
    a = tracker.update((first,))[0]
    b = tracker.update((second,))[0]
    assert a.track_id == b.track_id
    assert b.appearance["track_association"] == "position+camera+motion+scale+appearance"


def test_vertical_sliding_windows_for_one_subject_are_deduplicated():
    # These are the typical partially-overlapping generic windows created over
    # one upright body.  They are UNKNOWN attention proposals, not entities.
    torso = PixelRect(480, 188, 512, 252)
    upper = PixelRect(464, 156, 496, 220)
    assert _same_vertical_attention_region(torso, upper)


def test_side_by_side_subject_windows_remain_distinct():
    # Touching/nearby units must not be merged merely because they are close.
    left = PixelRect(480, 188, 512, 252)
    right = PixelRect(512, 188, 544, 252)
    assert not _same_vertical_attention_region(left, right)


def test_self_avatar_region_is_post_detection_attention_metadata_only():
    scene = WorldSceneROI(
        PixelRect(0, 0, 1000, 700),
        self_avatar_rect=PixelRect(400, 400, 600, 700),
    )
    own_view = WorldCandidate(
        "unknown_subject_candidate", PixelRect(450, 450, 550, 700), .8,
        appearance={"proposal_semantics": "UNKNOWN"},
    )
    annotated = _annotate_self_avatar_attention(own_view, scene)
    assert annotated.kind == "unknown_subject_candidate"
    assert annotated.appearance["self_avatar_suppression_hint"] is True
    assert annotated.appearance["self_avatar_evidence_role"] == "ATTENTION_SUPPRESS_ONLY"


def test_nearby_npc_above_avatar_bottom_is_not_marked_as_self():
    scene = WorldSceneROI(
        PixelRect(0, 0, 1000, 700),
        self_avatar_rect=PixelRect(400, 400, 600, 700),
    )
    # A nearby subject can overlap most of the avatar band, but unlike our own
    # third-person avatar its feet/box are not pinned to the screen ROI bottom.
    nearby_npc = WorldCandidate(
        "unknown_subject_candidate", PixelRect(450, 420, 550, 620), .8,
        appearance={"proposal_semantics": "UNKNOWN"},
    )
    annotated = _annotate_self_avatar_attention(nearby_npc, scene)
    assert annotated.appearance["self_avatar_region_overlap"] == 1.0
    assert annotated.appearance["self_avatar_suppression_hint"] is False


def test_information_gain_prefers_subject_over_static_scenery():
    active = ActivePerception()
    common = {"source": "WORLD3D", "semantic_type": "UNKNOWN", "stable_frames": 4,
              "confidence": .75, "x": .5, "y": .5}
    subject = {**common, "track_id": "subject", "detector_kind": "unknown_subject_candidate",
               "appearance": {"residual_motion": .7, "body_geometry": .8,
                              "foreground_contrast": .8, "static_scene_score": .05},
               "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}]}
    scenery = {**common, "track_id": "scenery", "detector_kind": "unknown_scene_candidate",
               "appearance": {"residual_motion": .01, "body_geometry": .05,
                              "foreground_contrast": .7, "static_scene_score": .95}}
    a = active.evaluate(subject, _world(), Goal.parse("Questelj", 1))
    b = active.evaluate(scenery, _world(), Goal.parse("Questelj", 1))
    assert a["utility"] > b["utility"]
    assert a["world3d_features"]["overhead_relation"] is True


def test_complete_visual_signature_can_reidentify_across_small_crop_change(tmp_path):
    memory = EntityMemory(tmp_path / "entities.sqlite3")
    image = _frame(100, 100)
    image[20:65, 30:55, :3] = (80, 130, 175)
    raw = image.tobytes()
    a = build_visual_signature(raw, 100, 100, PixelRect(30, 20, 55, 65))
    b = build_visual_signature(raw, 100, 100, PixelRect(29, 19, 56, 66))
    assert a["signature_id"] != b["signature_id"]
    key = memory.record_mouseover({"npc_id": 42, "unit_type": "NPC"}, map_id=1409,
                                  map_x=None, map_y=None, zone="Exile", observed_at=1)
    for at in (2, 3, 4):
        memory.associate_visual(key, a, at)
    matches = memory.recognize_visual(b)
    assert matches and matches[0]["identity_key"] == "npc:42"
    assert matches[0]["match_method"] == "APPROXIMATE_VISUAL_REIDENTIFICATION"
    assert matches[0]["status"] == "CANDIDATE"
