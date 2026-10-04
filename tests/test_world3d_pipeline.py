import numpy as np
import pytest
import threading
import time

from wowbot.vision.world3d import (PixelRect, World3DPipeline, WorldSceneROI,
                                   TemporalTraversabilityFusion, validate_batch)
from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel
from wowbot.agent.perception import PerceptionWorker


def _frame(width=320, height=240):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :, :3] = 75
    image[:, :, 3] = 255
    return image.tobytes(), width, height


def _textured_frame(width=320, height=240, *, invert=False):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    yy, xx = np.indices((height, width))
    values = ((xx//8 + yy//8) % 2 * 190 + 30).astype(np.uint8)
    if invert:
        values = 255-values
    image[:, :, :3] = values[:, :, None]
    image[:, :, 3] = 255
    return image.tobytes(), width, height


def _track(track_id="WORLD3D:1", *, rect=None, **overrides):
    base = {
        "track_id": track_id,
        "source": "WORLD3D",
        "detector_kind": "unknown_subject_candidate",
        "kind": "unknown_subject_candidate",
        "confidence": .78,
        "lifecycle": "ACTIVE",
        "bbox": {"left": 130, "top": 80, "right": 170, "bottom": 180,
                 "coordinate_space": "CLIENT_PIXELS"},
        "bbox_height_fraction": 100 / 240,
        "appearance": {},
        "candidate_labels": ["overhead_symbol_like_cue"],
    }
    if rect:
        base["bbox"] = {**rect, "coordinate_space": "CLIENT_PIXELS"}
        base["bbox_height_fraction"] = (rect["bottom"]-rect["top"])/240
    base.update(overrides)
    return base


def test_canonical_batch_keeps_unknown_visual_semantics_and_explicit_spaces():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    batch = pipeline.observe(_frame(), {"client_id": "test-client"}, [_track(
        upstream_track_id="WORLD3D_V3:17",
        upstream_track_aliases=["WORLD3D_V3:12", "WORLD3D_V3:17"],
        upstream_association="UPSTREAM_REIDENTIFIED",
    )], scene, observed_at=1., frame_id="f-1")
    track = batch.entity_tracks[0]

    assert track["semantic_type"] == "UNKNOWN"
    assert track["confirmed"] is False
    assert track["bbox"]["coordinate_space"] == "SCREEN_PIXELS"
    assert track["viewport_bbox"]["coordinate_space"] == "WORLD_VIEWPORT_NORMALIZED"
    assert track["bearing"]["coordinate_space"] == "CAMERA_RELATIVE_BEARING"
    assert track["upstream_track_id"] == "WORLD3D_V3:17"
    assert track["upstream_association"] == "UPSTREAM_REIDENTIFIED"
    assert all(belief["fact"] is False for belief in track["type_beliefs"] + track["role_beliefs"])
    detection = batch.detections[0]
    assert detection["frame_id"] == "f-1"
    assert detection["track_id"] == track["track_id"]
    assert detection["class_distribution"]["UNKNOWN"] == 1.0
    assert sum(detection["class_distribution"].values()) == 1.0
    assert track["latest_detection_id"] == detection["detection_id"]
    assert validate_batch(batch).valid


def test_learned_view_tracks_use_full_client_normalization_not_heuristic_roi():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(
        PixelRect(0, 92, 892, 374),
        learned_rect=PixelRect(0, 12, 892, 502),
    )
    rect = {"left": 692, "top": 390, "right": 782, "bottom": 490}

    batch = pipeline.observe(
        _frame(892, 502), {}, [_track(rect=rect)], scene,
        observed_at=1., frame_id="capture:geometry",
    )
    track = batch.entity_tracks[0]

    assert track["raw_screen_center"]["x"] == pytest.approx(737/892)
    assert track["raw_screen_center"]["y"] == pytest.approx(440/502)
    assert 0 <= track["raw_screen_center"]["y"] <= 1
    assert track["viewport_bbox"]["bottom"] == pytest.approx(490/502)


def test_track_with_center_outside_current_frame_is_not_actionable():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(
        PixelRect(0, 92, 892, 374),
        learned_rect=PixelRect(0, 12, 892, 502),
    )
    stale_probe = _track(rect={"left": 692, "top": 504, "right": 782, "bottom": 629})

    batch = pipeline.observe(
        _frame(892, 502), {}, [stale_probe], scene,
        observed_at=1., frame_id="capture:stale-probe",
    )

    assert batch.entity_tracks == ()


def test_detection_contract_rejects_malformed_or_cross_frame_classification():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    batch = pipeline.observe(_frame(), {"client_id": "test-client"}, [_track()], scene,
                             observed_at=1., frame_id="capture:1")
    bad = dict(batch.detections[0])
    bad["frame_id"] = "capture:other"
    bad["class_distribution"] = {"UNKNOWN": .5}
    tampered = type(batch)(
        frame_id=batch.frame_id, timestamp=batch.timestamp, client_id=batch.client_id,
        scene_roi=batch.scene_roi, camera_state=batch.camera_state, ego_motion=batch.ego_motion,
        entity_tracks=batch.entity_tracks, detections=(bad,), scene_geometry=batch.scene_geometry,
        traversability=batch.traversability, obstacles=batch.obstacles, entrances=batch.entrances,
        landmarks=batch.landmarks, interaction_candidates=batch.interaction_candidates,
        negative_evidence=batch.negative_evidence, diagnostics=batch.diagnostics,
        frame_events=batch.frame_events, processing_latency_ms=batch.processing_latency_ms)

    report = validate_batch(tampered)
    assert not report.valid
    assert any(error.startswith("detection_frame_mismatch") for error in report.errors)
    assert any(error.startswith("detection_class_distribution") for error in report.errors)


def test_frame_contract_preserves_client_and_dropped_capture_evidence():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))

    batch = pipeline.observe(_frame(), {"client_id": "pid:42", "dropped_frames": 3}, [], scene,
                             observed_at=1., frame_id="capture:7")

    assert batch.frame_id == "capture:7"
    assert batch.client_id == "pid:42"
    assert batch.to_payload()["client_id"] == "pid:42"
    assert batch.frame_events == ({"event_type": "FRAME_DROPPED", "count": 3,
                                   "timestamp_monotonic": 1., "client_id": "pid:42",
                                   "frame_id": "capture:7", "source": "WORLD3D_FRAME_SOURCE"},)
    assert validate_batch(batch).valid


