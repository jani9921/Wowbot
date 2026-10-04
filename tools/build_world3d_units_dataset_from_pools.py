"""Build the 3-class unit YOLO dataset directly from every human review pool.

Every explicitly saved frame (REVIEWED or REVIEWED_EMPTY) of every
``<datasets>/*/review`` pool is included with its current label file, remapped
by ``remap_world3d_unit_dataset.REMAP``.  Unreviewed frames are never used.

Splits: a frame that already appears in the reference export keeps that split.
A new frame inherits the split of the nearest already-assigned frame from the
same video source (so adjacent frames never straddle train/test); a source with
no assigned frame is split in contiguous blocks.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil

_REMAP_TOOL = Path(__file__).resolve().parent / "remap_world3d_unit_dataset.py"
_spec = importlib.util.spec_from_file_location("remap_world3d_unit_dataset", _REMAP_TOOL)
_remap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_remap)
UNIT_CLASSES, remap_label_text = _remap.UNIT_CLASSES, _remap.remap_label_text

SPLITS = ("train", "val", "test")
_EXPORT_PREFIX = re.compile(r"^s\d+_world3d_")


def original_stem(exported_stem: str) -> str:
    """Strip nested combine prefixes (``s0_<dataset>__``) from an exported stem."""
    parts = exported_stem.split("__")
    last_prefix = max((i for i, part in enumerate(parts) if _EXPORT_PREFIX.match(part)), default=-1)
    return "__".join(parts[last_prefix + 1:])


def block_split(position: int, block: int = 20) -> str:
    """Deterministic 70/15/15 split of contiguous blocks."""
    pattern = ("train",) * 14 + ("val",) * 3 + ("test",) * 3
    return pattern[(position // block) % len(pattern)]


def inherit_splits(ordered: list[tuple[str, str | None]]) -> list[str]:
    """Fill missing splits from the nearest assigned neighbour in source order."""
    known = [i for i, (_, split) in enumerate(ordered) if split]
    result = []
    for index, (_, split) in enumerate(ordered):
        if split:
            result.append(split)
        elif known:
            nearest = min(known, key=lambda k: (abs(k - index), k))
            result.append(ordered[nearest][1])
        else:
            result.append(block_split(index))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("datasets", type=Path, help="folder containing the review pools")
    parser.add_argument("reference_export", type=Path, help="existing export whose splits are preserved")
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"output already exists: {args.out}")

    reference: dict[str, str] = {}
    for split in SPLITS:
        for label in (args.reference_export / "labels" / split).glob("*.txt"):
            reference[original_stem(label.stem)] = split

    frames = []  # (pool, source_id, order, stem, image, label, preserved split)
    for review_dir in sorted(args.datasets.glob("*/review/reviews")):
        pool = review_dir.parent.parent
        manifest = [json.loads(line) for line in
                    (pool / "review" / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        order = {Path(str(row["image"])).stem: (str(row.get("source_id") or ""), float(row.get("timestamp_seconds") or 0), i)
                 for i, row in enumerate(manifest)}
        for review_path in review_dir.glob("*.json"):
            review = json.loads(review_path.read_text(encoding="utf-8"))
            if review.get("review_status") not in {"REVIEWED", "REVIEWED_EMPTY"}:
                continue
            stem = review_path.stem
            image = pool / str(review["image"]).replace("\\", "/")
            label = pool / "review" / "labels" / f"{stem}.txt"
            if not image.is_file() or not label.is_file():
                continue
            source_id, timestamp, index = order.get(stem, ("", 0., 0))
            frames.append((pool.name, source_id, (timestamp, index), stem, image, label, reference.get(stem)))

    groups: dict[tuple[str, str], list] = {}
    for frame in frames:
        groups.setdefault((frame[0], frame[1]), []).append(frame)
    for split in SPLITS:
        (args.out / "images" / split).mkdir(parents=True)
        (args.out / "labels" / split).mkdir(parents=True)
    summary = {split: {"images": 0, "empty": 0, "boxes": {name: 0 for name in UNIT_CLASSES}} for split in SPLITS}
    per_pool: dict[str, dict[str, int]] = {}
    preserved = 0
    for (pool_name, _), members in sorted(groups.items()):
        members.sort(key=lambda frame: frame[2])
        splits = inherit_splits([(frame[3], frame[6]) for frame in members])
        for frame, split in zip(members, splits):
            _, _, _, stem, image, label, kept = frame
            preserved += kept is not None
            target_stem = f"{pool_name}__{stem}"
            target = args.out / "images" / split / f"{target_stem}{image.suffix.lower()}"
            try:
                os.link(image, target)
            except OSError:
                shutil.copy2(image, target)
            text, counts = remap_label_text(label.read_text(encoding="utf-8"))
            (args.out / "labels" / split / f"{target_stem}.txt").write_text(text, encoding="utf-8")
            summary[split]["images"] += 1
            summary[split]["empty"] += not text
            for class_id, count in counts.items():
                summary[split]["boxes"][UNIT_CLASSES[class_id]] += count
            per_pool.setdefault(pool_name, {s: 0 for s in SPLITS})[split] += 1

    (args.out / "data.yaml").write_text(
        f"path: '{args.out.resolve().as_posix()}'\ntrain: images/train\nval: images/val\ntest: images/test\n"
        "names:\n" + "".join(f"  {i}: {name}\n" for i, name in enumerate(UNIT_CLASSES)), encoding="utf-8")
    report = {"datasets": str(args.datasets.resolve()), "reference_export": str(args.reference_export.resolve()),
              "frames": len(frames), "preserved_split_frames": preserved, "per_pool": per_pool, "summary": summary}
    (args.out / "sources.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
