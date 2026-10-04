from pathlib import Path

import numpy as np

from wowbot.vision.world3d.video_dataset import (
    WORLD3D_YOLO_CLASSES,
    sample_difference,
    source_id,
)


def test_source_id_is_stable_safe_and_distinguishes_paths(tmp_path: Path) -> None:
    first = source_id(tmp_path / "Elwynn Gameplay #1.mp4")
    second = source_id(tmp_path / "other" / "Elwynn Gameplay #1.mp4")

    assert first.startswith("elwynn-gameplay-1-")
    assert first != second
    assert " " not in first


def test_sample_difference_rejects_identical_and_separates_changed_frames() -> None:
    black = np.zeros((180, 320, 3), dtype=np.uint8)
    white = np.full((180, 320, 3), 255, dtype=np.uint8)

    first_difference, previous = sample_difference(None, black)
    same_difference, _ = sample_difference(previous, black)
    changed_difference, _ = sample_difference(previous, white)

    assert first_difference is None
    assert same_difference == 0.0
    assert changed_difference == 255.0


def test_taxonomy_keeps_outline_reserved_without_semantic_roles() -> None:
    assert WORLD3D_YOLO_CLASSES == (
        "humanoid_unit_like",
        "creature_unit_like",
        "corpse_like",
        "quest_object_outline_like",
        "world_object_like",
        "overhead_symbol_like",
        "entrance_or_door_like",
    )
    assert "npc" not in WORLD3D_YOLO_CLASSES
    assert "hostile" not in WORLD3D_YOLO_CLASSES
