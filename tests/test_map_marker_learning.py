"""Map-marker YOLO pipeline: canvas geometry, proposals, learned adapter,
collector, review pool/export and the quest-class training gate."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

from wowbot.agent.map_marker_dataset import MapMarkerCropCollector, state_snapshot
from wowbot.vision import map_markers
from wowbot.vision.map_marker_dataset import (assign_split, build_review_pool, export_dataset,
                                              quest_class_coverage)
from wowbot.vision.map_markers import (CLASS_APPEARANCE_LABELS, MAP_MARKER_YOLO_CLASSES,
                                       LearnedMapMarkerDetector, fast_world_map_hints,
                                       map_yolo_line, merge_minimap_markers, minimap_crop,
                                       world_map_crop, world_map_proposals)
from wowbot.vision.models import MapPoint, MarkerObservation
from wowbot.vision.world3d.learned_detector import LearnedDetection
from wowbot.vision.world_map_calibration import estimate_world_map_canvas
from wowbot.vision.world_map_perception import WorldMapMarkerDetector

WIDTH, HEIGHT = 843, 475
CANVAS = (90, 31, 752, 472)  # measured live layout at this capture size


def _map_frame(player=(0.6182, 0.8328), *, gold=(), blue=None):
    """Synthetic full-screen map: black backdrop, parchment canvas, white arrow."""
    frame = np.zeros((HEIGHT, WIDTH, 4), np.uint8)
    frame[:, :, 3] = 255
    left, top, right, bottom = CANVAS
    frame[top:bottom + 1, left:right + 1, :3] = (110, 150, 170)  # BGR parchment
    frame[8:24, left:right + 1, :3] = (40, 40, 40)  # title/navigation strip
    if player is not None:
        px = round(left + player[0] * (right - left))
        py = round(top + (bottom - top) - (right - left) / (1002 / 668) * (1 - player[1]))
        frame[py - 4:py + 5, px - 3:px + 3, :3] = 240
    for gx, gy in gold:
        frame[gy - 3:gy + 4, gx - 2:gx + 2, :3] = (40, 180, 230)
    if blue is not None:
        bl, bt, br, bb = blue
        frame[bt:bb, bl:br, :3] = (200, 120, 60)
    return frame


def test_canvas_estimator_finds_full_screen_map_and_rejects_3d_frames():
    canvas = estimate_world_map_canvas(_map_frame())
    assert canvas is not None
    assert abs(canvas.left_px - CANVAS[0]) <= 3 and abs(canvas.right_px - CANVAS[2]) <= 3
    assert abs(canvas.bottom_px - CANVAS[3]) <= 3
    world = np.full((HEIGHT, WIDTH, 4), 90, np.uint8)
    assert estimate_world_map_canvas(world) is None
    crop, _, estimated = world_map_crop(world, WIDTH, HEIGHT)
    assert not estimated and crop.source == "LEGACY_CONSTANTS"


def test_projection_is_verified_against_the_detected_player_arrow():
    frame = _map_frame()
    crop, canvas, estimated = world_map_crop(frame, WIDTH, HEIGHT)
    player, _ = fast_world_map_hints(frame[crop.top:crop.bottom, crop.left:crop.right, :3])
    assert player is not None
    player_px = MapPoint(player.x + crop.left, player.y + crop.top)
    state = {"map_id": 1409, "position": {"x": .6182, "y": .8328},
             "quests": [{"quest_id": 1, "is_complete": False},
                        {"quest_id": 2, "is_complete": True}],
             "quest_locations": [{"quest_id": 1, "map_id": 1409, "x": .40, "y": .50},
                                 {"quest_id": 2, "map_id": 1409, "x": .55, "y": .30},
                                 {"quest_id": 3, "map_id": 999, "x": .1, "y": .1}]}
    proposals, verification = world_map_proposals(
        crop=crop, canvas=canvas, canvas_estimated=estimated, state=state, player_pixel=player_px)
    assert verification["projection_verified"], verification
    names = sorted(p["class_name"] for p in proposals)
    assert names == ["player_arrow", "quest_objective_pin", "quest_turn_in"]
    pin = next(p for p in proposals if p["class_name"] == "quest_objective_pin")
    ex, ey = canvas.map_to_pixel(.40, .50)
    assert abs((pin["left"] + pin["right"]) / 2 + crop.left - ex) <= 1
    assert abs((pin["top"] + pin["bottom"]) / 2 + crop.top - ey) <= 1


def test_unverified_projection_never_emits_poi_proposals():
    frame = _map_frame()
    crop, canvas, estimated = world_map_crop(frame, WIDTH, HEIGHT)
    state = {"position": {"x": .2, "y": .2},  # e.g. zoomed/panned map
             "quest_locations": [{"quest_id": 1, "x": .4, "y": .5}]}
    proposals, verification = world_map_proposals(
        crop=crop, canvas=canvas, canvas_estimated=estimated, state=state,
        player_pixel=MapPoint(500, 400))
    assert not verification["projection_verified"]
    assert [p["class_name"] for p in proposals] == ["player_arrow"]


def test_tooltip_confirmed_hover_becomes_a_proposal_at_the_cursor():
    frame = _map_frame(player=None)
    crop, canvas, estimated = world_map_crop(frame, WIDTH, HEIGHT)
    state = {"map_mouseover": {"surface": "WORLD_MAP", "semantic_type": "QUEST_GIVER",
                               "tooltip": "Available quest"}}
    proposals, _ = world_map_proposals(crop=crop, canvas=canvas, canvas_estimated=estimated,
                                       state=state, player_pixel=None, cursor_pixel=(300, 200))
    assert [p["class_name"] for p in proposals] == ["quest_available"]
    assert proposals[0]["source"] == "ADDON_MAP_MOUSEOVER_TOOLTIP"


class _Backend:
    def __init__(self, detections, status="ready", error=None):
        self.detections, self.status, self.error = detections, status, error

    def predict(self, _image, *, confidence, iou):
        if self.error:
            raise self.error
        return self.detections


def test_learned_adapter_publishes_unknown_markers_with_appearance_labels():
    backend = _Backend([
        LearnedDetection("quest_available", .9, 10, 10, 20, 22),
        LearnedDetection("quest_area", .7, 40, 40, 90, 80),
        LearnedDetection("player_arrow", .8, 100, 100, 110, 112),
        LearnedDetection("npc_body", .99, 0, 0, 5, 5),  # foreign vocabulary: ignored
    ])
    markers, player = LearnedMapMarkerDetector(backend, surface="WORLD_MAP").detect(
        np.zeros((200, 200, 3), np.uint8), offset=(100, 50))
    assert player == MapPoint(205, 156)
    by_type = {m.marker_type: m for m in markers}
    assert set(by_type) == {"unknown_world_map_marker", "unknown_world_map_area"}
    offer = by_type["unknown_world_map_marker"]
    assert offer.bbox == (110, 60, 120, 72)
    assert "quest_available_like" in offer.candidate_labels
    assert "learned_map_marker_like" in offer.candidate_labels
    assert offer.evidence[0] == "appearance_only"
    assert "blue_region_like" in by_type["unknown_world_map_area"].candidate_labels


def test_learned_adapter_failure_is_not_fatal():
    detector = LearnedMapMarkerDetector(_Backend([], error=RuntimeError("cuda")),
                                        surface="MINIMAP")
    assert detector.detect(np.zeros((8, 8, 3), np.uint8)) == ([], None)
    assert "cuda" in detector.last_error


def test_every_class_has_appearance_labels_and_yolo_lines_validate():
    assert set(CLASS_APPEARANCE_LABELS) == set(MAP_MARKER_YOLO_CLASSES)
    assert map_yolo_line(0, 10, 20, 30, 40, 100, 100) == "0 0.200000 0.300000 0.200000 0.200000"
    with pytest.raises(ValueError):
        map_yolo_line(len(MAP_MARKER_YOLO_CLASSES), 0, 0, 5, 5, 10, 10)


def test_world_map_detector_uses_learned_markers_only_when_ready():
    frame = _map_frame(gold=[(300, 200), (400, 300)], blue=(560, 120, 640, 180))
    raw = frame.tobytes()
    heuristic = WorldMapMarkerDetector(learned=None).detect((raw, WIDTH, HEIGHT), 1., {})
    assert any("gold_glyph_like" in m.candidate_labels for m in heuristic.markers)
    warming = WorldMapMarkerDetector(learned=LearnedMapMarkerDetector(
        _Backend([], status="warming"), surface="WORLD_MAP"))
    assert warming.detect((raw, WIDTH, HEIGHT), 1., {}).markers == heuristic.markers
    ready = WorldMapMarkerDetector(learned=LearnedMapMarkerDetector(
        _Backend([LearnedDetection("quest_turn_in", .8, 5, 5, 17, 19)]), surface="WORLD_MAP"))
    observation = ready.detect((raw, WIDTH, HEIGHT), 1., {})
    labels = [m.candidate_labels for m in observation.markers]
    assert not any("gold_glyph_like" in item for item in labels)
    assert any("quest_turn_in_like" in item for item in labels)
    assert any("blue_region_like" in item for item in labels)  # heuristic area kept
    assert observation.player_marker == heuristic.player_marker


def test_minimap_merge_keeps_heuristics_and_adds_new_learned_markers():
    heuristic = [MarkerObservation("unknown_minimap_marker", MapPoint(50, 50), .8,
                                   candidate_labels=("exclamation_symbol_like",))]
    learned = [MarkerObservation("unknown_minimap_marker", MapPoint(52, 51), .9,
                                 candidate_labels=("quest_available_like",)),
               MarkerObservation("unknown_minimap_marker", MapPoint(90, 20), .7,
                                 candidate_labels=("quest_turn_in_like",))]
    merged = merge_minimap_markers(learned, heuristic)
    assert [m.position for m in merged] == [MapPoint(50, 50), MapPoint(90, 20)]


def test_minimap_crop_from_addon_geometry():
    crop = minimap_crop({"center_x": .93, "center_y": .12, "radius_fraction": .1,
                         "visible": True}, 1920, 1080)
    assert crop is not None and abs(crop.width - crop.height) <= 1
    assert minimap_crop({"center_x": .93, "center_y": .12, "radius_fraction": .5}, 1920, 1080) is None
    assert minimap_crop(None, 1920, 1080) is None


def test_runtime_model_path_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AIPC_MAP_MARKER_MODEL", "0")
    assert map_markers.runtime_model_path("WORLD_MAP") is None
    monkeypatch.setenv("AIPC_MAP_MARKER_MODEL", "1")
    monkeypatch.setenv("AIPC_MINIMAP_MODEL", str(tmp_path / "m.pt"))
    assert map_markers.runtime_model_path("MINIMAP") == tmp_path / "m.pt"


def _collector_state(**overrides):
    state = {"session_id": "s1", "world_map_open": True, "map_id": 1409,
             "position": {"x": .6182, "y": .8328},
             "quests": [{"quest_id": 7, "title": "Q", "is_complete": False}],
             "quest_locations": [{"quest_id": 7, "map_id": 1409, "x": .4, "y": .5}],
             "cursor_position": {"nx": .1, "ny": .9}}
    state.update(overrides)
    return state


def test_collector_saves_world_map_crop_with_verified_proposals(tmp_path):
    collector = MapMarkerCropCollector(tmp_path, background=False)
    raw = _map_frame().tobytes()
    assert collector.consider(raw, WIDTH, HEIGHT, _collector_state(), 10.) == 1
    meta = json.loads(next((tmp_path / "world_map" / "meta").glob("*.json")).read_text("utf-8"))
    assert meta["label_status"] == "UNLABELED_MAP_CROP"
    assert meta["verification"]["projection_verified"]
    assert {p["class_name"] for p in meta["proposals"]} == {"player_arrow", "quest_objective_pin"}
    assert (tmp_path / "world_map" / meta["image"]).is_file()
    # Interval gate, then content/facts dedupe.
    assert collector.consider(raw, WIDTH, HEIGHT, _collector_state(), 10.5) == 0
    assert collector.consider(raw, WIDTH, HEIGHT, _collector_state(), 12.) == 0
    assert collector.skipped_duplicates == 1
    changed = _collector_state(quests=[{"quest_id": 7, "is_complete": True}])
    assert collector.consider(raw, WIDTH, HEIGHT, changed, 14.) == 1
    assert collector.diagnostics()["saved"]["WORLD_MAP"] == 2


def test_collector_saves_minimap_crops_and_respects_limits(tmp_path):
    collector = MapMarkerCropCollector(tmp_path, background=False, minimap_limit=1)
    frame = np.full((HEIGHT, WIDTH, 4), 60, np.uint8)
    state = {"session_id": "s1", "minimap_geometry": {
        "center_x": .93, "center_y": .12, "radius_fraction": .1, "visible": True}}
    assert collector.consider(frame.tobytes(), WIDTH, HEIGHT, state, 1.) == 1
    assert list((tmp_path / "minimap" / "images").glob("*.png"))
    assert collector.consider(frame.tobytes(), WIDTH, HEIGHT, state, 100.) == 0
    assert MapMarkerCropCollector(None).consider(frame.tobytes(), WIDTH, HEIGHT, state, 1.) == 0


def test_state_snapshot_is_json_safe_and_bounded():
    snapshot = state_snapshot({**_collector_state(), "secret_unrelated": object()})
    assert "secret_unrelated" not in snapshot
    json.dumps(snapshot)


def _reviewed_pool(tmp_path, groups):
    source = tmp_path / "collected"
    collector = MapMarkerCropCollector(source, background=False, world_map_interval=.2)
    at = 0.
    for group, count in groups.items():
        for index in range(count):
            at += 1.
            state = _collector_state(session_id=group,
                                     quests=[{"quest_id": index, "is_complete": False}])
            collector.consider(_map_frame().tobytes(), WIDTH, HEIGHT, state, at)
    dataset = tmp_path / "dataset"
    result = build_review_pool([source], dataset, surface="WORLD_MAP")
    assert result["added"] == sum(groups.values())
    # Rerun is idempotent.
    assert build_review_pool([source], dataset, surface="WORLD_MAP")["added"] == 0
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from review_map_marker_annotations import MapReviewer
    reviewer = MapReviewer(dataset)
    for index in range(len(reviewer.records)):
        reviewer.index = index
        reviewer.load()
        for box in reviewer.boxes:
            box.status = "ACCEPTED"
        reviewer.save()
    return dataset


def test_review_export_splits_whole_groups_and_gates_training(tmp_path):
    dataset = _reviewed_pool(tmp_path, {"a": 2, "b": 2, "c": 2, "d": 2})
    summary = export_dataset(dataset)
    seen = {}
    for split in ("train", "val", "test"):
        images = list((dataset / "images" / split).glob("*"))
        labels = list((dataset / "labels" / split).glob("*.txt"))
        assert len(images) == len(labels)
        for group in summary["groups"][split]:
            assert group not in seen
            seen[group] = split
    assert all(summary["frames"].get(split) for split in ("train", "val", "test"))
    assert "player_arrow" in summary["class_counts"]["train"]
    gate = quest_class_coverage(summary, minimum_train=1, minimum_val=1)
    # Only the (projected) objective pin is a quest class here.
    assert gate["ready_classes"] == ["quest_objective_pin"]
    arrow_only = {"class_counts": {"train": {"player_arrow": 500}, "val": {"player_arrow": 80}}}
    assert not quest_class_coverage(arrow_only)["training_ready"]
    assert (dataset / "data.yaml").read_text("utf-8").count("player_arrow") == 1


def test_split_assignment_is_deterministic():
    assert assign_split("session-x") == assign_split("session-x")
    assert assign_split("anything") in {"train", "val", "test"}


def test_perception_lane_map_local_position_uses_estimated_canvas():
    import time
    from wowbot.agent.perception import PerceptionWorker
    frame = _map_frame(player=None)
    canvas = estimate_world_map_canvas(frame)
    px, py = canvas.map_to_pixel(.4, .5)
    marker = MarkerObservation("unknown_world_map_marker", MapPoint(round(px), round(py)), .8,
                               candidate_labels=("quest_available_like",),
                               bbox=(round(px) - 5, round(py) - 5, round(px) + 5, round(py) + 5))
    worker = PerceptionWorker()
    worker.pipeline._world_map = lambda *_: [marker]
    items = []
    try:
        for step in range(40):
            items = worker.update((frame.tobytes(), WIDTH, HEIGHT), 1. + step * .6,
                                  world_map_open=True)
            if any(item.get("source") == "WORLD_MAP_CV" for item in items):
                break
            time.sleep(.02)
    finally:
        worker.close()
    item = next(item for item in items if item.get("source") == "WORLD_MAP_CV")
    local = item["map_local_position"]
    assert abs(local["x"] - .4) < .004 and abs(local["y"] - .5) < .004, local
    assert "quest_available_like" in item["candidate_labels"]
