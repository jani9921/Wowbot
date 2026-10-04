from __future__ import annotations

import json
from pathlib import Path

from wowbot.vision.world3d.dataset_audit import audit_yolo_dataset
from wowbot.vision.world3d.dataset_export import export_reviewed_dataset


def test_reviewed_export_keeps_temporal_clusters_in_one_split(tmp_path: Path) -> None:
    source = tmp_path / "review_pool"
    review = source / "review"
    for directory in (review / "images", review / "labels", review / "reviews"):
        directory.mkdir(parents=True)
    records = []
    timestamps = (0.0, 3.0, 50.0, 53.0, 100.0, 103.0)
    for index, timestamp in enumerate(timestamps):
        name = f"frame_{index}.jpg"
        (review / "images" / name).write_bytes(b"jpeg-placeholder")
        (review / "labels" / f"frame_{index}.txt").write_text(
            f"{index % 2} 0.5 0.5 0.2 0.3\n", encoding="utf-8")
        image = f"review/images/{name}"
        records.append({
            "image": image, "source_id": "session-a", "source_path": "capture.mp4",
            "source_frame": index, "timestamp_seconds": timestamp,
            "width": 1280, "height": 720, "sample_difference": 5.0,
            "sha256": f"hash-{index}", "review_status": "UNREVIEWED",
        })
        (review / "reviews" / f"frame_{index}.json").write_text(json.dumps({
            "image": image, "review_status": "REVIEWED", "boxes": [{}],
        }), encoding="utf-8")
    (review / "manifest.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    output = tmp_path / "export"
    summary = export_reviewed_dataset(source, output, cluster_gap_seconds=10.0)

    assert summary.reviewed_frames == 6
    assert summary.clusters == 3
    assert summary.split_frames == {"train": 2, "val": 2, "test": 2}
    manifest = json.loads((output / "split_manifest.json").read_text())
    split_by_time = {row["timestamp_seconds"]: row["split"] for row in manifest}
    assert split_by_time[0.0] == split_by_time[3.0]
    assert split_by_time[50.0] == split_by_time[53.0]
    assert split_by_time[100.0] == split_by_time[103.0]
    assert audit_yolo_dataset(output).training_ready


def test_reviewed_export_greedy_assignment_handles_more_than_twelve_clusters(
        tmp_path: Path) -> None:
    source = tmp_path / "review_pool"
    review = source / "review"
    for directory in (review / "images", review / "labels", review / "reviews"):
        directory.mkdir(parents=True)
    records = []
    for index in range(15):
        name = f"frame_{index}.jpg"
        (review / "images" / name).write_bytes(b"jpeg-placeholder")
        (review / "labels" / f"frame_{index}.txt").write_text(
            f"{index % 2} 0.5 0.5 0.2 0.3\n", encoding="utf-8")
        image = f"review/images/{name}"
        records.append({
            "image": image, "source_id": "session-a", "source_path": "capture.mp4",
            "source_frame": index, "timestamp_seconds": float(index * 2),
            "width": 1280, "height": 720, "sample_difference": 5.0,
            "sha256": f"hash-{index}", "review_status": "UNREVIEWED",
        })
        (review / "reviews" / f"frame_{index}.json").write_text(json.dumps({
            "image": image, "review_status": "REVIEWED", "boxes": [{}],
        }), encoding="utf-8")
    (review / "manifest.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    output = tmp_path / "export"
    summary = export_reviewed_dataset(source, output, cluster_gap_seconds=.5)

    assert summary.reviewed_frames == 15
    assert summary.clusters == 15
    assert all(summary.split_frames[name] > 0 for name in ("train", "val", "test"))
    assert sum(summary.split_frames.values()) == 15


def test_reviewed_export_segments_a_continuous_video_without_frame_leakage(
        tmp_path: Path) -> None:
    source = tmp_path / "review_pool"
    review = source / "review"
    for directory in (review / "images", review / "labels", review / "reviews"):
        directory.mkdir(parents=True)
    records = []
    for index in range(12):
        name = f"continuous_{index}.jpg"
        (review / "images" / name).write_bytes(b"jpeg-placeholder")
        (review / "labels" / f"continuous_{index}.txt").write_text(
            "0 0.5 0.5 0.2 0.3\n", encoding="utf-8")
        image = f"review/images/{name}"
        records.append({
            "image": image, "source_id": "continuous-video", "source_path": "capture.mp4",
            "source_frame": index, "timestamp_seconds": float(index * 10),
            "width": 1280, "height": 720, "sample_difference": 5.0,
            "sha256": f"hash-{index}", "review_status": "UNREVIEWED",
        })
        (review / "reviews" / f"continuous_{index}.json").write_text(json.dumps({
            "image": image, "review_status": "REVIEWED", "boxes": [{}],
        }), encoding="utf-8")
    (review / "manifest.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    output = tmp_path / "export"
    summary = export_reviewed_dataset(
        source, output, cluster_gap_seconds=30.0, max_cluster_duration_seconds=40.0)

    assert summary.clusters == 3
    assert summary.split_frames == {"train": 4, "val": 4, "test": 4}
    manifest = json.loads((output / "split_manifest.json").read_text())
    split_by_time = {row["timestamp_seconds"]: row["split"] for row in manifest}
    assert len({split_by_time[time] for time in (0.0, 10.0, 20.0, 30.0)}) == 1
    assert len({split_by_time[time] for time in (40.0, 50.0, 60.0, 70.0)}) == 1
    assert len({split_by_time[time] for time in (80.0, 90.0, 100.0, 110.0)}) == 1
