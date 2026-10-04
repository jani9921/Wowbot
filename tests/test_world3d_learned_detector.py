from __future__ import annotations

from pathlib import Path

from wowbot.vision.world3d import (
    LearnedDetection,
    LearnedWorldDetector,
    PixelRect,
    World3DPerceptionV2,
    WorldSceneROI,
    audit_yolo_dataset,
)
from wowbot.vision.world3d.learned_detector import (
    RUNTIME_ENGINE_NAME,
    RUNTIME_MODEL_NAME,
    RUNTIME_SUBJECT_CONFIDENCE,
    default_runtime_model_path,
)


def test_default_runtime_model_revision_is_units_3class_v10_e65(monkeypatch) -> None:
    monkeypatch.delenv("AIPC_WORLD3D_MODEL", raising=False)

    assert RUNTIME_MODEL_NAME == "world3d_units_3class_v10_e65.pt"
    assert RUNTIME_ENGINE_NAME == "world3d_units_3class_v10_e65.engine"
    assert default_runtime_model_path().name == RUNTIME_ENGINE_NAME
    assert RUNTIME_SUBJECT_CONFIDENCE == .15


class _Backend:
    name = "fake_yolo"

    def __init__(self, detections):
        self.detections = detections

    def predict(self, _bgr_roi, *, confidence: float, iou: float):
        assert confidence == .30
        assert iou == .45
        return self.detections


class _AdaptiveBackend(_Backend):
    def __init__(self, detections):
        super().__init__(detections)
        self.sizes = []
        self.shapes = []
        self.frames = []

    def predict_at_size(self, bgr_roi, *, confidence: float, iou: float,
                        image_size: int):
        self.sizes.append(image_size)
        self.shapes.append(tuple(bgr_roi.shape))
        self.frames.append(bgr_roi.copy())
        return super().predict(bgr_roi, confidence=confidence, iou=iou)


class _LowConfidenceBackend:
    name = "fake_low_confidence_yolo"

    def predict(self, _bgr_roi, *, confidence: float, iou: float):
        assert confidence == .01
        assert iou == .45
        return (
            LearnedDetection("overhead_symbol_like", .02, 40, 5, 48, 18),
            LearnedDetection("humanoid_unit_like", .02, 35, 20, 55, 70),
        )


def _frame(width: int = 100, height: int = 80) -> bytes:
    return bytes(width * height * 4)


def test_learned_npc_label_remains_unknown_visual_evidence() -> None:
    detector = LearnedWorldDetector(_Backend([
        LearnedDetection("npc_body", .88, 10, 5, 40, 55),
    ]))
    scene = WorldSceneROI(PixelRect(5, 10, 95, 75))

    result = detector.detect(_frame(), 100, 80, scene)

    assert len(result) == 1
    candidate = result[0]
    assert candidate.kind == "unknown_subject_candidate"
    assert candidate.rect == PixelRect(15, 15, 45, 65)
    assert candidate.appearance["learned_label_hypothesis"] == "npc_body"
    assert candidate.appearance["semantic_status"] == "UNCONFIRMED"
    assert candidate.candidate_labels == ("learned_subject_like",)
    assert "NPC" not in candidate.candidate_labels


def test_learned_detector_respects_excluded_ui_regions() -> None:
    detector = LearnedWorldDetector(_Backend([
        LearnedDetection("world_object_like", .90, 0, 0, 30, 20),
        LearnedDetection("symbol", .80, 50, 20, 58, 32),
    ]))
    scene = WorldSceneROI(PixelRect(0, 0, 100, 80),
                          excluded_rects=(PixelRect(0, 0, 35, 25),))

    result = detector.detect(_frame(), 100, 80, scene)

    assert len(result) == 1
    assert result[0].kind == "unknown_symbol_candidate"
    assert result[0].candidate_labels == ("learned_symbol_like",)


def test_learned_detector_sees_overhead_marker_above_heuristic_scene_crop() -> None:
    backend = _AdaptiveBackend([
        LearnedDetection("overhead_symbol_like", .80, 45, 55, 55, 72),
    ])
    detector = LearnedWorldDetector(backend, adaptive_sampling=False)
    scene = WorldSceneROI(
        PixelRect(0, 92, 100, 180),
        excluded_rects=(PixelRect(0, 0, 100, 92),),
        learned_rect=PixelRect(0, 12, 100, 180),
    )

    result = detector.detect(_frame(100, 200), 100, 200, scene)

    assert backend.shapes == [(168, 100, 3)]
    assert len(result) == 1
    assert result[0].kind == "unknown_symbol_candidate"
    assert result[0].rect == PixelRect(45, 67, 55, 84)


