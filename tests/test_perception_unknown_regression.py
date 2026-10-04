from pathlib import Path

import numpy as np
import pytest

from wowbot.agent.perception import PerceptionWorker
from wowbot.agent.visual_tracks import VisualTrackManager


def test_live_perception_projection_omits_only_internal_track_histories():
    from wowbot.agent.perception import PerceptionWorker

    tracked = {
        "track_id": "WORLD3D:7", "bbox": {"left": 10}, "confidence": .8,
        "observations": ["o1"], "bbox_history": [{"left": 1}],
        "appearance_history": [{"shape": "subject"}],
        "position_history": [[1.0, .5, .5]], "confidence_history": [.7],
        "candidate_label_history": [["subject_like"]],
    }
    projected = PerceptionWorker._live_projection(tracked)
    assert projected == {"track_id": "WORLD3D:7", "bbox": {"left": 10},
                         "confidence": .8}
    assert tracked["appearance_history"] == [{"shape": "subject"}]
from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel
from wowbot.vision.adapters.minimap import detect_minimap
from wowbot.vision.minimap_geometry import (
    MapCorrespondence, MinimapGeometry, MinimapMapTransformCalibrator,
)
from wowbot.vision.models import MapPoint
from wowbot.vision.world3d.candidates import detect_world_candidates
from wowbot.vision.world3d.scene import build_scene_roi


WORLD_FIXTURE = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Screenshots\WoWScrnShot_090826_101519.jpg")
MINIMAP_FIXTURE = Path(r"C:\Users\<user>\AppData\Local\Temp\codex-clipboard-6ece8a7a-ef73-4cfc-b1a4-33ac09699058.png")


def _bgra(path: Path):
    pil = pytest.importorskip("PIL.Image")
    image = pil.open(path).convert("RGBA")
    return image, np.asarray(image)[:, :, [2, 1, 0, 3]].copy()


@pytest.mark.skipif(not WORLD_FIXTURE.exists(), reason="local real WoW screenshot unavailable")
def test_real_world_screenshot_starts_unknown_and_tracks_overhead_relation():
    image, pixels = _bgra(WORLD_FIXTURE)
    detected = detect_world_candidates(pixels.tobytes(), image.width, image.height,
                                       build_scene_roi(image.width, image.height))
    assert detected
    assert not {c.kind for c in detected} & {"npc_candidate", "mob_candidate", "player_candidate",
                                                   "quest_giver", "quest_turn_in"}
    symbols = [c for c in detected if c.kind == "unknown_symbol_candidate"
               and 680 <= c.rect.left <= 725 and 145 <= c.rect.top <= 205]
    assert symbols, "the visible overhead yellow symbol must be an UNKNOWN symbol candidate"

    worker = PerceptionWorker()
    try:
        for frame in range(3):
            candidates = worker._candidates(detected, image.width, image.height, 1+frame*.2,
                                            raw=pixels.tobytes())
            tracked = worker.visual_tracks.update("WORLD3D", candidates, 1+frame*.2)
    finally:
        worker.close()
    symbol = next(item for item in tracked if item.get("detector_kind") == "unknown_symbol_candidate"
                  and .47 <= item["x"] <= .53 and .75 <= item["y"] <= .84)
    assert symbol["semantic_type"] == "UNKNOWN"
    assert any(edge["type"] == "ABOVE" and edge["belief"] == "SUPPORTED"
               for edge in symbol.get("visual_relations", []))
    assert not symbol["inspectable"]
    related_id = symbol["visual_relations"][0]["subject_track_id"]
    assert next(item for item in tracked if item["track_id"] == related_id)["inspectable"]


@pytest.mark.skipif(not MINIMAP_FIXTURE.exists(), reason="local real minimap screenshot unavailable")
def test_real_minimap_rim_and_four_decorative_arrows_are_not_markers():
    image, pixels = _bgra(MINIMAP_FIXTURE)
    obs = detect_minimap(pixels.tobytes(), image.width, image.height,
                         geometry=MinimapGeometry(.46, .50, .42))
    assert obs.player_marker == MapPoint(round(image.width*.46), round(image.height*.50))
    assert all(marker.marker_type == "unknown_minimap_marker" for marker in obs.markers)
    assert all(marker.relation is None and marker.symbol is None for marker in obs.markers)
    assert all(obs.marker_distance_px(marker) <= obs.usable_radius_px for marker in obs.markers)
    rim_points = (MapPoint(obs.player_marker.x, 12), MapPoint(9, obs.player_marker.y),
                  MapPoint(image.width-9, obs.player_marker.y), MapPoint(obs.player_marker.x, image.height-12))
    assert all(all(((m.position.x-p.x)**2+(m.position.y-p.y)**2)**.5 > 12 for m in obs.markers)
               for p in rim_points)


