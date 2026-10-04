"""Create an unreviewed World3D annotation pool from an image folder."""
from __future__ import annotations

import argparse
from hashlib import sha1, sha256
import json
from pathlib import Path
import re
import shutil
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.world3d.video_dataset import WORLD3D_YOLO_CLASSES


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _source_id(folder: Path) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", folder.name.lower()).strip("-")[:48]
    digest = sha1(str(folder.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{slug or 'images'}-{digest}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--recursive", action="store_true")
    args = parser.parse_args()

    source = args.images.resolve()
    output = args.out.resolve()
    if not source.is_dir():
        raise SystemExit(f"Image folder does not exist: {source}")
    manifest = output / "review" / "manifest.jsonl"
    if manifest.exists() or (output.exists() and any(output.iterdir())):
        raise SystemExit(f"Output must be absent or empty: {output}")

    image_dir = output / "review" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    paths = source.rglob("*") if args.recursive else source.glob("*")
    candidates = sorted(path for path in paths
                        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
    sid = _source_id(source)
    rows: list[dict] = []
    hashes: set[str] = set()
    duplicates = unreadable = 0
    for source_index, image_path in enumerate(candidates):
        payload = image_path.read_bytes()
        digest = sha256(payload).hexdigest()
        if digest in hashes:
            duplicates += 1
            continue
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            unreadable += 1
            continue
        hashes.add(digest)
        safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", image_path.stem)[:96]
        filename = f"{sid}__i{source_index:06d}__{safe_stem}{image_path.suffix.lower()}"
        target = image_dir / filename
        shutil.copy2(image_path, target)
        height, width = frame.shape[:2]
        rows.append({
            "image": target.relative_to(output).as_posix(),
            "source_id": sid,
            "source_path": str(image_path),
            "source_frame": source_index,
            "timestamp_seconds": round(image_path.stat().st_mtime, 3),
            "width": width,
            "height": height,
            "sample_difference": None,
            "sha256": digest,
            "review_status": "UNREVIEWED",
        })

    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                        encoding="utf-8", newline="\n")
    (output / "classes.txt").write_text(
        "\n".join(WORLD3D_YOLO_CLASSES) + "\n", encoding="utf-8")
    (output / "README.txt").write_text(
        "World3D screenshot review pool.\n"
        "Model boxes are proposals only until explicitly reviewed and saved.\n"
        "Review empty frames as valid negatives; do not auto-promote proposals.\n",
        encoding="utf-8")
    print(json.dumps({"source": str(source), "output": str(output),
                      "discovered": len(candidates), "written": len(rows),
                      "duplicates_skipped": duplicates, "unreadable": unreadable},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
