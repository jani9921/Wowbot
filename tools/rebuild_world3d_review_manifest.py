"""Rebuild review provenance from deterministic frame filenames and image bytes."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

import cv2


FRAME_PATTERN = re.compile(r"^(?P<source>.+)__f(?P<frame>\d+)__t(?P<time>\d+\.\d+)\.(?:jpg|jpeg|png|webp)$", re.I)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--source-video", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    dataset = args.dataset.resolve()
    video = args.source_video.resolve()
    images = []
    for image_path in (dataset / "review" / "images").glob("*"):
        match = FRAME_PATTERN.match(image_path.name)
        if match:
            images.append((int(match.group("frame")), float(match.group("time")),
                           match.group("source"), image_path))
    images.sort(key=lambda item: (item[0], item[3].name))
    if args.limit:
        images = images[:args.limit]
    rows = []
    for source_frame, timestamp, source_id, image_path in images:
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"Cannot read {image_path}")
        height, width = frame.shape[:2]
        rows.append({
            "image": image_path.relative_to(dataset).as_posix(),
            "source_id": source_id,
            "source_path": str(video),
            "source_frame": source_frame,
            "timestamp_seconds": timestamp,
            "width": width,
            "height": height,
            "sample_difference": None,
            "sha256": sha256(image_path.read_bytes()).hexdigest(),
            "review_status": "UNREVIEWED",
        })
    manifest = dataset / "review" / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                        encoding="utf-8", newline="\n")
    print(f"manifest={manifest} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
