import numpy as np

from wowbot.vision.world3d.nameplate import attach_nameplate_observations


def frame():
    image = np.zeros((120, 200, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    # Main red/gold-like plate and a secondary cyan cast-bar-like strip.
    image[20:26, 75:135, :3] = (25, 35, 220)
    image[29:34, 82:128, :3] = (220, 180, 20)
    return image.tobytes(), 200, 120


def track():
    return {"track_id": "WORLD3D:1", "confidence": .8, "source_confidence": .8,
            "semantic_type": "UNKNOWN", "candidate_labels": ["possible_nameplate_like"],
            "appearance": {"hue_family": "red", "nameplate_bbox": {
                "left": 75, "top": 20, "right": 135, "bottom": 26}},
            "screen_center": {"x": .5, "y": .5,
                              "coordinate_space": "WORLD_VIEWPORT_NORMALIZED"},
            "information_value": .4, "type_beliefs": [], "role_beliefs": [],
            "identity_belief": {"state": "UNKNOWN", "fact": False}}


def test_nameplate_is_first_class_evidence_but_never_identity_or_hostility_fact():
    result = attach_nameplate_observations(frame(), [track()])[0]
    observation = result["nameplate_observation"]

    assert observation["associated_track_id"] == "WORLD3D:1"
    assert observation["relation_color_belief"]["label"] == "RED"
    assert observation["relation_color_belief"]["fact"] is False
    assert observation["health_fraction_belief"]["value"] is not None
    assert observation["cast_state"]["state"] == "CAST_BAR_LIKE"
    assert observation["identity_authority"] is False
    assert result["semantic_type"] == "UNKNOWN"


def test_soft_target_only_increases_attention_prior():
    original = track()
    result = attach_nameplate_observations(frame(), [original], soft_targets=[{
        "track_id": "WORLD3D:1", "selected": True, "confidence": .9,
        "candidate_type": "UNKNOWN_UNIT",
    }])[0]

    assert result["soft_target_evidence"]["selected_or_highlighted"] is True
    assert result["soft_target_evidence"]["identity_authority"] is False
    assert result["information_value"] > original["information_value"]
    assert result["identity_belief"]["state"] == "UNKNOWN"
    assert result["nameplate_observation"]["selected_state"]["state"] == "SELECTED_LIKE"


def test_missing_nameplate_does_not_remove_subject_track():
    subject = track()
    subject["candidate_labels"] = []
    subject["appearance"] = {}
    result = attach_nameplate_observations(frame(), [subject])

    assert len(result) == 1
    assert "nameplate_observation" not in result[0]
    assert result[0]["semantic_type"] == "UNKNOWN"

