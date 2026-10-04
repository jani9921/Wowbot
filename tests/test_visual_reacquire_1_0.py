import pytest

from wowbot.agent.visual_approach import VisualApproachController, VisualApproachPhase


def test_visual_approach_uses_bounded_player_turn_reacquire_without_changing_identity():
    controller = VisualApproachController()
    state = {"target": {"guid": "npc", "dead": False},
             "visual_candidates": [{"track_id": "track", "x": .7, "y": .5,
                                     "confidence": .8, "source": "WORLD3D"}]}
    controller.start({"guid": "npc", "track_id": "track", "purpose": "INTERACT"},
                     state, "o1", 1.)
    missing = {"target": {"guid": "npc", "dead": False}, "visual_candidates": []}
    controller.observe(missing, "o2", 2.)
    assert controller.command(missing, "o2", 2.) == ()
    controller.observe(missing, "o3", 3.)
    assert controller.phase == VisualApproachPhase.OCCLUDED
    retry = controller.command(missing, "o3", 3.)
    assert retry and retry[0].binding == "INTERACTTARGET"
    # Only scan after authoritative selection has actually disappeared; a
    # A bounded player turn keeps the exact committed GUID unchanged.
    unselected = {**missing, "target": {}}
    controller.observe(unselected, "o4", 3.1)
    assert controller.command(unselected, "o4", 3.1) == ()
    controller.observe(unselected, "o5", 3.2)
    command = controller.command(unselected, "o5", 3.2)[0]
    assert command.kind == "BIND"
    assert command.binding in {"TURNLEFT", "TURNRIGHT"}
    assert controller.intent["guid"] == "npc"
    assert controller.snapshot()["reacquire_actions"] == 1


def test_selected_guid_rebinds_unambiguous_nearby_replacement_track():
    controller = VisualApproachController()
    target = {"guid": "npc", "dead": False}
    initial = {
        "target": target,
        "visual_candidates": [{
            "track_id": "WORLD3D:old", "x": .52, "y": .58,
            "confidence": .8, "source": "WORLD3D", "lifecycle": "ACTIVE",
            "detector_kind": "unknown_subject_candidate",
            "observed_at": 1.,
        }],
    }
    controller.start(
        {"guid": "npc", "track_id": "WORLD3D:old", "purpose": "INTERACT"},
        initial, "o1", 1.)

    refreshed = {
        "target": target,
        "visual_candidates": [{
            "track_id": "WORLD3D:new", "x": .54, "y": .58,
            "confidence": .82, "source": "WORLD3D", "lifecycle": "ACTIVE",
            "detector_kind": "unknown_subject_candidate",
            "observed_at": 1.1,
        }],
    }
    assessment = controller.observe(refreshed, "o2", 1.1)

    assert not assessment.terminal
    assert assessment.reason == "visual_target_tracked"
    assert controller.intent["track_id"] == "WORLD3D:new"
    assert controller.snapshot()["track_rebindings"] == 1


def test_selected_guid_does_not_rebind_ambiguous_adjacent_tracks():
    controller = VisualApproachController()
    target = {"guid": "npc", "dead": False}
    initial = {
        "target": target,
        "visual_candidates": [{
            "track_id": "WORLD3D:old", "x": .50, "y": .58,
            "confidence": .8, "source": "WORLD3D", "lifecycle": "ACTIVE",
            "detector_kind": "unknown_subject_candidate",
            "observed_at": 1.,
        }],
    }
    controller.start(
        {"guid": "npc", "track_id": "WORLD3D:old", "purpose": "INTERACT"},
        initial, "o1", 1.)
    ambiguous = {
        "target": target,
        "visual_candidates": [
            {"track_id": "WORLD3D:a", "x": .52, "y": .58,
             "confidence": .8, "source": "WORLD3D", "lifecycle": "ACTIVE",
             "detector_kind": "unknown_subject_candidate",
             "observed_at": 1.1},
            {"track_id": "WORLD3D:b", "x": .54, "y": .58,
             "confidence": .8, "source": "WORLD3D", "lifecycle": "ACTIVE",
             "detector_kind": "unknown_subject_candidate",
             "observed_at": 1.1},
        ],
    }

    assessment = controller.observe(ambiguous, "o2", 1.1)

    assert not assessment.terminal
    assert assessment.reason == "visual_track_temporarily_occluded"
    assert controller.intent["track_id"] == "WORLD3D:old"
    assert controller.snapshot()["track_rebindings"] == 0