def test_learned_subject_survives_broad_hud_overlay_intersection() -> None:
    detector = LearnedWorldDetector(_Backend([
        LearnedDetection("creature_unit_like", .84, 70, 20, 98, 70),
    ]))
    scene = WorldSceneROI(
        PixelRect(0, 0, 100, 80),
        excluded_rects=(PixelRect(65, 10, 100, 80),),
    )

    result = detector.detect(_frame(), 100, 80, scene)

    assert len(result) == 1
    assert result[0].kind == "unknown_subject_candidate"
    assert result[0].appearance["learned_label_hypothesis"] == "creature_unit_like"


def test_learned_subject_and_symbol_do_not_survive_hard_ui_masks() -> None:
    backend = _AdaptiveBackend([
        LearnedDetection("creature_unit_like", .84, 70, 20, 98, 70),
        LearnedDetection("overhead_symbol_like", .80, 75, 25, 85, 40),
    ])
    detector = LearnedWorldDetector(backend)
    hard_ui = PixelRect(65, 10, 100, 80)
    scene = WorldSceneROI(
        PixelRect(0, 0, 100, 80),
        excluded_rects=(hard_ui,),
        hard_excluded_rects=(hard_ui,),
    )

    result = detector.detect(bytes([255]) * (100 * 80 * 4), 100, 80, scene)

    assert result == ()
    assert backend.frames[0][20, 70].tolist() == [0, 0, 0]
    assert backend.frames[0][5, 5].tolist() == [255, 255, 255]
    assert detector.last_diagnostics["rejected_by_ui_exclusion"] == 2
    assert detector.last_diagnostics["masked_hard_ui_regions"] == 1


def test_learned_subject_inside_self_avatar_region_is_preserved_as_unknown() -> None:
    detector = LearnedWorldDetector(_Backend([
        LearnedDetection("humanoid_unit_like", .80, 40, 35, 60, 75),
    ]))
    self_region = PixelRect(35, 30, 65, 80)
    scene = WorldSceneROI(
        PixelRect(0, 0, 100, 80), excluded_rects=(self_region,),
        self_avatar_rect=self_region,
    )

    result = detector.detect(_frame(), 100, 80, scene)

    assert len(result) == 1
    assert result[0].kind == "unknown_subject_candidate"
    assert result[0].appearance["possible_self_avatar_overlap"] is True
    assert result[0].appearance["self_avatar_region_overlap"] == 1.0
    assert detector.last_diagnostics["rejected_as_self_avatar"] == 0
    assert detector.last_diagnostics["self_avatar_overlap_candidates"] == 1


def test_learned_symbol_inside_self_avatar_region_is_not_treated_as_hud() -> None:
    detector = LearnedWorldDetector(_Backend([
        LearnedDetection("overhead_symbol_like", .80, 45, 35, 55, 50),
    ]))
    self_region = PixelRect(35, 30, 65, 80)
    scene = WorldSceneROI(
        PixelRect(0, 0, 100, 80), excluded_rects=(self_region,),
        self_avatar_rect=self_region,
    )

    result = detector.detect(_frame(), 100, 80, scene)

    assert len(result) == 1
    assert result[0].kind == "unknown_symbol_candidate"
    assert result[0].appearance["possible_self_avatar_overlap"] is True


def test_learned_corpse_interact_and_quest_object_labels_remain_unknown_cues() -> None:
    detector = LearnedWorldDetector(_Backend([
        LearnedDetection("corpse", .91, 5, 5, 25, 25),
        LearnedDetection("interact_icon", .85, 30, 5, 40, 20),
        LearnedDetection("quest_object", .82, 45, 5, 70, 30),
    ]))
    result = detector.detect(_frame(), 100, 80, WorldSceneROI(PixelRect(0, 0, 100, 80)))

    assert [candidate.kind for candidate in result] == [
        "unknown_subject_candidate", "unknown_symbol_candidate", "unknown_object_candidate"]
    assert "learned_corpse_like" in result[0].candidate_labels
    assert "interact_cue_like" in result[1].candidate_labels
    assert "quest_object_like" in result[2].candidate_labels
    assert all(candidate.appearance["semantic_status"] == "UNCONFIRMED" for candidate in result)


def test_training_taxonomy_maps_to_unknown_first_visual_families() -> None:
    detector = LearnedWorldDetector(_Backend([
        LearnedDetection("humanoid_unit_like", .95, 2, 2, 18, 40),
        LearnedDetection("creature_unit_like", .94, 20, 2, 40, 35),
        LearnedDetection("corpse_like", .93, 42, 20, 65, 35),
        LearnedDetection("quest_object_outline_like", .92, 67, 5, 82, 30),
        LearnedDetection("world_object_like", .91, 5, 45, 25, 70),
        LearnedDetection("overhead_symbol_like", .90, 30, 40, 38, 50),
        LearnedDetection("entrance_or_door_like", .89, 50, 40, 80, 75),
    ]))

    result = detector.detect(
        _frame(), 100, 80, WorldSceneROI(PixelRect(0, 0, 100, 80)))

    assert [candidate.kind for candidate in result] == [
        "unknown_subject_candidate",
        "unknown_subject_candidate",
        "unknown_subject_candidate",
        "unknown_object_candidate",
        "unknown_object_candidate",
        "unknown_symbol_candidate",
        "unknown_scene_candidate",
    ]
    assert "outline_like_cue" in result[3].candidate_labels
    assert "learned_corpse_like" in result[2].candidate_labels
    assert all(candidate.appearance["semantic_status"] == "UNCONFIRMED" for candidate in result)


