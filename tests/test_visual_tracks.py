from wowbot.agent.visual_tracks import VisualTrackManager


def test_visual_track_is_unknown_even_when_detector_calls_it_quest_giver():
    tracks = VisualTrackManager()
    samples = [tracks.update("MINIMAP_CV", [{"kind": "quest_giver", "x": .8+i*.001,
                                              "y": .5, "confidence": .9}], i)[0]
               for i in range(3)]
    assert len({item["track_id"] for item in samples}) == 1
    assert samples[-1]["track_state"] == "ACTIVE"
    assert samples[-1]["temporal_state"] == "CONFIRMED"
    assert samples[-1]["association_evidence"]["class_compatibility"] == "UNKNOWN_FAMILY_COMPATIBLE"
    assert samples[-1]["semantic_type"] == "UNKNOWN"
    assert samples[-1]["detector_kind"] == "quest_giver"
    assert len(samples[-1]["position_history"]) == 3
    assert len(samples[-1]["confidence_history"]) == 3


def test_detector_label_drift_does_not_change_track_identity_or_semantics():
    tracks = VisualTrackManager()
    first = tracks.update("WORLD_MAP_CV", [{"kind": "quest_giver", "x": .4, "y": .6}], 1)[0]
    second = tracks.update("WORLD_MAP_CV", [{"kind": "quest_turn_in", "x": .401, "y": .6}], 2)[0]
    assert first["track_id"] == second["track_id"]
    assert second["semantic_type"] == "UNKNOWN"
    assert second["detection_hypotheses"] == {"quest_giver": 1, "quest_turn_in": 1}


def test_tracks_are_source_local_and_expose_lost_lifecycle():
    tracks = VisualTrackManager(max_misses=2)
    mini = tracks.update("MINIMAP_CV", [{"kind": "visual", "x": .5, "y": .5}], 1)[0]
    world = tracks.update("WORLD3D", [{"kind": "visual", "x": .5, "y": .5}], 1)[0]
    assert mini["track_id"] != world["track_id"]
    tracks.update("MINIMAP_CV", [], 2)
    assert next(item for item in tracks.snapshot() if item["track_id"] == mini["track_id"])["state"] == "OCCLUDED"


def test_discriminative_candidate_label_survives_short_detector_flicker():
    tracks = VisualTrackManager()
    first = {"kind": "unknown_symbol_candidate", "x": .5, "y": .7,
             "confidence": .84, "candidate_labels": ["quest_badge_like"]}
    plain = {**first, "candidate_labels": ["overhead_symbol_like_cue"]}
    observed = tracks.update("WORLD3D", [first], 1.)[0]
    observed = tracks.update("WORLD3D", [plain], 2.)[0]
    assert "quest_badge_like" in observed["candidate_labels"]
    assert observed["semantic_type"] == "UNKNOWN"


def test_source_tracker_uses_global_assignment_for_close_tracks():
    tracks = VisualTrackManager()
    first = tracks.update("WORLD3D", [
        {"kind": "unknown_subject_candidate", "x": .10, "y": .5, "confidence": .9},
        {"kind": "unknown_subject_candidate", "x": .14, "y": .5, "confidence": .9},
    ], 1.)
    observed = tracks.update("WORLD3D", [
        {"kind": "unknown_subject_candidate", "x": .125, "y": .5, "confidence": .95},
        {"kind": "unknown_subject_candidate", "x": .139, "y": .5, "confidence": .80},
    ], 2.)

    assert observed[0]["track_id"] == first[0]["track_id"]
    assert observed[1]["track_id"] == first[1]["track_id"]


def test_track_loss_requires_wall_clock_grace_as_well_as_miss_count():
    tracks = VisualTrackManager(max_misses=2, lost_grace_seconds=.5)
    tracks.update("WORLD3D", [{"kind": "unknown_subject_candidate", "x": .5, "y": .5}], 1.)
    for at in (1.01, 1.02, 1.03, 1.04):
        projected = tracks.update("WORLD3D", [], at)
    assert projected and projected[0]["lifecycle"] == "LOST_TEMPORARY"
    assert projected[0]["temporal_state"] == "LOST"
    assert projected[0]["missing_seconds"] < .5
    assert tracks.update("WORLD3D", [], 1.6) == []


