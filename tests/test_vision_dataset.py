import json

import pytest

from wowbot.agent.vision_dataset import (AutoLabeledExampleCollector, confirmed_mouseover_label,
                                          nearest_subject_candidate)


def _candidate(**overrides):
    base = {"kind": "unknown_subject_candidate", "track_id": 7, "x": .5, "y": .5,
            "bbox": {"left": 10, "top": 10, "right": 40, "bottom": 60}}
    base.update(overrides)
    return base


def _state(**overrides):
    base = {"mouseover": {"guid": "Creature-1", "name": "Murky", "npc_id": 555, "attackable": True},
            "cursor_position": {"nx": .5, "ny": .5},
            "visual_candidates": [_candidate()]}
    base.update(overrides)
    return base


def _raw_frame(width=64, height=64):
    return bytes(width*height*4)


def test_confirmed_mouseover_label_extracts_addon_identity():
    label = confirmed_mouseover_label(_state())
    assert label == {"guid": "Creature-1", "name": "Murky", "npc_id": 555,
                      "attackable": True, "dead": None}


def test_confirmed_mouseover_label_none_without_a_name():
    assert confirmed_mouseover_label({"mouseover": {"guid": "Creature-1"}}) is None


def test_confirmed_mouseover_label_none_for_the_unresolved_placeholder():
    unit = {"guid": "Creature-1", "name": "Unknown until addon"}
    assert confirmed_mouseover_label({"mouseover": unit}) is None


def test_nearest_subject_candidate_within_threshold():
    candidates = [_candidate(x=.51, y=.5)]
    assert nearest_subject_candidate(candidates, .5, .5) is not None


def test_nearest_subject_candidate_none_when_too_far():
    candidates = [_candidate(x=.9, y=.9)]
    assert nearest_subject_candidate(candidates, .5, .5) is None


def test_nearest_subject_candidate_ignores_non_subject_kinds():
    candidates = [_candidate(kind="obstacle_candidate", detector_kind="obstacle_candidate")]
    assert nearest_subject_candidate(candidates, .5, .5) is None


def test_collector_saves_a_full_frame_with_yolo_labels(tmp_path):
    # User 2026-10-04: crops cannot train a detector; full frames + boxes can.
    collector = AutoLabeledExampleCollector(tmp_path)
    written = collector.consider(_raw_frame(), 64, 64, _state(), observed_at=10.0)
    assert written == 1 and collector.saved == 1
    (meta_path,) = list((tmp_path / "meta").glob("*.json"))
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["label"]["name"] == "Murky"
    assert metadata["review_status"] == "NEEDS_REVIEW"
    token = metadata["sample_id"]
    from PIL import Image
    assert Image.open(tmp_path / "images" / f"{token}.jpg").size == (64, 64)
    lines = (tmp_path / "labels" / f"{token}.txt").read_text(encoding="utf-8").split()
    # box 10..40 x 10..60 in a 64x64 frame -> class 0, cx .390625, cy .546875
    assert lines[:5] == ["0", "0.390625", "0.546875", "0.468750", "0.781250"]
    assert "creature_unit_like" in (tmp_path / "data.yaml").read_text(encoding="utf-8")


def test_other_model_detections_become_reviewable_prelabels(tmp_path):
    collector = AutoLabeledExampleCollector(tmp_path)
    others = [
        _candidate(track_id=8, x=.2, y=.2, source="WORLD3D", confidence=.6,
                   bbox={"left": 2, "top": 2, "right": 12, "bottom": 14},
                   appearance={"learned_label_hypothesis": "overhead_symbol_like"}),
        _candidate(track_id=9, x=.8, y=.8, source="WORLD3D", confidence=.6, coasting=True,
                   bbox={"left": 40, "top": 40, "right": 60, "bottom": 62},
                   appearance={"learned_label_hypothesis": "creature_unit_like"}),
        _candidate(track_id=10, x=.8, y=.2, source="WORLD3D", confidence=.1,
                   bbox={"left": 44, "top": 2, "right": 60, "bottom": 20},
                   appearance={"learned_label_hypothesis": "creature_unit_like"}),
    ]
    collector.consider(_raw_frame(), 64, 64, _state(visual_candidates=[_candidate()] + others), observed_at=10.0)
    (meta_path,) = list((tmp_path / "meta").glob("*.json"))
    boxes = json.loads(meta_path.read_text(encoding="utf-8"))["boxes"]
    # The confirmed box plus the symbol; the coasting and low-confidence boxes are skipped.
    assert [(box["source"], box["class_name"]) for box in boxes] == [
        ("ADDON_CONFIRMED_MOUSEOVER", "creature_unit_like"), ("MODEL_PRELABEL", "overhead_symbol_like")]


def test_collector_respects_per_track_cooldown(tmp_path):
    collector = AutoLabeledExampleCollector(tmp_path, cooldown=20.)
    collector.consider(_raw_frame(), 64, 64, _state(), observed_at=10.0)
    written = collector.consider(_raw_frame(), 64, 64, _state(), observed_at=15.0)
    assert written == 0
    assert collector.saved == 1


def test_collector_saves_again_after_cooldown_elapses(tmp_path):
    collector = AutoLabeledExampleCollector(tmp_path, cooldown=5.)
    collector.consider(_raw_frame(), 64, 64, _state(), observed_at=10.0)
    written = collector.consider(_raw_frame(), 64, 64, _state(), observed_at=20.0)
    assert written == 1
    assert collector.saved == 2


def test_collector_stops_at_its_limit(tmp_path):
    collector = AutoLabeledExampleCollector(tmp_path, limit=1, cooldown=1.)
    collector.consider(_raw_frame(), 64, 64, _state(), observed_at=10.0)
    written = collector.consider(_raw_frame(), 64, 64, _state(), observed_at=20.0)
    assert written == 0
    assert collector.saved == 1
    assert collector.diagnostics()["status"] == "limit_reached"


def test_collector_noop_without_a_confirmed_mouseover(tmp_path):
    collector = AutoLabeledExampleCollector(tmp_path)
    state = _state(mouseover={})
    assert collector.consider(_raw_frame(), 64, 64, state, observed_at=10.0) == 0
    assert collector.saved == 0


def test_collector_noop_when_nothing_tracked_near_the_cursor(tmp_path):
    collector = AutoLabeledExampleCollector(tmp_path)
    state = _state(visual_candidates=[_candidate(x=.9, y=.9)])
    assert collector.consider(_raw_frame(), 64, 64, state, observed_at=10.0) == 0


def test_collector_disabled_without_a_directory():
    collector = AutoLabeledExampleCollector(None)
    assert collector.consider(_raw_frame(), 64, 64, _state(), observed_at=10.0) == 0
    assert collector.diagnostics()["status"] == "disabled"


def test_diagnostics_reflects_existing_saved_count_on_reload(tmp_path):
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "meta" / "b.json").write_text("{}", encoding="utf-8")
    (tmp_path / "old_crop.json").write_text("{}", encoding="utf-8")   # legacy crops are not counted
    collector = AutoLabeledExampleCollector(tmp_path)
    assert collector.saved == 2