def test_v2_adds_learned_candidates_without_replacing_cheap_detectors() -> None:
    detector = LearnedWorldDetector(_Backend([
        LearnedDetection("npc_body", .91, 35, 15, 55, 55),
    ]))
    perception = World3DPerceptionV2(learned_detector=detector)
    scene = WorldSceneROI(PixelRect(0, 0, 100, 80))

    result = perception.process(_frame(), 100, 80, scene)

    assert any(item.appearance.get("source_detector") == "fake_yolo" for item in result)
    assert perception.last_diagnostics["learned_candidates"] == 1
    assert "legacy_candidates" in perception.last_diagnostics
    assert "generic_candidates" in perception.last_diagnostics


def test_yolo_only_mode_forbids_legacy_and_generic_candidate_boxes() -> None:
    detector = LearnedWorldDetector(_Backend([
        LearnedDetection("overhead_symbol_like", .91, 35, 15, 55, 55),
    ]), confidence=.30)
    perception = World3DPerceptionV2(
        learned_detector=detector, proposal_mode="YOLO_ONLY")
    scene = WorldSceneROI(PixelRect(0, 0, 100, 80))

    result = perception.process(_frame(), 100, 80, scene)

    assert len(result) == 1
    assert result[0].appearance.get("source_detector") == "fake_yolo"
    assert perception.last_diagnostics["proposal_mode"] == "YOLO_ONLY"
    assert perception.last_diagnostics["legacy_candidates"] == 0
    assert perception.last_diagnostics["generic_candidates"] == 0


def test_runtime_style_label_thresholds_and_caps_reduce_box_flood() -> None:
    detections = [
        LearnedDetection("humanoid_unit_like", .90, 2+i*10, 2, 10+i*10, 35)
        for i in range(4)
    ] + [
        LearnedDetection("corpse_like", .49, 5, 45, 20, 60),
        LearnedDetection("world_object_like", .65, 30, 45, 50, 70),
    ]
    detector = LearnedWorldDetector(
        _Backend(detections), confidence=.30,
        label_thresholds={"corpse_like": .52, "world_object_like": .72},
        per_label_limits={"humanoid_unit_like": 2},
    )

    result = detector.detect(
        _frame(), 100, 80, WorldSceneROI(PixelRect(0, 0, 100, 80)))

    assert len(result) == 2
    assert all(item.appearance["learned_label_hypothesis"] == "humanoid_unit_like"
               for item in result)
    assert detector.last_diagnostics["rejected_by_threshold"] == 2
    assert detector.last_diagnostics["rejected_by_label_limit"] == 2


def test_low_confidence_overhead_cue_survives_without_admitting_weak_subjects() -> None:
    detector = LearnedWorldDetector(
        _LowConfidenceBackend(), confidence=.01,
        label_thresholds={
            "overhead_symbol_like": .01,
            "humanoid_unit_like": .12,
        },
    )

    result = detector.detect(
        _frame(), 100, 80, WorldSceneROI(PixelRect(0, 0, 100, 80)))

    assert len(result) == 1
    assert result[0].kind == "unknown_symbol_candidate"
    assert result[0].appearance["learned_confidence"] == .02
    assert result[0].appearance["semantic_status"] == "UNCONFIRMED"
    assert detector.last_diagnostics["rejected_by_threshold"] == 1


def test_runtime_subject_gate_rejects_below_point_15_and_admits_boundary() -> None:
    detector = LearnedWorldDetector(
        _Backend([
            LearnedDetection("humanoid_unit_like", .149, 5, 5, 25, 60),
            LearnedDetection("creature_unit_like", .15, 35, 10, 70, 55),
        ]),
        confidence=.30,
        label_thresholds={
            "humanoid_unit_like": RUNTIME_SUBJECT_CONFIDENCE,
            "creature_unit_like": RUNTIME_SUBJECT_CONFIDENCE,
        },
    )

    result = detector.detect(
        _frame(), 100, 80, WorldSceneROI(PixelRect(0, 0, 100, 80)))

    assert len(result) == 1
    assert result[0].appearance["learned_label_hypothesis"] == "creature_unit_like"
    assert result[0].appearance["learned_confidence"] == .15
    assert detector.last_diagnostics["rejected_by_threshold"] == 1


