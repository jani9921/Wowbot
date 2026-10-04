"""Combine reviewed YOLO exports while preserving their existing splits."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil


SPLITS = ("train", "val", "test")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("sources", nargs="+", type=Path)
    args = parser.parse_args()

    out = args.out.resolve()
    sources = [source.resolve() for source in args.sources]
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"Output must be absent or empty: {out}")

    copied: dict[str, int] = {split: 0 for split in SPLITS}
    seen: set[str] = set()
    for split in SPLITS:
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    for source_index, source in enumerate(sources):
        if not (source / "data.yaml").is_file():
            raise SystemExit(f"Not a YOLO export: {source}")
        prefix = f"s{source_index}_{source.name}__"
        for split in SPLITS:
            for image in sorted((source / "images" / split).glob("*")):
                if not image.is_file():
                    continue
                label = source / "labels" / split / f"{image.stem}.txt"
                if not label.is_file():
                    raise SystemExit(f"Missing label for {image}")
                target_stem = prefix + image.stem
                if target_stem in seen:
                    raise SystemExit(f"Duplicate target stem: {target_stem}")
                seen.add(target_stem)
                shutil.copy2(image, out / "images" / split / f"{target_stem}{image.suffix.lower()}")
                shutil.copy2(label, out / "labels" / split / f"{target_stem}.txt")
                copied[split] += 1

    classes_path = sources[0].parent / "world3d_labeling_4k_v1" / "classes.txt"
    if classes_path.is_file():
        names = [line.strip() for line in classes_path.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    else:
        names = [
            "humanoid_unit_like", "creature_unit_like", "corpse_like",
            "quest_object_outline_like", "world_object_like",
            "overhead_symbol_like", "entrance_or_door_like",
        ]
    yaml_lines = [
        f"path: '{out.as_posix()}'", "train: images/train", "val: images/val",
        "test: images/test", "names:",
        *[f"  {index}: {name}" for index, name in enumerate(names)],
    ]
    (out / "data.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    (out / "sources.json").write_text(json.dumps({
        "sources": [str(source) for source in sources],
        "preserved_splits": True,
        "image_counts": copied,
        "total_images": sum(copied.values()),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(out), "counts": copied,
                      "total": sum(copied.values())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