def test_pipeline_rejects_out_of_order_capture_timestamp():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    pipeline.observe(_frame(), {"client_id": "pid:42"}, [], scene,
                     observed_at=2., frame_id="capture:2")

    with pytest.raises(ValueError, match="timestamp regressed"):
        pipeline.observe(_frame(), {"client_id": "pid:42"}, [], scene,
                         observed_at=1.9, frame_id="capture:1")


def test_worker_logs_superseded_capture_on_next_world3d_batch():
    """One in-flight lane must drop, rather than queue, a newer capture."""
    worker = PerceptionWorker()
    # This test re-submits one identical capture object on the time gate;
    # the frame-driven runtime default would (correctly) not reprocess it.
    worker.world_frame_driven = False
    started, release = threading.Event(), threading.Event()
    calls = 0

    def detector(_frame, _at, _geometry):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            assert release.wait(1.)
        return ()

    try:
        worker._world_v2 = detector
        worker._minimap = lambda *_args: ()
        first = _frame()
        second = (bytes([1]) + first[0][1:], first[1], first[2])
        geometry = {"client_id": "pid:42"}
        worker.update(first, 1., geometry=geometry, context=("session", "char", 1, 0))
        assert started.wait(1.)
        worker.update(second, 1.01, geometry=geometry, context=("session", "char", 1, 0))
        release.set()
        time.sleep(.02)
        # Collect the first batch, then submit the newest capture after the
        # normal scheduler interval.  Its source metadata must contain the
        # deliberately dropped intermediate capture count.
        worker.update(second, 1.2, geometry=geometry, context=("session", "char", 1, 0))
        time.sleep(.02)
        worker.update(second, 1.3, geometry=geometry, context=("session", "char", 1, 0))
        # Canonical evidence publication is deliberately slower than the
        # 30 Hz tracker. Submit and harvest the next due canonical sample.
        worker.update(second, 1.4, geometry=geometry, context=("session", "char", 1, 0))
        time.sleep(.02)
        worker.update(second, 1.5, geometry=geometry, context=("session", "char", 1, 0))

        assert worker.world3d_batch is not None
        assert worker.world3d_batch.client_id == "pid:42"
        assert any(event["event_type"] == "FRAME_DROPPED" and event["count"] >= 1
                   for event in worker.world3d_batch.frame_events)
    finally:
        release.set()
        worker.close()


