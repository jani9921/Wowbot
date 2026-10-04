"""Prepare reviewable World3D frames from gameplay videos.

This module deliberately stops before annotation.  A sampled gameplay frame is
not ground truth, and detector-generated boxes must not silently become YOLO
labels.  The output is a review pool plus provenance manifest for a human
annotation/export step.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha1, sha256
import json
from pathlib import Path
import re
from typing import Iterable

import cv2
import numpy as np


WORLD3D_YOLO_CLASSES: tuple[str, ...] = (
    "humanoid_unit_like",
    "creature_unit_like",
    "corpse_like",
    "quest_object_outline_like",
    "world_object_like",
    "overhead_symbol_like",
    "entrance_or_door_like",
)


@dataclass(frozen=True, slots=True)
class ReviewFrame:
    image: str
    source_id: str
    source_path: str
    source_frame: int
    timestamp_seconds: float
    width: int
    height: int
    sample_difference: float | None
    sha256: str
    review_status: str = "UNREVIEWED"


@dataclass(frozen=True, slots=True)
class ExtractionSummary:
    videos: int
    sampled: int
    written: int
    near_duplicates_skipped: int
    exact_duplicates_skipped: int


def source_id(path: Path) -> str:
    """Return a stable, filesystem-safe source identifier."""
    slug = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")[:48]
    digest = sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{slug or 'video'}-{digest}"


def sample_difference(previous: np.ndarray | None, frame: np.ndarray) -> tuple[float | None, np.ndarray]:
    """Return cheap visual difference on a small grayscale representation."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
    if previous is None:
        return None, small
    difference = float(np.mean(cv2.absdiff(previous, small)))
    return difference, small


def prepare_review_pool(
    videos: Iterable[Path],
    output: Path,
    *,
    interval_seconds: float = 3.0,
    minimum_difference: float = 2.5,
    jpeg_quality: int = 92,
    limit_per_video: int = 0,
    exclude_manifests: Iterable[Path] = (),
) -> ExtractionSummary:
    """Sample videos into an unsplit, unlabelled, provenance-preserving pool."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if minimum_difference < 0:
        raise ValueError("minimum_difference cannot be negative")
    if not 1 <= jpeg_quality <= 100:
        raise ValueError("jpeg_quality must be between 1 and 100")

    video_paths = tuple(Path(path).resolve() for path in videos)
    if not video_paths:
        raise ValueError("at least one video is required")
    missing = [str(path) for path in video_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing video(s): " + ", ".join(missing))

    image_dir = output / "review" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    output_manifest_path = output / "review" / "manifest.jsonl"
    records: list[ReviewFrame] = []
    seen_hashes: set[str] = set()
    excluded_source_frames: set[tuple[str, int]] = set()
    for exclusion_manifest in (Path(path) for path in exclude_manifests):
        if not exclusion_manifest.is_file():
            raise FileNotFoundError(f"missing exclusion manifest: {exclusion_manifest}")
        for line in exclusion_manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            source_path = str(Path(str(row["source_path"])).resolve()).casefold()
            excluded_source_frames.add((source_path, int(row["source_frame"])))
    sampled = near_duplicates = exact_duplicates = 0

    for video in video_paths:
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            raise RuntimeError(f"could not open video: {video}")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if fps <= 0 or frame_count <= 0:
            capture.release()
            raise RuntimeError(f"invalid video metadata: {video}")

        duration = frame_count / fps
        sid = source_id(video)
        previous_small: np.ndarray | None = None
        accepted_for_source = 0
        timestamp = 0.0
        while timestamp < duration:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok:
                break
            sampled += 1
            difference, small = sample_difference(previous_small, frame)
            previous_small = small
            if difference is not None and difference < minimum_difference:
                near_duplicates += 1
                timestamp += interval_seconds
                continue

            source_frame = int(round(timestamp * fps))
            source_key = (str(video.resolve()).casefold(), source_frame)
            if source_key in excluded_source_frames:
                exact_duplicates += 1
                timestamp += interval_seconds
                continue

            encoded_ok, encoded = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
            if not encoded_ok:
                capture.release()
                raise RuntimeError(f"JPEG encoding failed: {video} @ {timestamp:.3f}s")
            payload = encoded.tobytes()
            digest = sha256(payload).hexdigest()
            if digest in seen_hashes:
                exact_duplicates += 1
                timestamp += interval_seconds
                continue
            seen_hashes.add(digest)

            filename = f"{sid}__f{source_frame:09d}__t{timestamp:011.3f}.jpg"
            relative = Path("review") / "images" / filename
            (output / relative).write_bytes(payload)
            records.append(ReviewFrame(
                image=relative.as_posix(),
                source_id=sid,
                source_path=str(video),
                source_frame=source_frame,
                timestamp_seconds=round(timestamp, 3),
                width=int(frame.shape[1]),
                height=int(frame.shape[0]),
                sample_difference=None if difference is None else round(difference, 4),
                sha256=digest,
            ))
            accepted_for_source += 1
            if limit_per_video and accepted_for_source >= limit_per_video:
                break
            timestamp += interval_seconds
        capture.release()

    with output_manifest_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    (output / "classes.txt").write_text(
        "\n".join(WORLD3D_YOLO_CLASSES) + "\n", encoding="utf-8")
    (output / "README.txt").write_text(
        "World3D video review pool.\n"
        "These images are UNREVIEWED and intentionally have no YOLO labels.\n"
        "Draw tight boxes around every in-scope object. Empty reviewed frames are valid negatives.\n"
        "Do not split adjacent frames across train/val/test; split by source/session or disjoint time block.\n"
        "quest_object_outline_like is reserved and may have zero positives in this revision.\n",
        encoding="utf-8",
    )
    return ExtractionSummary(
        videos=len(video_paths),
        sampled=sampled,
        written=len(records),
        near_duplicates_skipped=near_duplicates,
        exact_duplicates_skipped=exact_duplicates,
    )
