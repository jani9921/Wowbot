"""Export the saved frames of a unit relabel pool as a 3-class YOLO dataset.

Only frames with a saved review (REVIEWED / REVIEWED_EMPTY) are exported;
unreviewed frames are skipped.  Labels are remapped with
``remap_world3d_unit_dataset.REMAP``.  A frame keeps the split recorded in the
pool manifest; a frame without one inherits the split of the nearest assigned
frame from the same source video, so adjacent frames never straddle splits.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil

_TOOLS = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_remap = _load("remap_world3d_unit_dataset")
_pools = _load("build_world3d_units_dataset_from_pools")
UNIT_CLASSES, remap_label_text = _remap.UNIT_CLASSES, _remap.remap_label_text
original_stem, inherit_splits = _pools.original_stem, _pools.inherit_splits
SPLITS = ("train", "val", "test")


def frame_key(record: dict) -> tuple[str, str, int]:
    """(video id, original stem, frame number) for grouping and ordering."""
    stem = Path(str(record["image"])).stem
    stem = stem.split("__", 1)[1] if record.get("source_pool") else original_stem(stem)
    video = stem.split("__", 1)[0]
    match = re.search(r"__f(\d+)", stem)
    return video, stem, int(match[1]) if match else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pool", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"output already exists: {args.out}")
    review = args.pool / "review"
    records = [json.loads(line) for line in (review / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    frames, seen, skipped = [], set(), {"unreviewed": 0, "duplicate": 0}
    for record in records:
        stem = Path(str(record["image"])).stem
        saved = review / "reviews" / f"{stem}.json"
        label = review / "labels" / f"{stem}.txt"
        if not saved.is_file() or not label.is_file():
            skipped["unreviewed"] += 1
            continue
        if json.loads(saved.read_text(encoding="utf-8")).get("review_status") not in {"REVIEWED", "REVIEWED_EMPTY"}:
            skipped["unreviewed"] += 1
            continue
        video, original, number = frame_key(record)
        if original in seen:
            skipped["duplicate"] += 1
            continue
        seen.add(original)
        frames.append((video, number, stem, args.pool / str(record["image"]), label, record.get("split")))

    groups: dict[str, list] = {}
    for frame in frames:
        groups.setdefault(frame[0], []).append(frame)
    for split in SPLITS:
        (args.out / "images" / split).mkdir(parents=True)
        (args.out / "labels" / split).mkdir(parents=True)
    summary = {split: {"images": 0, "empty": 0, "boxes": {name: 0 for name in UNIT_CLASSES}} for split in SPLITS}
    for _, members in sorted(groups.items()):
        members.sort(key=lambda frame: frame[1])
        for frame, split in zip(members, inherit_splits([(frame[2], frame[5]) for frame in members])):
            _, _, stem, image, label, _ = frame
            target = args.out / "images" / split / image.name
            try:
                os.link(image, target)
            except OSError:
                shutil.copy2(image, target)
            text, counts = remap_label_text(label.read_text(encoding="utf-8"))
            (args.out / "labels" / split / f"{stem}.txt").write_text(text, encoding="utf-8")
            summary[split]["images"] += 1
            summary[split]["empty"] += not text
            for class_id, count in counts.items():
                summary[split]["boxes"][UNIT_CLASSES[class_id]] += count
    (args.out / "data.yaml").write_text(
        f"path: '{args.out.resolve().as_posix()}'\ntrain: images/train\nval: images/val\ntest: images/test\n"
        "names:\n" + "".join(f"  {i}: {name}\n" for i, name in enumerate(UNIT_CLASSES)), encoding="utf-8")
    report = {"pool": str(args.pool.resolve()), "exported": len(frames), "skipped": skipped, "summary": summary}
    (args.out / "sources.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