def test_scale_history_yields_relative_distance_trend_without_fake_meters():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    first = _track(rect={"left": 145, "top": 100, "right": 155, "bottom": 140})
    second = _track(rect={"left": 135, "top": 70, "right": 165, "bottom": 185})
    pipeline.observe(_frame(), {}, [first], scene, observed_at=1.)
    batch = pipeline.observe(_frame(), {}, [second], scene, observed_at=1.1)
    track = batch.entity_tracks[0]

    assert track["scale_trend"] == "APPROACHING"
    assert track["distance_belief"]["bucket"] in {"NEAR", "VERY_NEAR"}
    assert "estimated_meters" not in track["distance_belief"]
    assert track["raw_screen_center"]["coordinate_space"] == "WORLD_VIEWPORT_NORMALIZED"
    assert track["smoothed_viewport_bbox"]["coordinate_space"] == "WORLD_VIEWPORT_NORMALIZED"
    assert track["motion"]["smoothed_velocity"]["coordinate_space"] == "WORLD_VIEWPORT_NORMALIZED_PER_SECOND"
    assert track["distance_belief"]["unit_or_relative_scale"] == "RELATIVE_SCREEN_SCALE"
    assert track["distance_belief"]["metric_value"] is None
    assert -1 <= track["bearing"]["horizontal"] <= 1


def test_temporal_filter_keeps_raw_detection_and_publishes_smoothed_kinematics():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    first = _track(rect={"left": 120, "top": 80, "right": 160, "bottom": 160})
    second = _track(rect={"left": 240, "top": 80, "right": 280, "bottom": 160})
    pipeline.observe(_frame(), {"client_id": "test-client"}, [first], scene,
                     observed_at=1., frame_id="capture:1")
    batch = pipeline.observe(_frame(), {"client_id": "test-client"}, [second], scene,
                             observed_at=1.1, frame_id="capture:2")
    track = batch.entity_tracks[0]

    assert track["raw_screen_center"]["x"] == pytest.approx(.8125)
    assert .5 < track["screen_center"]["x"] < track["raw_screen_center"]["x"]
    assert track["motion"]["smoothed_velocity"]["x"] > 0
    assert track["bbox"] == batch.detections[0]["bbox"]  # source geometry is not replaced


def test_obstacle_only_changes_local_traversability_evidence_not_navigation():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    obstacle = _track(track_id="WORLD3D:rock", detector_kind="obstacle_candidate",
                      rect={"left": 120, "top": 95, "right": 200, "bottom": 225},
                      appearance={"static_scene_score": .8, "shape": "rock_like"},
                      candidate_labels=[])
    batch = pipeline.observe(_frame(), {}, [obstacle], scene, observed_at=1.)
    center = next(sector for sector in batch.traversability["sectors"] if sector["sector"] == "CENTER")

    assert batch.obstacles and batch.obstacles[0]["fact"] is False
    assert center["blocked_probability"] > 0
    assert "go_to_entity" not in batch.to_payload()


def test_temporal_traversability_requires_repeated_block_evidence_and_then_decays():
    fusion = TemporalTraversabilityFusion()
    blocked = {"coordinate_space": "WORLD_VIEWPORT_NORMALIZED", "sectors": [{
        "sector": "CENTER", "free_probability": .10, "blocked_probability": .82,
        "unknown_probability": .08, "evidence": ["boundary_overlap"], "fact": False,
    }]}
    first = fusion.update(blocked, observed_at=1.)["sectors"][0]
    second = fusion.update(blocked, observed_at=1.1)["sectors"][0]
    clear = fusion.update({"coordinate_space": "WORLD_VIEWPORT_NORMALIZED", "sectors": [{
        "sector": "CENTER", "free_probability": .88, "blocked_probability": .02,
        "unknown_probability": .10, "evidence": ["clear_ground"], "fact": False,
    }]}, observed_at=1.2)["sectors"][0]

    assert first["obstacle_lifecycle"] == "SUSPECTED"
    assert first["state"] != "BLOCKED"  # one visual frame is never a hard block
    assert second["obstacle_lifecycle"] == "CONFIRMED"
    assert second["state"] == "BLOCKED"
    assert clear["obstacle_lifecycle"] == "DECAYING"
    assert clear["state"] != "BLOCKED"


