"""Strict, dependency-free audit for YOLO World3D datasets.

The audit intentionally rejects the common but invalid shortcut where every
reference image is labeled as one full-frame NPC and where training and
validation point to the same files.  Passing this audit does not prove model
quality; it only proves that the dataset has the minimum structural properties
needed for a meaningful training run.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
import re


_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp"})


@dataclass(frozen=True, slots=True)
class YoloDatasetAudit:
    root: str
    image_count: int
    label_file_count: int
    box_count: int
    class_counts: dict[int, int]
    full_frame_box_count: int
    full_frame_fraction: float
    duplicate_image_stems: int
    missing_label_count: int
    orphan_label_count: int
    invalid_label_count: int
    split_names: tuple[str, ...]
    split_overlap_count: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def training_ready(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "training_ready": self.training_ready}


def _images(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*")
                  if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES)


def _declared_splits(root: Path) -> dict[str, set[str]]:
    """Read conventional split folders plus simple data.yaml declarations."""
    result: dict[str, set[str]] = {}
    images_root = root / "images"
    for split in ("train", "val", "test"):
        directory = images_root / split
        if directory.is_dir():
            result[split] = {str(path.resolve()).casefold() for path in _images(directory)}

    yaml_path = root / "data.yaml"
    if yaml_path.is_file():
        text = yaml_path.read_text(encoding="utf-8", errors="replace")
        for split in ("train", "val", "test"):
            match = re.search(rf"(?m)^\s*{split}\s*:\s*([^#\r\n]+)", text)
            if not match:
                continue
            value = match.group(1).strip().strip("'\"")
            declared = Path(value)
            directory = declared if declared.is_absolute() else root / declared
            if directory.is_dir():
                result[split] = {str(path.resolve()).casefold() for path in _images(directory)}
    return result


def audit_yolo_dataset(root: str | Path, *, max_full_frame_fraction: float = .20,
                       require_test_split: bool = True) -> YoloDatasetAudit:
    root = Path(root)
    errors: list[str] = []
    warnings: list[str] = []
    if not root.is_dir():
        return YoloDatasetAudit(str(root), 0, 0, 0, {}, 0, 0., 0, 0, 0, 0,
                                (), 0, ("dataset_root_missing",), ())

    image_root, label_root = root / "images", root / "labels"
    images = _images(image_root) if image_root.is_dir() else []
    labels = sorted(label_root.rglob("*.txt")) if label_root.is_dir() else []
    image_stems = Counter(path.stem.casefold() for path in images)
    label_stems = Counter(path.stem.casefold() for path in labels)
    duplicate_stems = sum(count - 1 for count in image_stems.values() if count > 1)
    missing = sum(1 for stem in image_stems if stem not in label_stems)
    orphan = sum(1 for stem in label_stems if stem not in image_stems)

    classes: Counter[int] = Counter()
    box_count = full_frame = invalid = 0
    for label_path in labels:
        for line in label_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            fields = line.split()
            try:
                class_id = int(fields[0])
                x, y, width, height = (float(value) for value in fields[1:])
            except (IndexError, ValueError):
                invalid += 1
                continue
            if len(fields) != 5 or class_id < 0 or not all(
                    0. <= value <= 1. for value in (x, y, width, height)) or width <= 0 or height <= 0:
                invalid += 1
                continue
            classes[class_id] += 1
            box_count += 1
            if width >= .98 and height >= .98:
                full_frame += 1

    splits = _declared_splits(root)
    overlap: set[str] = set()
    split_items = list(splits.items())
    for index, (_, left) in enumerate(split_items):
        for _, right in split_items[index + 1:]:
            overlap.update(left & right)

    full_fraction = full_frame / box_count if box_count else 0.
    if not images:
        errors.append("no_images")
    if not labels or not box_count:
        errors.append("no_valid_labels")
    if invalid:
        errors.append("invalid_yolo_labels")
    if missing:
        errors.append("images_without_labels")
    if orphan:
        errors.append("labels_without_images")
    if duplicate_stems:
        errors.append("duplicate_image_stems")
    if full_fraction > max(0., min(1., float(max_full_frame_fraction))):
        errors.append("full_frame_label_collapse")
    if "train" not in splits or "val" not in splits:
        errors.append("train_val_split_missing")
    if require_test_split and "test" not in splits:
        errors.append("test_split_missing")
    if overlap:
        errors.append("split_leakage")
    if len(classes) < 2:
        warnings.append("single_class_dataset")
    if images and box_count / len(images) < .25:
        warnings.append("very_sparse_annotations")

    return YoloDatasetAudit(
        root=str(root.resolve()), image_count=len(images), label_file_count=len(labels),
        box_count=box_count, class_counts=dict(sorted(classes.items())),
        full_frame_box_count=full_frame, full_frame_fraction=round(full_fraction, 6),
        duplicate_image_stems=duplicate_stems, missing_label_count=missing,
        orphan_label_count=orphan, invalid_label_count=invalid,
        split_names=tuple(sorted(splits)), split_overlap_count=len(overlap),
        errors=tuple(dict.fromkeys(errors)), warnings=tuple(dict.fromkeys(warnings)),
    )