def test_selected_guid_rehovers_supported_replacement_after_follow_camera_turn():
    """Live repro: Jaina moved across the frame while the old track stayed LOST."""
    controller = VisualApproachController()
    target = {"guid": "jaina", "dead": False}
    old = {
        "track_id": "WORLD3D:old", "x": .084, "y": .67,
        "bbox_height_fraction": .096, "confidence": .8,
        "source": "WORLD3D", "lifecycle": "ACTIVE",
        "detector_kind": "unknown_subject_candidate", "observed_at": 1.,
        "appearance": {"body_geometry": .92},
    }
    anchor = {
        "x": .084, "y": .67, "source": "CONFIRMED_MOUSEOVER_ANCHOR",
        "track_association": "CANDIDATE", "track_id": "WORLD3D:old",
    }
    start = {"target": target, "visual_candidates": [old],
             "mouseover_sample_time": 1.}
    controller.start({"guid": "jaina", "track_id": "WORLD3D:old",
                      "purpose": "INTERACT", "screen_position": anchor},
                     start, "o1", 1.)

    replacement = {
        "track_id": "WORLD3D:new", "x": .69, "y": .63,
        "bbox_height_fraction": .078, "confidence": .7,
        "source": "WORLD3D", "lifecycle": "ACTIVE",
        "detector_kind": "unknown_subject_candidate", "observed_at": 1.2,
        "appearance": {"body_geometry": .95},
        "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}],
        "visual_group": {"belief": "SUPPORTED"},
    }
    turned = {"target": target, "visual_candidates": [
        {**old, "lifecycle": "LOST_TEMPORARY", "observed_at": 1.1}, replacement],
        "mouseover_sample_time": 1.}
    occluded = controller.observe(turned, "o2", 1.2)
    assert occluded.reason == "visual_track_predicted_during_occlusion"

    hover = controller.command(turned, "o2", 1.2)
    assert hover and hover[0].kind == "HOVER"
    assert (hover[0].x, hover[0].y) == (.69, .63)

    confirmed = {**turned, "mouseover": target, "mouseover_sample_time": 1.3,
                 "cursor_sample_time": 1.3,
                 "cursor_position": {"nx": .69, "ny": .63}}
    assessment = controller.observe(confirmed, "o3", 1.3)

    assert not assessment.terminal
    assert controller.intent["track_id"] == "WORLD3D:new"
    assert controller.snapshot()["track_rebindings"] == 1
    assert controller.snapshot()["identity_reconfirmations"] == 1