def test_learned_overhead_symbol_survives_optional_hud_region_overlap() -> None:
    detector = LearnedWorldDetector(_Backend([
        LearnedDetection("overhead_symbol_like", .80, 75, 5, 90, 25),
    ]), confidence=.30)
    scene = WorldSceneROI(
        PixelRect(0, 0, 100, 80),
        excluded_rects=(PixelRect(70, 0, 100, 35),))

    result = detector.detect(_frame(), 100, 80, scene)

    assert len(result) == 1
    assert result[0].kind == "unknown_symbol_candidate"
    assert result[0].appearance["semantic_status"] == "UNCONFIRMED"


def test_adaptive_sampling_alternates_global_and_magnified_foveal_scans() -> None:
    backend = _AdaptiveBackend([
        LearnedDetection("overhead_symbol_like", .90, 400, 200, 450, 300),
    ])
    detector = LearnedWorldDetector(
        backend, confidence=.30, full_scan_interval=3,
        full_scan_image_size=512, foveal_image_size=640)
    scene = WorldSceneROI(PixelRect(0, 0, 1000, 800))

    frame = _frame(1000, 800)
    first = detector.detect(frame, 1000, 800, scene)
    second = detector.detect(frame, 1000, 800, scene)
    third = detector.detect(frame, 1000, 800, scene)

    assert first and second and third
    assert backend.sizes == [512, 640, 512]
    assert backend.shapes[0] == (800, 1000, 3)
    assert backend.shapes[1][0] < 800 or backend.shapes[1][1] < 1000
    assert detector.last_diagnostics["sampling_mode"] == "FULL"


def test_empty_foveal_scan_forces_next_global_reacquisition() -> None:
    backend = _AdaptiveBackend([
        LearnedDetection("humanoid_unit_like", .90, 40, 20, 50, 60),
    ])
    detector = LearnedWorldDetector(backend, confidence=.30, full_scan_interval=5)
    scene = WorldSceneROI(PixelRect(0, 0, 100, 80))
    assert detector.detect(_frame(), 100, 80, scene)
    backend.detections = []
    assert detector.detect(_frame(), 100, 80, scene) == ()
    backend.detections = [LearnedDetection(
        "humanoid_unit_like", .90, 40, 20, 50, 60)]

    detector.detect(_frame(), 100, 80, scene)

    assert backend.sizes[-1] == 512
    assert detector.last_diagnostics["sampling_mode"] == "FULL"


def _write_dataset(root: Path, splits: tuple[str, ...], label: str) -> None:
    for index, split in enumerate(splits):
        image_dir = root / "images" / split
        label_dir = root / "labels" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        (image_dir / f"sample_{split}_{index}.png").write_bytes(b"not-decoded-by-audit")
        (label_dir / f"sample_{split}_{index}.txt").write_text(label, encoding="utf-8")
    (root / "data.yaml").write_text(
        "path: .\ntrain: images/train\nval: images/val\ntest: images/test\n"
        "names: [unknown_subject, unknown_object]\n", encoding="utf-8")


def test_dataset_audit_accepts_disjoint_non_full_frame_splits(tmp_path: Path) -> None:
    _write_dataset(tmp_path, ("train", "val", "test"), "0 0.5 0.5 0.3 0.5\n")
    # Add a second class so taxonomy coverage is explicit rather than warned.
    label = tmp_path / "labels" / "train" / "sample_train_0.txt"
    label.write_text(label.read_text(encoding="utf-8") + "1 0.2 0.2 0.1 0.1\n",
                     encoding="utf-8")

    audit = audit_yolo_dataset(tmp_path)

    assert audit.training_ready
    assert audit.split_names == ("test", "train", "val")
    assert audit.split_overlap_count == 0
    assert audit.class_counts == {0: 3, 1: 1}


def test_dataset_audit_rejects_full_frame_labels_and_train_val_leakage(tmp_path: Path) -> None:
    image_dir = tmp_path / "images"
    label_dir = tmp_path / "labels"
    image_dir.mkdir()
    label_dir.mkdir()
    (image_dir / "scene.jpg").write_bytes(b"x")
    (label_dir / "scene.txt").write_text("2 0.5 0.5 1.0 1.0\n", encoding="utf-8")
    (tmp_path / "data.yaml").write_text(
        "train: images\nval: images\nnames: [a, b, npc_body]\n", encoding="utf-8")

    audit = audit_yolo_dataset(tmp_path)

    assert not audit.training_ready
    assert audit.full_frame_fraction == 1.0
    assert "full_frame_label_collapse" in audit.errors
    assert "split_leakage" in audit.errors
    assert "test_split_missing" in audit.errors