def test_camera_rotation_does_not_create_collision_evidence():
    fusion = TemporalTraversabilityFusion()
    raw = {"coordinate_space": "WORLD_VIEWPORT_NORMALIZED", "sectors": [{
        "sector": "CENTER", "free_probability": .8, "blocked_probability": .0,
        "unknown_probability": .2, "evidence": [], "fact": False,
    }]}
    sector = fusion.update(raw, observed_at=1., ego_motion={"motion_kind": "ROTATION"},
                           motion_feedback={"commanded_motion": "FORWARD", "progress_score": 0.})["sectors"][0]

    assert sector["collision_evidence_confidence"] == 0
    assert sector["state"] != "BLOCKED"


def test_traversability_fusion_renormalizes_only_available_configured_sources():
    fusion = TemporalTraversabilityFusion()
    raw = {"coordinate_space": "WORLD_VIEWPORT_NORMALIZED", "sectors": [{
        "sector": "CENTER", "free_probability": .10, "blocked_probability": .80,
        "unknown_probability": .10, "evidence": ["boundary_overlap"], "fact": False,
    }]}

    sector = fusion.update(raw, observed_at=1.)["sectors"][0]

    # Depth and motion sources are unavailable, so their configured weights do
    # not dilute the independently observed boundary/free-space evidence.
    assert sector["obstacle_confidence"] >= .80
    assert sector["depth_discontinuity_confidence"] == 0


def test_drop_evidence_creates_danger_and_explicit_traversability_event():
    fusion = TemporalTraversabilityFusion()
    result = fusion.update({"coordinate_space": "WORLD_VIEWPORT_NORMALIZED", "sectors": [{
        "sector": "CENTER", "free_probability": .4, "blocked_probability": .1,
        "unknown_probability": .5, "drop_confidence": .9, "evidence": ["ground_end"], "fact": False,
    }]}, observed_at=1.)

    assert result["sectors"][0]["state"] == "DANGEROUS"
    assert any(event["event_type"] == "CLIFF_SUSPECTED" for event in result["events"])
    assert any(event["event_type"] == "TRAVERSABILITY_UPDATED" for event in result["events"])


def test_pipeline_preserves_camera_rotation_kind_for_traversability_fusion():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    batch = pipeline.observe(
        _frame(), {"movement": {"moving": True},
                   "motion_feedback": {"commanded_motion": "FORWARD", "progress_score": 0.}},
        [], scene, observed_at=1.,
        camera_motion={"dx": 7., "dy": 0., "confidence": .9, "motion_kind": "ROTATION"},
    )
    center = next(item for item in batch.traversability["sectors"] if item["sector"] == "CENTER")

    assert batch.ego_motion["motion_kind"] == "ROTATION"
    assert batch.camera_state["optical_flow_summary"]["confidence"] == .9
    assert batch.ego_motion["player_motion_evidence"]["moving"] is True
    assert center["collision_evidence_confidence"] == 0


def test_temporary_occlusion_is_preserved_as_a_track_lifecycle():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    occluded = _track(lifecycle="OCCLUDED", occlusion_probability=.64)
    batch = pipeline.observe(_frame(), {}, [occluded], scene, observed_at=1.)

    assert pipeline.get_active_tracks()[0]["lifecycle"] == "OCCLUDED"
    assert pipeline.get_active_tracks()[0]["visibility"] == "OCCLUDED"


def test_active_perception_requests_are_read_only_and_can_emit_negative_evidence():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    pipeline.observe(_frame(), {}, [_track()], scene, observed_at=1.)
    request = pipeline.request_identity_probe("WORLD3D:1")
    scan = pipeline.request_local_scan({"label": "door_like"})
    batch = pipeline.observe(_frame(), {"search_coverage": "local_sweep"}, [], scene, observed_at=2.)

    assert request["status"] == "REQUESTED" and request["kind"] == "IDENTITY_PROBE"
    assert scan["status"] == "REQUESTED"
    assert batch.negative_evidence[0]["kind"] == "LOCAL_SCAN_UNOBSERVED"


def test_entrance_detector_is_context_evidence_not_a_door_fact():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    candidate = _track(detector_kind="unknown_object_candidate", candidate_labels=["door_like"])
    batch = pipeline.observe(_frame(), {}, [candidate], scene, observed_at=1.)

    assert batch.entrances
    assert batch.entrances[0]["kind"] == "UNKNOWN"
    assert batch.entrances[0]["fact"] is False