def test_wrong_replacement_hover_is_rejected_without_reach_object_wait_fallback():
    controller = VisualApproachController()
    target = {"guid": "jaina", "dead": False}
    old = {"track_id": "old", "x": .08, "y": .67, "confidence": .8,
           "source": "WORLD3D", "lifecycle": "ACTIVE",
           "detector_kind": "unknown_subject_candidate", "observed_at": 1.}
    anchor = {"x": .08, "y": .67, "source": "CONFIRMED_MOUSEOVER_ANCHOR",
              "track_association": "CANDIDATE"}
    start = {"target": target, "visual_candidates": [old],
             "mouseover_sample_time": 1.}
    controller.start({"guid": "jaina", "track_id": "old", "purpose": "INTERACT",
                      "screen_position": anchor}, start, "o1", 1.)
    wrong = {"track_id": "kee-la", "x": .65, "y": .62, "confidence": .8,
             "source": "WORLD3D", "lifecycle": "ACTIVE",
             "detector_kind": "unknown_subject_candidate", "observed_at": 1.2,
             "appearance": {"body_geometry": .95},
             "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}]}
    changed = {"target": target, "visual_candidates": [
        {**old, "lifecycle": "LOST_TEMPORARY"}, wrong],
        "mouseover_sample_time": 1.}
    controller.observe(changed, "o2", 1.2)
    assert controller.command(changed, "o2", 1.2)[0].kind == "HOVER"

    contradicted = {**changed,
                    "mouseover": {"guid": "kee-la"},
                    "mouseover_sample_time": 1.3,
                    "cursor_sample_time": 1.3}
    assessment = controller.observe(contradicted, "o3", 1.3)

    assert not assessment.terminal
    assert assessment.reason == "replacement_visual_track_identity_not_confirmed"
    assert controller.intent["track_id"] == "old"
    assert controller.snapshot()["rejected_reacquire_tracks"] == 1


def test_visual_approach_never_drives_toward_stale_starting_pixel_after_motion():
    controller = VisualApproachController()
    anchor = {"x": .5, "y": .66, "source": "CONFIRMED_MOUSEOVER_ANCHOR",
              "player_world_snapshot": {"x": 0., "y": 0.},
              "orientation_snapshot": 0.}
    start = {"target": {"guid": "npc", "dead": False},
             "player_world_position": {"x": 0., "y": 0.}, "orientation": 0.,
             "visual_candidates": []}
    controller.start({"guid": "npc", "purpose": "INTERACT",
                      "screen_position": anchor, "range_block_started_at": 1.},
                     start, "o1", 1.)
    moved = {**start, "player_world_position": {"x": 1., "y": 0.}}
    assessment = controller.observe(moved, "o2", 1.2)
    assert assessment.reason == "visual_track_temporarily_occluded"
    assert controller.command(moved, "o2", 1.2) == ()


def test_visual_approach_periodically_probes_exact_selected_interaction_target():
    controller = VisualApproachController()
    controller.range_probe_enabled = True      # opt-in (AIPC_VA_RANGE_PROBE=1)
    state = {"target": {"guid": "npc", "dead": False},
             "visual_candidates": [{"track_id": "track", "x": .5, "y": .6,
                                     "confidence": .8, "source": "WORLD3D"}]}
    controller.start({"guid": "npc", "track_id": "track", "purpose": "INTERACT",
                      "range_block_started_at": 1.}, state, "o1", 1.)
    controller.observe(state, "o1a", 1.2)
    assert controller.command(state, "o1a", 1.2)[0].binding == "MOVEFORWARD"
    controller.observe(state, "o1b", 1.4)
    assert controller.command(state, "o1b", 1.4)[0].binding == "MOVEFORWARD"
    controller.observe(state, "o1c", 1.6)
    assert controller.command(state, "o1c", 1.6)[0].binding == "MOVEFORWARD"
    controller.observe(state, "o1d", 1.7)
    assert controller.command(state, "o1d", 1.7)[0].binding == "MOVEFORWARD"
    controller.observe(state, "o1e", 1.9)
    assert controller.command(state, "o1e", 1.9)[0].binding == "MOVEFORWARD"
    controller.observe(state, "o2", 2.3)
    command = controller.command(state, "o2", 2.3)[0]
    assert command.kind == "BIND"
    assert command.binding == "INTERACTTARGET"


def test_visual_servo_fuses_track_camera_and_telemetry_measurements():
    controller = VisualApproachController()
    state = {"target": {"guid": "npc", "dead": False},
             "monotonic_time": 10., "orientation": 1.2,
             "player_world_position": {"x": 12., "y": 34.},
             "movement": {"speed": 7., "moving": True},
             "visual_candidates": [{"track_id": "track", "x": .58, "y": .61,
                 "bbox_height_fraction": .08, "confidence": .82, "source": "WORLD3D",
                 "lifecycle": "ACTIVE", "appearance": {"camera_motion_dx": 3.,
                                                            "camera_motion_dy": -1.}}]}
    controller.start({"guid": "npc", "track_id": "track", "purpose": "COMBAT"},
                     state, "o1", 10.)
    updated = {**state, "monotonic_time": 10.1,
               "visual_candidates": [{**state["visual_candidates"][0],
                                        "x": .54, "bbox_height_fraction": .09}]}
    controller.observe(updated, "o2", 10.1)
    sample = controller.samples[-1]
    assert sample.track_id == "track"
    assert sample.bbox_scale_delta == pytest.approx(.01)
    assert sample.camera_motion_x == 3.
    assert (sample.player_x, sample.player_y, sample.player_heading) == (12., 34., 1.2)
    assert sample.player_speed == 7. and sample.player_moving is True
    assert controller.snapshot()["visual_progress_samples"] == 1


def test_predicted_occluded_track_only_drives_bounded_player_turn_reacquisition():
    controller = VisualApproachController()
    active = {"target": {"guid": "npc", "dead": False},
              "visual_candidates": [{"track_id": "track", "x": .62, "y": .55,
                                      "bbox_height_fraction": .07,
                                      "confidence": .8, "source": "WORLD3D",
                                      "lifecycle": "ACTIVE"}]}
    controller.start({"guid": "npc", "track_id": "track", "purpose": "COMBAT"},
                     active, "o1", 1.)
    occluded = {**active, "visual_candidates": [{**active["visual_candidates"][0],
                                                   "x": .64, "confidence": .55,
                                                   "lifecycle": "OCCLUDED"}]}
    assessment = controller.observe(occluded, "o2", 1.05)
    assert assessment.reason == "visual_track_predicted_during_occlusion"
    assert controller.command(occluded, "o2", 1.05) == ()
    unselected = {**occluded, "target": {}}
    controller.observe(unselected, "o3", 1.10)
    assert controller.command(unselected, "o3", 1.10) == ()
    controller.observe(unselected, "o4", 1.15)
    command = controller.command(unselected, "o4", 1.15)[0]
    assert command.kind == "BIND"
    assert command.binding in {"TURNLEFT", "TURNRIGHT"}
    assert controller.samples[-1].predicted is True


def test_identify_reacquisition_is_slow_one_way_and_observation_gated():
    controller = VisualApproachController()
    active = {
        "target": {},
        "visual_candidates": [{
            "track_id": "unknown-cue", "x": .62, "y": .55,
            "bbox_height_fraction": .04, "confidence": .3,
            "source": "WORLD3D", "lifecycle": "ACTIVE",
        }],
    }
    controller.start(
        {"track_id": "unknown-cue", "purpose": "IDENTIFY"},
        active, "o1", 1.)

    missing = {"target": {}, "visual_candidates": []}
    controller.observe(missing, "o2", 1.1)
    first = controller.command(missing, "o2", 1.1)
    assert first and first[0].kind == "BIND"
    assert (first[0].binding, first[0].duration) == ("TURNLEFT", .16)

    controller.observe(missing, "o3", 1.5)
    assert controller.command(missing, "o3", 1.5) == ()

    controller.observe(missing, "o4", 2.0)
    second = controller.command(missing, "o4", 2.0)
    assert second and (second[0].binding, second[0].duration) == ("TURNLEFT", .16)
