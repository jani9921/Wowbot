from wowbot.vision.tooltip import tooltip_observation


def test_tooltip_observation_preserves_addon_frame_and_links_only_near_subject():
    payload = {"mouseover": {"guid": "Creature-1", "name": "Lady Jaina Proudmoore",
                              "tooltip_text": "Lady Jaina Proudmoore ~ Level 10",
                              "tooltip_data": {"unit_guid": "Creature-1", "raw_type": 2}},
               "cursor_position": {"nx": .51, "ny": .62}}
    candidates = [{"track_id": "WORLD3D:7", "source": "WORLD3D",
                   "detector_kind": "unknown_subject_candidate", "x": .50, "y": .60,
                   "latest_detection_frame_id": "capture:7"}]

    observed = tooltip_observation(payload, frame_id="addon:12", observed_at=4.2,
                                   candidates=candidates)

    assert observed["frame_id"] == "addon:12"
    assert observed["parsed_name"] == "Lady Jaina Proudmoore"
    assert observed["confidence"] == 1.0
    assert observed["candidate_track_id"] == "WORLD3D:7"
    assert observed["candidate_association"] == "SPATIAL_HYPOTHESIS"
    assert observed["fact"] is False


def test_tooltip_observation_never_links_a_distant_visual_candidate():
    payload = {"mouseover": {"tooltip_text": "Some NPC"}, "cursor_position": {"nx": .1, "ny": .1}}
    candidates = [{"track_id": "WORLD3D:far", "source": "WORLD3D",
                   "detector_kind": "unknown_subject_candidate", "x": .9, "y": .9}]

    observed = tooltip_observation(payload, frame_id="addon:13", observed_at=4.3,
                                   candidates=candidates)

    assert observed["visible"] is True
    assert "candidate_track_id" not in observed