def test_corpse_object_and_interaction_cues_stay_unknown_but_queryable():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    tracks = [
        _track("WORLD3D:corpse", candidate_labels=["learned_corpse_like"],
               appearance={"death_confirmation": True,
                           "death_continuity_track_id": "WORLD3D:alive-before"}),
        _track("WORLD3D:object", detector_kind="unknown_object_candidate",
               candidate_labels=["learned_object_like", "quest_object_like"]),
        _track("WORLD3D:interact", candidate_labels=["interact_cue_like"]),
    ]
    batch = pipeline.observe(_frame(), {}, tracks, scene, observed_at=1.)

    by_id = {track["track_id"]: track for track in batch.entity_tracks}
    assert by_id["WORLD3D:corpse"]["semantic_type"] == "UNKNOWN"
    assert by_id["WORLD3D:corpse"]["corpse_belief"]["belief"] == "SUPPORTED"
    assert pipeline.get_corpses()[0]["track_id"] == "WORLD3D:corpse"
    assert pipeline.get_quest_objects()[0]["track_id"] == "WORLD3D:object"
    assert "WORLD3D:interact" in {row["track_id"] for row in pipeline.get_interactables()}
    assert all(not track["confirmed"] for track in batch.entity_tracks)


def test_batch_reaches_world_model_as_separate_local_evidence_projection():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    batch = pipeline.observe(_frame(), {}, [_track()], scene, observed_at=1., frame_id="vision-1")
    model = WorldModel()
    addon = Observation.create({"session_id": "test-session", "timestamp": 1., "frame_id": "addon-1",
                                "player_present": True, "position": {"x": .5, "y": .5}}, 1.)
    assert model.ingest(addon)
    payload = batch.to_payload()
    local = Observation.create({"session_id": "test-session", "timestamp": 1.1, "frame_id": "vision-1",
                                "world3d_batch": payload, "local_traversability": payload["traversability"],
                                "scene_geometry": payload["scene_geometry"],
                                "world3d_obstacles": payload["obstacles"],
                                "world3d_entrances": payload["entrances"],
                                "confidence": .5}, 1.1, "WORLD3D_LOCAL_VIEW")
    assert model.ingest(local)

    view = model.query.local_world_view()
    assert view["world3d_batch"]["frame_id"] == "vision-1"
    assert model.planning_snapshot(1.1).traversability.value["sectors"]


def test_debug_overlay_and_replay_are_rendering_and_input_free_data_contracts():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    pipeline.observe(_frame(), {}, [_track()], scene, observed_at=1., frame_id="f-debug")
    overlay = pipeline.debug_overlay()
    replay = pipeline.replay_record()

    assert overlay["tracks"][0]["bbox"]["coordinate_space"] == "SCREEN_PIXELS"
    assert replay["kind"] == "WORLD3D_REPLAY"
    assert replay["frame_meta"]["frame_id"] == "f-debug"
    assert "input" not in replay and "move" not in replay


def test_visual_condition_diagnostics_downweight_poor_frame_confidence():
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240),
                          excluded_rects=(PixelRect(0, 0, 80, 60),))
    poor = World3DPipeline().observe(_frame(), {}, [_track()], scene, observed_at=1.)
    good = World3DPipeline().observe(_textured_frame(), {}, [_track()], scene, observed_at=1.)

    for key in ("brightness", "contrast", "motion_blur_estimate",
                "ui_occlusion_fraction", "scene_visibility_quality"):
        assert key in good.diagnostics
    assert good.diagnostics["scene_visibility_quality"] > poor.diagnostics["scene_visibility_quality"]
    assert good.entity_tracks[0]["effective_confidence"] > poor.entity_tracks[0]["effective_confidence"]
    assert good.entity_tracks[0]["source_confidence"] == poor.entity_tracks[0]["source_confidence"] == .78
    assert good.entity_tracks[0]["confidence_model"]["source_reliability"] == .9
    assert good.diagnostics["ui_occlusion_fraction"] == pytest.approx(.0625)


def test_large_scene_change_is_evidence_event_not_automatic_fact_or_action():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    pipeline.observe(_textured_frame(), {}, [], scene, observed_at=1., frame_id="before")
    changed = pipeline.observe(_textured_frame(invert=True), {}, [], scene,
                               observed_at=1.1, frame_id="after")

    event = next(row for row in changed.frame_events
                 if row["event_type"] == "SCENE_CHANGE_OBSERVED")
    assert event["suggested_effect"] == "CONTEXT_INVALIDATION_CANDIDATE"
    assert event["fact"] is False
    assert event["frame_id"] == "after"
    assert changed.diagnostics["scene_change"]["change_magnitude"] >= .34
    assert validate_batch(changed).valid