def test_world3d_upstream_tracker_id_prevents_second_identity_assignment():
    tracks = VisualTrackManager()
    first = tracks.update("WORLD3D", [{"kind": "unknown_subject_candidate", "x": .2, "y": .5,
                                        "upstream_track_id": "WORLD3D_V3:17"}], 1.)[0]
    # A large screen displacement may occur during a detector refresh/camera
    # motion; the V3 association is the upstream authority for this source.
    second = tracks.update("WORLD3D", [{"kind": "unknown_subject_candidate", "x": .8, "y": .5,
                                         "upstream_track_id": "WORLD3D_V3:17"}], 1.1)[0]
    assert second["track_id"] == first["track_id"]
    assert next(item for item in tracks.snapshot() if item["track_id"] == first["track_id"])["upstream_track_id"] == "WORLD3D_V3:17"


def test_world3d_nearby_refresh_id_is_reidentified_without_new_track():
    tracks = VisualTrackManager()
    first = tracks.update("WORLD3D", [{
        "kind": "unknown_subject_candidate", "x": .40, "y": .50,
        "confidence": .8, "upstream_track_id": "WORLD3D_V3:17",
        "appearance": {"foreground_contrast": .7, "edge_density": .5, "body_geometry": .7},
    }], 1.)[0]
    # The detector has restarted its V3 id, but the nearby same-appearance
    # candidate must retain the source-local visual identity.
    second = tracks.update("WORLD3D", [{
        "kind": "unknown_subject_candidate", "x": .418, "y": .502,
        "confidence": .8, "upstream_track_id": "WORLD3D_V3:99",
        "appearance": {"foreground_contrast": .69, "edge_density": .51, "body_geometry": .7},
    }], 1.2)[0]
    assert second["track_id"] == first["track_id"]
    assert second["upstream_association"] == "UPSTREAM_REIDENTIFIED"
    assert {"WORLD3D_V3:17", "WORLD3D_V3:99"} <= set(second["upstream_track_aliases"])


def test_world3d_new_upstream_id_does_not_merge_distant_subject():
    tracks = VisualTrackManager()
    first = tracks.update("WORLD3D", [{
        "kind": "unknown_subject_candidate", "x": .40, "y": .50,
        "upstream_track_id": "WORLD3D_V3:17",
    }], 1.)[0]
    second = tracks.update("WORLD3D", [{
        "kind": "unknown_subject_candidate", "x": .48, "y": .50,
        "upstream_track_id": "WORLD3D_V3:99",
    }], 1.2)[0]
    assert second["track_id"] != first["track_id"]


def test_distinctive_track_reidentifies_after_long_gap_without_semantic_claim():
    tracks = VisualTrackManager(max_misses=2, lost_grace_seconds=.5,
                                reidentification_grace_seconds=8.)
    appearance = {"foreground_contrast": .72, "edge_density": .43,
                  "body_geometry": .81, "residual_motion": .18}
    first = tracks.update("WORLD3D", [{
        "kind": "unknown_subject_candidate", "x": .40, "y": .50,
        "bbox": {"left": 360, "top": 310, "right": 410, "bottom": 430},
        "bbox_width_fraction": .05, "bbox_height_fraction": .12,
        "appearance": appearance,
    }], 1.)[0]
    tracks.update("WORLD3D", [], 1.2)
    assert tracks.update("WORLD3D", [], 1.7) == []

    revived = tracks.update("WORLD3D", [{
        "kind": "unknown_subject_candidate", "x": .425, "y": .505,
        "bbox": {"left": 385, "top": 312, "right": 436, "bottom": 434},
        "bbox_width_fraction": .051, "bbox_height_fraction": .122,
        "appearance": {"foreground_contrast": .70, "edge_density": .45,
                       "body_geometry": .80, "residual_motion": .19},
    }], 4.)[0]

    assert revived["track_id"] == first["track_id"]
    assert revived["upstream_association"] == "LONG_GAP_REIDENTIFIED"
    assert revived["lifecycle"] == "REACQUIRE_CANDIDATE"
    assert revived["semantic_type"] == "UNKNOWN"
    assert revived["association_evidence"]["fact"] is False