def test_minimap_world_map_transform_requires_validated_correspondences():
    calibrator = MinimapMapTransformCalibrator()
    calibrator.add(MapCorrespondence(MapPoint(0, 0), MapPoint(.5, .5)))
    calibrator.add(MapCorrespondence(MapPoint(1, 0), MapPoint(.6, .5)))
    assert calibrator.estimate() is None
    calibrator.add(MapCorrespondence(MapPoint(0, 1), MapPoint(.5, .6)))
    candidate = calibrator.estimate()
    assert candidate is not None and candidate.trusted is False
    assert candidate.project(MapPoint(.5, .5)) is None
    validated = MinimapMapTransformCalibrator()
    for pair in calibrator.correspondences:
        validated.add(MapCorrespondence(pair.minimap_local, pair.world_map, validated=True))
    trusted = validated.estimate()
    assert trusted is not None and trusted.trusted is True and trusted.rmse < 1e-9
    assert trusted.project(MapPoint(.5, .5)) is not None


def test_unknown_track_survives_short_occlusion_with_full_history():
    tracks = VisualTrackManager(max_misses=2)
    detection = {"kind": "unknown_subject_candidate", "x": .4, "y": .6, "confidence": .7,
                 "bbox": {"left": 10, "top": 20, "right": 30, "bottom": 70},
                 "appearance": {"shape": "subject_like"}}
    first = tracks.update("WORLD3D", [detection], 1.)[0]
    tracks.update("WORLD3D", [], 2.)
    second = tracks.update("WORLD3D", [detection], 3.)[0]
    assert first["track_id"] == second["track_id"]
    assert len(second["observations"]) == 2
    assert len(second["bbox_history"]) == 2 and len(second["appearance_history"]) == 2


def test_cursor_and_tooltip_probe_do_not_reset_perception_context():
    worker = PerceptionWorker()
    try:
        dimensions = (1177, 552)
        context = ("session", "character", 1409, 0)
        first = worker._stable_context_key(context, dimensions, True, {
            "visible": True, "center_x": .9, "center_y": .15,
            "radius_fraction": .08, "cursor_position": {"nx": .1, "ny": .2},
            "tooltip_probe": False})
        hover = worker._stable_context_key(context, dimensions, True, {
            "visible": True, "center_x": .9, "center_y": .15,
            "radius_fraction": .08, "cursor_position": {"nx": .8, "ny": .7},
            "tooltip_probe": True})
        changed_map = worker._stable_context_key(("session", "character", 1411, 0),
                                                  dimensions, True, {"visible": True})
        assert first == hover
        assert first != changed_map
    finally:
        worker.close()


def test_stable_isolated_symbol_creates_subject_probe_not_symbol_hover():
    tracks = VisualTrackManager()
    symbol = {"kind": "unknown_symbol_candidate", "x": .5, "y": .8, "confidence": .8,
              "bbox": {"left": 90, "top": 40, "right": 105, "bottom": 65}}
    for frame in range(5):
        items = tracks.update("WORLD3D", [symbol], float(frame))
    symbol_track = next(item for item in items if item["detector_kind"] == "unknown_symbol_candidate")
    probe = next(item for item in items if item["detector_kind"] == "unknown_subject_probe")
    assert symbol_track["inspectable"] is False
    assert probe["semantic_type"] == "UNKNOWN" and probe["inspectable"] is True
    assert any(edge["type"] == "ABOVE" for edge in symbol_track["visual_relations"])


def test_tiny_colour_fragment_below_stable_symbol_does_not_suppress_subject_probe():
    tracks = VisualTrackManager()
    symbol = {"kind": "unknown_symbol_candidate", "x": .52, "y": .66, "confidence": .72,
              "stable_frames": 1, "bbox_height_fraction": 21/552,
              "bbox": {"left": 598, "top": 179, "right": 610, "bottom": 200},
              "appearance": {"track_hits": 4, "screen_center_relevance": .96,
                             "hue_family": "yellow"}}
    fragment = {"kind": "unknown_subject_candidate", "x": .517, "y": .63,
                "confidence": .62,
                "bbox": {"left": 598, "top": 201, "right": 610, "bottom": 210}}
    for frame in range(3):
        items = tracks.update("WORLD3D", [symbol, fragment], float(frame))
    probe = next(item for item in items if item["detector_kind"] == "unknown_subject_probe")
    assert probe["inspectable"] is True
    assert probe["x"] == symbol["x"] and probe["y"] < symbol["y"]
    assert probe["servo_scale_fraction"] == symbol["bbox_height_fraction"]
    assert probe["appearance"]["anchor_bbox_height_fraction"] == symbol["bbox_height_fraction"]
    assert (probe["bbox"]["right"]-probe["bbox"]["left"]) >= 72
    assert any(edge["type"] == "ABOVE" and edge["belief"] == "SUPPORTED"
               for edge in probe["visual_relations"])


