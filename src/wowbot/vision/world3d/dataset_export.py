"""Leakage-aware export of reviewed video annotations to YOLO folders."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import product
import json
from pathlib import Path
import shutil

from .video_dataset import WORLD3D_YOLO_CLASSES


@dataclass(frozen=True, slots=True)
class ExportSummary:
    reviewed_frames: int
    boxes: int
    clusters: int
    split_frames: dict[str, int]


def _clusters(records: list[dict], gap_seconds: float,
              max_duration_seconds: float) -> list[list[dict]]:
    by_source: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_source[str(record["source_id"])].append(record)
    result: list[list[dict]] = []
    for source_id in sorted(by_source):
        current: list[dict] = []
        previous: float | None = None
        cluster_started: float | None = None
        for record in sorted(by_source[source_id], key=lambda row: float(row["timestamp_seconds"])):
            timestamp = float(record["timestamp_seconds"])
            gap_break = current and previous is not None and timestamp - previous > gap_seconds
            duration_break = (current and cluster_started is not None
                              and timestamp - cluster_started >= max_duration_seconds)
            if gap_break or duration_break:
                result.append(current)
                current = []
                cluster_started = None
            if cluster_started is None:
                cluster_started = timestamp
            current.append(record)
            previous = timestamp
        if current:
            result.append(current)
    return result


def _record_classes(record: dict) -> list[int]:
    result: list[int] = []
    for line in Path(str(record["label_path"])).read_text(encoding="utf-8").splitlines():
        if line.strip():
            result.append(int(line.split()[0]))
    return result


def _assign_clusters(clusters: list[list[dict]]) -> dict[str, list[list[dict]]]:
    if len(clusters) < 3:
        raise ValueError("at least three temporally separated clusters are required")
    names = ("train", "val", "test")
    splits = {name: [] for name in names}
    targets = {"train": .70, "val": .15, "test": .15}
    total = sum(len(cluster) for cluster in clusters)
    ordered = sorted(
        clusters,
        key=lambda cluster: (-len(cluster), str(cluster[0]["source_id"]),
                             float(cluster[0]["timestamp_seconds"])),
    )
    cluster_classes = [
        [class_id for record in cluster for class_id in _record_classes(record)]
        for cluster in ordered
    ]
    all_classes = sorted({class_id for values in cluster_classes for class_id in values})
    class_totals = {class_id: sum(values.count(class_id) for values in cluster_classes)
                    for class_id in all_classes}

    def score(assignment: tuple[int, ...]) -> float:
        frame_counts = [0, 0, 0]
        class_counts = [{class_id: 0 for class_id in all_classes} for _ in names]
        for cluster_index, split_index in enumerate(assignment):
            frame_counts[split_index] += len(ordered[cluster_index])
            for class_id in cluster_classes[cluster_index]:
                class_counts[split_index][class_id] += 1
        if any(count == 0 for count in frame_counts):
            return 1_000_000.
        value = sum(abs(frame_counts[index] / total - targets[name]) * 4.
                    for index, name in enumerate(names))
        for class_id, class_total in class_totals.items():
            if class_counts[0][class_id] == 0:
                value += 100.
            if class_total >= 3:
                value += 12. * (class_counts[1][class_id] == 0)
                value += 12. * (class_counts[2][class_id] == 0)
            for index, name in enumerate(names):
                value += abs(class_counts[index][class_id] / class_total - targets[name])
        return value

    if len(ordered) <= 12:
        assignment = min(product(range(3), repeat=len(ordered)), key=score)
    else:
        # Large datasets use deterministic load-balanced placement.  Scoring a
        # partially built assignment as though every future cluster belonged
        # to train biases every choice toward train and can leave val/test
        # empty.  Seed all splits, then compare projected frame/class pressure
        # against each split's final target.
        partial: list[int] = []
        frame_counts = [0, 0, 0]
        class_counts = [{class_id: 0 for class_id in all_classes} for _ in names]
        for cluster_index, cluster in enumerate(ordered):
            values = cluster_classes[cluster_index]
            per_class = {class_id: values.count(class_id) for class_id in set(values)}
            if cluster_index < 3:
                choice = cluster_index
            else:
                def pressure(split_index: int) -> tuple[float, float, int]:
                    target_frames = max(1.0, total * targets[names[split_index]])
                    frame_pressure = ((frame_counts[split_index] + len(cluster))
                                      / target_frames)
                    class_pressure = 0.0
                    if per_class:
                        class_pressure = sum(
                            (class_counts[split_index][class_id] + count)
                            / max(1.0, class_totals[class_id]
                                  * targets[names[split_index]])
                            for class_id, count in per_class.items()
                        ) / len(per_class)
                    return (frame_pressure * 4.0 + class_pressure,
                            frame_pressure, split_index)

                choice = min(range(3), key=pressure)
            partial.append(choice)
            frame_counts[choice] += len(cluster)
            for class_id in values:
                class_counts[choice][class_id] += 1
        assignment = tuple(partial)
    for cluster, split_index in zip(ordered, assignment):
        splits[names[split_index]].append(cluster)
    return splits


def export_reviewed_dataset(review_dataset: Path, output: Path, *,
                            cluster_gap_seconds: float = 30.0,
                            max_cluster_duration_seconds: float = 120.0) -> ExportSummary:
    """Export only explicitly reviewed frames; temporal clusters never cross splits."""
    review_dataset = Path(review_dataset)
    output = Path(output)
    if cluster_gap_seconds <= 0:
        raise ValueError("cluster_gap_seconds must be positive")
    if max_cluster_duration_seconds <= 0:
        raise ValueError("max_cluster_duration_seconds must be positive")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output is not empty: {output}")

    manifest = [json.loads(line) for line in
                (review_dataset / "review" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
    manifest_by_image = {str(row["image"]): row for row in manifest}
    records: list[dict] = []
    review_dir = review_dataset / "review" / "reviews"
    for review_path in sorted(review_dir.glob("*.json")):
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if review.get("review_status") not in {"REVIEWED", "REVIEWED_EMPTY"}:
            continue
        image_key = str(review["image"]).replace("\\", "/")
        source = manifest_by_image.get(image_key)
        if source is None:
            raise ValueError(f"review image is absent from manifest: {image_key}")
        label_path = review_dataset / "review" / "labels" / f"{Path(image_key).stem}.txt"
        if not label_path.is_file():
            raise ValueError(f"reviewed frame has no label file: {image_key}")
        records.append({**source, "review": review, "label_path": str(label_path)})

    grouped = _clusters(records, cluster_gap_seconds, max_cluster_duration_seconds)
    assignments = _assign_clusters(grouped)
    output.mkdir(parents=True, exist_ok=True)
    split_manifest: list[dict] = []
    total_boxes = 0
    split_frames: dict[str, int] = {}
    for split, clusters in assignments.items():
        image_out = output / "images" / split
        label_out = output / "labels" / split
        image_out.mkdir(parents=True, exist_ok=True)
        label_out.mkdir(parents=True, exist_ok=True)
        split_frames[split] = 0
        for cluster_index, cluster in enumerate(clusters):
            for record in cluster:
                source_image = review_dataset / str(record["image"])
                source_label = Path(str(record["label_path"]))
                shutil.copy2(source_image, image_out / source_image.name)
                shutil.copy2(source_label, label_out / source_label.name)
                lines = [line for line in source_label.read_text(encoding="utf-8").splitlines()
                         if line.strip()]
                total_boxes += len(lines)
                split_frames[split] += 1
                split_manifest.append({
                    "split": split,
                    "cluster": cluster_index,
                    "image": str(record["image"]),
                    "source_id": record["source_id"],
                    "timestamp_seconds": record["timestamp_seconds"],
                    "sha256": record["sha256"],
                    "review_status": record["review"]["review_status"],
                    "box_count": len(lines),
                })
    names = "\n".join(f"  {index}: {name}" for index, name in enumerate(WORLD3D_YOLO_CLASSES))
    dataset_path = output.resolve().as_posix().replace("'", "''")
    (output / "data.yaml").write_text(
        f"path: '{dataset_path}'\ntrain: images/train\nval: images/val\ntest: images/test\n"
        f"names:\n{names}\n", encoding="utf-8")
    (output / "split_manifest.json").write_text(
        json.dumps(split_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return ExportSummary(len(records), total_boxes, len(grouped), split_frames)