def test_feature_poor_track_is_not_reidentified_after_expiry():
    tracks = VisualTrackManager(max_misses=2, lost_grace_seconds=.5,
                                reidentification_grace_seconds=8.)
    first = tracks.update("WORLD3D", [{
        "kind": "unknown_subject_candidate", "x": .40, "y": .50,
        "appearance": {"foreground_contrast": .7},
    }], 1.)[0]
    tracks.update("WORLD3D", [], 1.2)
    tracks.update("WORLD3D", [], 1.7)
    replacement = tracks.update("WORLD3D", [{
        "kind": "unknown_subject_candidate", "x": .405, "y": .50,
        "appearance": {"foreground_contrast": .7},
    }], 3.)[0]

    assert replacement["track_id"] != first["track_id"]
    assert replacement["upstream_association"] == "NEW"


# Perf guard (live-confirmed 2026-09-22): a stuck search/INSPECT loop can
# flood a never-stabilizing scene with far more raw candidates than normal,
# and the per-tick new-candidates x active-tracks Hungarian assignment below
# must stay bounded regardless of how noisy the detector gets.

def _flood(n, *, kind="unknown_subject_candidate", x0=.01):
    return [{"kind": kind, "x": min(.99, x0 + i * .001), "y": .5, "confidence": .5 + (i % 50) * .001}
            for i in range(n)]


def test_a_single_flood_of_candidates_is_capped_before_the_cost_matrix():
    tracks = VisualTrackManager(max_active_tracks=60, max_new_candidates=60)
    result = tracks.update("WORLD3D", _flood(220), 1.)
    # Only the top max_new_candidates by confidence are tracked this tick;
    # the rest are dropped rather than paying full association cost on 220.
    assert len(result) <= 60


def test_active_track_count_never_exceeds_the_cap_across_repeated_floods():
    tracks = VisualTrackManager(max_active_tracks=60, max_new_candidates=60)
    # Every tick uses fresh x-offsets so (almost) nothing matches a prior
    # track -- the worst case that used to make `active` grow without bound.
    for tick in range(10):
        tracks.update("WORLD3D", _flood(220, x0=.01 + tick * .01), float(tick))
        assert len(tracks.tracks["WORLD3D"]) <= 60


def test_excess_active_tracks_are_evicted_lowest_hits_first():
    tracks = VisualTrackManager(max_active_tracks=2, max_new_candidates=10)
    tracks.update("WORLD3D", [{"kind": "unknown_subject_candidate", "x": .1, "y": .5, "confidence": .9}], 1.)
    tracks.update("WORLD3D", [{"kind": "unknown_subject_candidate", "x": .1, "y": .5, "confidence": .9}], 2.)
    # This track now has hits=2, the highest-priority one to keep.
    established_id = next(iter(tracks.tracks["WORLD3D"].values())).identity
    # Flood in two brand-new, never-matching candidates. `active` can briefly
    # exceed the cap within the tick that creates them (eviction runs before
    # this tick's new tracks are added), but the very next tick's eviction
    # pass must bring it back down to the cap and keep the established track.
    tracks.update("WORLD3D", [
        {"kind": "unknown_subject_candidate", "x": .5, "y": .5, "confidence": .3},
        {"kind": "unknown_subject_candidate", "x": .9, "y": .5, "confidence": .3},
    ], 3.)
    tracks.update("WORLD3D", [], 4.)
    active = tracks.tracks["WORLD3D"]
    assert len(active) == 2
    assert established_id in active


def test_small_normal_candidate_counts_are_unaffected_by_the_default_cap():
    tracks = VisualTrackManager()
    result = tracks.update("WORLD3D", _flood(25), 1.)
    assert len(result) == 25