def test_learned_overhead_symbol_never_invents_a_subject_probe():
    tracks = VisualTrackManager()
    symbol = {
        "kind": "unknown_symbol_candidate", "x": .52, "y": .66,
        "confidence": .72, "stable_frames": 4,
        "bbox_width_fraction": 18/892, "bbox_height_fraction": 25/502,
        "bbox": {"left": 598, "top": 179, "right": 616, "bottom": 204},
        "candidate_labels": ["learned_symbol_like"],
        "appearance": {
            "track_hits": 4,
            "source_detector": "ultralytics-yolo",
            "learned_label_hypothesis": "overhead_symbol_like",
        },
    }

    for frame in range(4):
        items = tracks.update("WORLD3D", [symbol], float(frame))

    assert any(item["detector_kind"] == "unknown_symbol_candidate" for item in items)
    assert not any(item["detector_kind"] == "unknown_subject_probe" for item in items)


def test_real_body_relation_is_preferred_over_a_derived_probe():
    symbol = {
        "detector_kind": "unknown_symbol_candidate", "track_id": "WORLD3D:symbol",
        "x": .50, "y": .70, "stable_frames": 5, "candidate_labels": [],
    }
    probe = {
        "detector_kind": "unknown_subject_probe", "kind": "unknown_subject_probe",
        "track_id": "WORLD3D:probe", "x": .50, "y": .62, "stable_frames": 3,
        "bbox": {"left": 450, "top": 210, "right": 530, "bottom": 330},
        "appearance": {"anchor_track_hits": 5},
    }
    body = {
        "detector_kind": "unknown_subject_candidate", "kind": "unknown_subject_candidate",
        "track_id": "WORLD3D:body", "x": .505, "y": .61, "stable_frames": 4,
        "bbox": {"left": 470, "top": 215, "right": 515, "bottom": 315},
        "appearance": {"learned_label_hypothesis": "humanoid_unit_like"},
    }

    VisualTrackManager._relations([symbol, probe, body])

    assert symbol["visual_group"]["subject_track_id"] == "WORLD3D:body"
    assert body["visual_group"]["symbol_track_id"] == "WORLD3D:symbol"
    assert "visual_group" not in probe


def test_patch_only_detector_dropout_is_visible_but_not_inspectable():
    tracks = VisualTrackManager()
    body = {
        "kind": "unknown_subject_candidate", "x": .5, "y": .5,
        "confidence": .7,
        "bbox": {"left": 100, "top": 80, "right": 150, "bottom": 190},
        "bbox_width_fraction": 50/320, "bbox_height_fraction": 110/240,
        "appearance": {"detector_miss_streak": 1, "tracking_only": True},
    }

    item = tracks.update("WORLD3D", [body], 1.)[0]

    assert item["lifecycle"] == "OCCLUDED"
    assert item["temporal_state"] == "PREDICTED"
    assert item["inspectable"] is False


def test_bottom_edge_symbol_never_creates_an_off_frame_subject_probe():
    tracks = VisualTrackManager()
    symbol = {"kind": "unknown_symbol_candidate", "x": .82, "y": .01,
              "confidence": .78, "stable_frames": 3,
              "bbox_width_fraction": 18/892, "bbox_height_fraction": 25/502,
              "bbox": {"left": 720, "top": 476, "right": 738, "bottom": 501},
              "appearance": {"track_hits": 4}}

    items = tracks.update("WORLD3D", [symbol], 1.)

    assert not any(item["detector_kind"] == "unknown_subject_probe" for item in items)


def test_stable_unknown_minimap_marker_is_inspectable_but_direction_hint_is_not():
    tracks = VisualTrackManager()
    marker = {"kind": "unknown_minimap_marker", "x": .6, "y": .6, "confidence": .7,
              "candidate_labels": ["salient_marker_like"], "inspectable": False}
    direction = {"kind": "unknown_minimap_marker", "x": .7, "y": .7, "confidence": .7,
                 "candidate_labels": ["gold_direction_like"], "inspectable": False}
    for frame in range(3):
        items = tracks.update("MINIMAP_CV", [marker, direction], float(frame))
    assert next(i for i in items if i["x"] == .6)["inspectable"] is True
    assert next(i for i in items if i["x"] == .7)["inspectable"] is False


def test_unknown_visual_track_enters_evidence_and_belief_without_becoming_fact():
    world = WorldModel()
    world.ingest(Observation.create({"session_id": "unknown-first", "active_quests": []}, 1.0))
    item = {"track_id": "WORLD3D:7", "kind": "unknown_subject_candidate",
            "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
            "confidence": .72, "appearance": {"shape": "subject_like"},
            "candidate_labels": ["possible_nameplate_like"]}
    visual = Observation.create({"session_id": world.session_id, "surface": "WORLD3D",
                                 "visual_candidates": [item], "confidence": .72},
                                1.1, "WORLD3D")
    assert world.ingest(visual)
    belief = world.query.visual_track_belief("WORLD3D:7", 1.2)
    assert belief["status"] == "SUPPORTED"
    assert belief["value"]["semantic_type"] == "UNKNOWN"
    assert world.query.visual_tracks(kind="unknown_subject_candidate")[0]["semantic_type"] == "UNKNOWN"
