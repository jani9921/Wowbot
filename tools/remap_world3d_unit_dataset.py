"""Copy an exported 7-class World3D YOLO dataset into the 3-class unit taxonomy.

No review step: existing labels are remapped as they are, splits are preserved
and images are hard-linked (copied only when linking is impossible).

  old 0 humanoid_unit_like, 1 creature_unit_like, 2 corpse_like -> 0 creature_unit_like
  old 3 quest_object_outline_like                              -> 1 quest_object_outline_like
  old 5 overhead_symbol_like                                   -> 2 overhead_symbol_like
  old 4 world_object_like, 6 entrance_or_door_like             -> dropped
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil

UNIT_CLASSES = ("creature_unit_like", "quest_object_outline_like", "overhead_symbol_like")
REMAP = {0: 0, 1: 0, 2: 0, 3: 1, 5: 2}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def remap_label_text(text: str) -> tuple[str, dict[int, int]]:
    lines, counts = [], {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        mapped = REMAP.get(int(float(parts[0])))
        if mapped is None:
            continue
        counts[mapped] = counts.get(mapped, 0) + 1
        lines.append(" ".join([str(mapped), *parts[1:5]]))
    return "".join(line + "\n" for line in lines), counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"output already exists: {args.out}")
    summary: dict[str, dict] = {}
    for split in ("train", "val", "test"):
        images = args.source / "images" / split
        if not images.is_dir():
            continue
        (args.out / "images" / split).mkdir(parents=True)
        (args.out / "labels" / split).mkdir(parents=True)
        totals = {"images": 0, "empty": 0, "boxes": {name: 0 for name in UNIT_CLASSES}}
        for image in sorted(images.iterdir()):
            if image.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            target = args.out / "images" / split / image.name
            try:
                os.link(image, target)
            except OSError:
                shutil.copy2(image, target)
            label = args.source / "labels" / split / f"{image.stem}.txt"
            text, counts = remap_label_text(label.read_text(encoding="utf-8") if label.is_file() else "")
            (args.out / "labels" / split / f"{image.stem}.txt").write_text(text, encoding="utf-8")
            totals["images"] += 1
            totals["empty"] += not text
            for class_id, count in counts.items():
                totals["boxes"][UNIT_CLASSES[class_id]] += count
        summary[split] = totals
    (args.out / "data.yaml").write_text(
        f"path: '{args.out.resolve().as_posix()}'\ntrain: images/train\nval: images/val\ntest: images/test\n"
        "names:\n" + "".join(f"  {i}: {name}\n" for i, name in enumerate(UNIT_CLASSES)), encoding="utf-8")
    (args.out / "sources.json").write_text(json.dumps(
        {"source": str(args.source.resolve()), "remap": {str(k): v for k, v in REMAP.items()},
         "summary": summary}, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
