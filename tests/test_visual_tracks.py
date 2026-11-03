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


def test_v3_subject_keeps_raw_track_when_canonical_detector_kind_flips():
    """PID 20864: a steady V3 subject must not birth a raw track on every label flip."""
    tracks = VisualTrackManager()

    def sample(upstream: str, x: float, detector_kind: str) -> dict:
        left = round(x * 961 - 23)
        return {"kind": "unknown_subject_candidate", "detector_kind": detector_kind,
                "upstream_track_id": upstream, "x": x, "y": .55, "confidence": .8,
                "bbox": {"left": left, "top": 195, "right": left + 46, "bottom": 295},
                "bbox_width_fraction": 46 / 961, "bbox_height_fraction": 100 / 541}

    subject = "WORLD3D_V3:1657"
    neighbour = "WORLD3D_V3:1567"
    first = tracks.update("WORLD3D", [sample(subject, .46, "obstacle_candidate"),
                                      sample(neighbour, .49, "unknown_subject_candidate")], 1.)
    subject_id = next(item["track_id"] for item in first if item["upstream_track_id"] == subject)
    neighbour_id = next(item["track_id"] for item in first if item["upstream_track_id"] == neighbour)
    for at, label in [(1.04, "unknown_subject_candidate"),
                      (1.08, "obstacle_candidate"),
                      (1.12, "unknown_subject_candidate")]:
        observed = tracks.update("WORLD3D", [sample(neighbour, .49, "unknown_subject_candidate"),
                                              sample(subject, .46, label)], at)
        assert next(item["track_id"] for item in observed
                    if item["upstream_track_id"] == subject) == subject_id
        assert next(item["track_id"] for item in observed
                    if item["upstream_track_id"] == neighbour) == neighbour_id
    assert len(tracks.tracks["WORLD3D"]) == 2
    assert len([event for event in tracks.identity_events if event["event"] == "new"]) == 2


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
    assert tracks.identity_events[-1]["event"] == "upstream_rebind"
    assert tracks.identity_events[-1]["previous_upstream_track_id"] == "WORLD3D_V3:17"
    assert tracks.identity_events[-1]["upstream_track_id"] == "WORLD3D_V3:99"


def test_returning_upstream_keeps_its_id_when_speculative_alias_is_also_visible():
    """14:21 run: V3:923 must not keep V3:830's id after both reappear."""
    tracks = VisualTrackManager()

    def subject(upstream, x):
        center = round(x * 961)
        return {"kind": "unknown_subject_candidate", "upstream_track_id": upstream,
                "x": x, "y": .5, "confidence": .8,
                "bbox": {"left": center - 16, "top": 170,
                         "right": center + 16, "bottom": 213},
                "bbox_width_fraction": 32 / 961, "bbox_height_fraction": 43 / 541}

    original = tracks.update("WORLD3D", [subject("WORLD3D_V3:830", .50)], 1.)[0]
    alias = tracks.update("WORLD3D", [subject("WORLD3D_V3:923", .51)], 1.04)[0]
    assert alias["track_id"] == original["track_id"]

    for at, detections in [(1.08, [subject("WORLD3D_V3:923", .58),
                                   subject("WORLD3D_V3:830", .50)]),
                            (1.12, [subject("WORLD3D_V3:830", .50),
                                    subject("WORLD3D_V3:923", .58)])]:
        observed = tracks.update("WORLD3D", detections, at)
        by_upstream = {item["upstream_track_id"]: item for item in observed}
        assert by_upstream["WORLD3D_V3:830"]["track_id"] == original["track_id"]
        assert by_upstream["WORLD3D_V3:923"]["track_id"] != original["track_id"]


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


def test_long_detector_gap_does_not_resurrect_an_active_track_id():
    """Issue #105: after a 100 s gap a new upstream id at the same place
    reused WORLD3D:1 (UPSTREAM_REIDENTIFIED) past every loss/re-ID bound."""
    tracks = VisualTrackManager()
    detection = {"kind": "unknown_subject_candidate", "x": .4, "y": .6, "confidence": .7,
                 "upstream_track_id": "V3:1",
                 "bbox": {"left": 10, "top": 20, "right": 30, "bottom": 70},
                 "appearance": {"shape": "subject_like"}}
    first = tracks.update("WORLD3D", [detection], 1.)[0]
    later = tracks.update("WORLD3D", [{**detection, "upstream_track_id": "V3:999"}], 101.)[0]
    assert later["track_id"] != first["track_id"]


def test_empty_world_batches_age_active_tracks():
    """Issue #105: an empty batch must age (and finally retire) active tracks;
    perception_cycle now calls update() for it."""
    tracks = VisualTrackManager()
    detection = {"kind": "unknown_subject_candidate", "x": .4, "y": .6, "confidence": .7}
    tracks.update("WORLD3D", [detection], 1.)
    for at in (1.1, 1.2, 1.3, 2.4, 2.5):
        tracks.update("WORLD3D", [], at)
    assert not tracks.tracks["WORLD3D"]