def test_pipeline_fuses_mouseover_ground_truth_without_promoting_cv_appearance():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    evidence = [
        {"track_id": "WORLD3D:1", "field": "identity", "label": "Jaina",
         "confidence": 1., "source": "MOUSEOVER_TELEMETRY", "observed_at": 1.,
         "evidence_id": "addon:hover:1", "ground_truth": True},
        {"track_id": "WORLD3D:1", "field": "role", "label": "QUEST_GIVER",
         "confidence": 1., "source": "QUEST_TELEMETRY", "observed_at": 1.,
         "evidence_id": "addon:quest:1", "ground_truth": True},
    ]
    batch = pipeline.observe(_textured_frame(), {"world3d_semantic_evidence": evidence},
                             [_track()], scene, observed_at=1.)
    track = batch.entity_tracks[0]

    assert track["semantic_type"] == "UNKNOWN"
    assert track["identity_belief"]["identity"] == "Jaina"
    assert track["identity_belief"]["fact"] is True
    assert any(belief["label"] == "QUEST_GIVER" and belief["belief"] == "CONFIRMED"
               for belief in track["role_beliefs"])
    appearance = next(belief for belief in track["role_beliefs"]
                      if belief["source"] == "WORLD3D_APPEARANCE")
    assert appearance["fact"] is False and appearance["belief"] == "CANDIDATE"


def test_pipeline_emits_termination_after_lost_track_expires():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    pipeline.observe(_textured_frame(), {}, [_track(lifecycle="LOST_TEMPORARY")],
                     scene, observed_at=1., frame_id="lost")
    ended = pipeline.observe(_textured_frame(), {}, [], scene,
                             observed_at=2., frame_id="gone")

    event = next(row for row in ended.frame_events
                 if row["event_type"] == "WORLD3D_TRACK_TERMINATED")
    assert event["track_id"] == "WORLD3D:1"
    assert event["reason"] == "EXPIRED_AFTER_LOSS"
    assert event["identity_history_retained"] is True
    assert validate_batch(ended).valid


def test_pipeline_death_transition_preserves_alive_to_corpse_continuity():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    corpse = _track("WORLD3D:corpse", candidate_labels=["learned_corpse_like"])
    context = {"world3d_death_events": [{
        "source_entity_track_id": "WORLD3D:alive",
        "corpse_track_id": "WORLD3D:corpse", "source": "COMBAT_LOG",
    }]}
    batch = pipeline.observe(_textured_frame(), context,
                             [_track("WORLD3D:alive"), corpse], scene, observed_at=1.)
    corpse_track = next(row for row in batch.entity_tracks
                        if row["track_id"] == "WORLD3D:corpse")

    assert corpse_track["source_entity_track_id"] == "WORLD3D:alive"
    assert corpse_track["corpse_belief"]["belief"] == "CONFIRMED"
    assert any(row["event_type"] == "WORLD3D_DEATH_TRANSITION"
               for row in batch.frame_events)


def test_quest_search_context_only_raises_unknown_object_role_prior():
    pipeline = World3DPipeline()
    scene = WorldSceneROI(PixelRect(0, 0, 320, 240))
    candidate = _track("WORLD3D:object", detector_kind="unknown_object_candidate",
                       candidate_labels=["learned_object_like"])
    batch = pipeline.observe(_textured_frame(), {"quest_search": True},
                             [candidate], scene, observed_at=1.)
    track = batch.entity_tracks[0]

    assert track["semantic_type"] == "UNKNOWN"
    assert track["object_belief"]["quest_role_belief"] == "CANDIDATE"
    assert "quest_search_context_prior" in track["object_belief"]["evidence"]
    assert track["object_belief"]["fact"] is False


def test_frame_driven_world_lane_processes_each_new_capture_once():
    worker = PerceptionWorker()
    seen = []
    worker._world_v2 = lambda frame, _at, _geometry: (seen.append(frame[0][:1]), ())[1]
    worker._minimap = lambda *_args: ()
    geometry = {"client_id": "pid:42"}
    first = _frame()
    second = (bytes([1]) + first[0][1:], first[1], first[2])
    for at, frame in ((1.0, first), (1.001, first), (1.002, first), (1.003, second)):
        worker.update(frame, at, geometry=geometry, context=("session", "char", 1, 0))
        time.sleep(.02)
    worker.update(second, 1.004, geometry=geometry, context=("session", "char", 1, 0))
    # No time gate between distinct frames, no reprocessing of one frame.
    assert len(seen) == 2
