"""Offline map-marker dataset helpers: review pool, export, training gate.

Layout (one dataset per surface, mirroring the World3D review layout)::

    <dataset>/review/images/<stem>.<ext>      crops (copied from collectors)
    <dataset>/review/proposals/<stem>.json    {"proposals": [...], "facts": {...}}
    <dataset>/review/manifest.jsonl           {"image", "group", "surface", ...}
    <dataset>/review/reviews/<stem>.json      human decisions (reviewer tool)
    <dataset>/review/labels/<stem>.txt        YOLO lines of accepted boxes
    <dataset>/images|labels/{train,val,test}  export (whole groups per split)

Only reviewed frames are exported.  Splits are by *group* (live session /
capture segment) so near-identical consecutive crops never leak between
train and validation.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

from .map_markers import MAP_MARKER_YOLO_CLASSES, QUEST_MARKER_CLASSES


IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_review_pool(sources: list[Path], dataset: Path, *, surface: str) -> dict:
    """Copy collector samples of one surface into ``dataset/review``.

    ``sources`` are collector surface folders (``.../map-marker-dataset/
    world_map``) or their parent.  Existing review decisions are preserved;
    re-running only adds new samples.
    """
    review = dataset / "review"
    for name in ("images", "proposals", "reviews", "labels"):
        (review / name).mkdir(parents=True, exist_ok=True)
    manifest_path = review / "manifest.jsonl"
    known = set()
    if manifest_path.is_file():
        known = {json.loads(line)["image"] for line in
                 manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    added = skipped = 0
    rows = []
    for source in sources:
        folder = source / surface.lower() if (source / surface.lower()).is_dir() else source
        for meta_path in sorted((folder / "meta").glob("*.json")):
            meta = _read_json(meta_path)
            if meta.get("surface") != surface:
                skipped += 1
                continue
            image_path = folder / meta["image"]
            if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_SUFFIXES:
                skipped += 1
                continue
            relative = f"review/images/{image_path.name}"
            if relative in known:
                continue
            shutil.copy2(image_path, dataset / relative)
            facts = {"state": meta.get("state"), "verification": meta.get("verification"),
                     "crop": meta.get("crop"), "frame_size": meta.get("frame_size")}
            (review / "proposals" / f"{image_path.stem}.json").write_text(json.dumps(
                {"proposals": meta.get("proposals") or [], "facts": facts},
                ensure_ascii=False, indent=1), encoding="utf-8")
            group = str((meta.get("provenance") or {}).get("session_id")
                        or (meta.get("state") or {}).get("session_id") or folder.parent.name)
            rows.append({"image": relative, "group": group, "surface": surface,
                         "sample_id": meta.get("sample_id"), "observed_at": meta.get("observed_at")})
            known.add(relative)
            added += 1
    if rows:
        with manifest_path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"added": added, "skipped": skipped, "total": len(known)}


def assign_split(group: str, *, val_fraction: float = .15, test_fraction: float = .15) -> str:
    """Deterministic group -> split assignment."""
    bucket = int(hashlib.sha1(group.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    if bucket < test_fraction:
        return "test"
    if bucket < test_fraction + val_fraction:
        return "val"
    return "train"


def reviewed_records(dataset: Path) -> list[dict]:
    review = dataset / "review"
    manifest = review / "manifest.jsonl"
    if not manifest.is_file():
        return []
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    return [row for row in rows
            if (review / "reviews" / f"{Path(row['image']).stem}.json").is_file()
            and (review / "labels" / f"{Path(row['image']).stem}.txt").is_file()]


def export_dataset(dataset: Path, *, val_fraction: float = .15,
                   test_fraction: float = .15) -> dict:
    """Write images/labels split folders and data.yaml from reviewed frames.

    Groups are assigned deterministically; when hashing leaves val or test
    empty but at least three groups exist, the smallest train groups are
    moved so every split is populated (still whole groups, no leakage).
    """
    records = reviewed_records(dataset)
    groups: dict[str, list[dict]] = {}
    for row in records:
        groups.setdefault(str(row.get("group") or "unknown"), []).append(row)
    split_of = {group: assign_split(group, val_fraction=val_fraction,
                                    test_fraction=test_fraction) for group in groups}
    for needed in ("val", "test"):
        if needed not in split_of.values():
            train_groups = sorted((g for g, s in split_of.items() if s == "train"),
                                  key=lambda g: (len(groups[g]), g))
            if len(train_groups) >= 2:
                split_of[train_groups[0]] = needed
    for split in ("train", "val", "test"):
        for kind in ("images", "labels"):
            target = dataset / kind / split
            if target.is_dir():
                shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=True)
    counts: dict[str, Counter] = {split: Counter() for split in ("train", "val", "test")}
    frames = Counter()
    for group, rows in groups.items():
        split = split_of[group]
        for row in rows:
            image = dataset / row["image"]
            label = dataset / "review" / "labels" / f"{image.stem}.txt"
            shutil.copy2(image, dataset / "images" / split / image.name)
            shutil.copy2(label, dataset / "labels" / split / label.name)
            frames[split] += 1
            for line in label.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    counts[split][MAP_MARKER_YOLO_CLASSES[int(line.split()[0])]] += 1
    names = "\n".join(f"  {index}: {name}" for index, name in enumerate(MAP_MARKER_YOLO_CLASSES))
    (dataset / "data.yaml").write_text(
        f"path: {dataset.resolve().as_posix()}\ntrain: images/train\nval: images/val\n"
        f"test: images/test\nnames:\n{names}\n", encoding="utf-8")
    summary = {"frames": dict(frames), "groups": {s: sorted(g for g, v in split_of.items() if v == s)
                                                  for s in ("train", "val", "test")},
               "class_counts": {split: dict(counter) for split, counter in counts.items()}}
    (dataset / "export_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def quest_class_coverage(summary: dict, *, minimum_train: int = 20,
                         minimum_val: int = 3) -> dict:
    """Training gate: a model may only be trained when quest classes exist.

    The player arrow alone would train "successfully" and then be mistaken for
    a working quest-marker detector.  At least one quest class must reach the
    train/val minimums; every class below them is reported.
    """
    train = summary.get("class_counts", {}).get("train", {})
    val = summary.get("class_counts", {}).get("val", {})
    ready = sorted(name for name in QUEST_MARKER_CLASSES
                   if train.get(name, 0) >= minimum_train and val.get(name, 0) >= minimum_val)
    insufficient = sorted(name for name in QUEST_MARKER_CLASSES if name not in ready)
    return {"ready_classes": ready, "insufficient_classes": insufficient,
            "train_counts": dict(train), "val_counts": dict(val),
            "training_ready": bool(ready)}
