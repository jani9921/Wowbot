"""Build a review pool that fills missing unit labels in an exported YOLO dataset.

Existing reviewed labels are remapped to the single-unit taxonomy and loaded as
ACCEPTED boxes.  Model detections that overlap no existing unit label become
PROPOSED boxes for the human reviewer.  Frames without any such proposal keep
their prior labels and are marked reviewed so the annotator skips them.

Taxonomy while reviewing (annotator buttons are unchanged):
  1 = creature_unit_like: every unit (humanoid, creature and corpse merged)
  3 = quest_object_outline_like (drawn again on an outlined unit's body)
  5 = overhead_symbol_like (the ! or ? symbol only)
World-object (4) and entrance/door (6) labels are dropped (too few examples).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

UNIT_CLASS = 1
REMAP = {0: UNIT_CLASS, 1: UNIT_CLASS, 2: UNIT_CLASS, 3: 3, 5: 5}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def remap_class(class_id: int) -> int | None:
    return REMAP.get(class_id)


def read_yolo_boxes(label: Path, width: int, height: int) -> list[tuple[int, list[float]]]:
    boxes = []
    if not label.is_file():
        return boxes
    for line in label.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        mapped = remap_class(int(float(parts[0])))
        if mapped is None:
            continue
        x, y, w, h = map(float, parts[1:5])
        boxes.append((mapped, [(x - w / 2) * width, (y - h / 2) * height,
                               (x + w / 2) * width, (y + h / 2) * height]))
    return boxes


def iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0., x2 - x1) * max(0., y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.


def missing_unit_proposals(labels, detections, *, iou_threshold: float = .3):
    """Return unit detections that overlap no existing unit label or each other."""
    units = [box for class_id, box in labels if class_id == UNIT_CLASS]
    kept: list[tuple[list[float], float]] = []
    for box, confidence in sorted(detections, key=lambda item: -item[1]):
        if any(iou(box, other) >= iou_threshold for other in units):
            continue
        if any(iou(box, other) >= .5 for other, _ in kept):
            continue
        kept.append((box, confidence))
    return kept


def _box(index: int, box, class_id: int, confidence: float, status: str, source: str) -> dict:
    left, top, right, bottom = (int(round(value)) for value in box)
    return {"box_id": f"b{index}", "left": left, "top": top, "right": right, "bottom": bottom,
            "class_id": class_id, "confidence": round(float(confidence), 4),
            "status": status, "source": source, "candidate_kind": ""}


def _yolo_line(box: dict, width: int, height: int) -> str:
    cx = (box["left"] + box["right"]) / 2 / width
    cy = (box["top"] + box["bottom"]) / 2 / height
    w = (box["right"] - box["left"]) / width
    h = (box["bottom"] - box["top"]) / height
    return f"{box['class_id']} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def _link_or_copy(source: Path, target: Path) -> None:
    if target.exists():
        return
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def original_stem(stem: str) -> str:
    """Strip nested ``s<N>_world3d_...__`` combine prefixes from an exported stem."""
    parts = stem.split("__")
    last = max((i for i, part in enumerate(parts) if re.match(r"^s\d+_world3d_", part)), default=-1)
    return "__".join(parts[last + 1:])


def _add_frame(model, args, review: Path, image: Path, label: Path, record: dict,
               target_name: str, totals: dict) -> bool:
    """Link one frame into the pool with remapped labels and missing-unit proposals.

    Never overwrites anything that already exists in the pool."""
    import cv2

    target = review / "images" / target_name
    stem = Path(target_name).stem
    if target.exists() or (review / "reviews" / f"{stem}.json").exists() \
            or (review / "proposals" / f"{stem}.json").exists():
        return False
    frame = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if frame is None:
        return False
    height, width = frame.shape[:2]
    labels = read_yolo_boxes(label, width, height)
    result = model.predict(frame, conf=args.conf, imgsz=args.imgsz, device=args.device, verbose=False)[0]
    detections = [(box.tolist(), float(confidence))
                  for cls, box, confidence in zip(result.boxes.cls, result.boxes.xyxy, result.boxes.conf)
                  if remap_class(int(cls)) == UNIT_CLASS]
    missing = missing_unit_proposals(labels, detections)
    _link_or_copy(image, target)
    boxes = [_box(i, box, class_id, 1., "ACCEPTED", "PRIOR_REVIEWED_LABEL_REMAPPED")
             for i, (class_id, box) in enumerate(labels)]
    boxes += [_box(len(boxes) + i, box, UNIT_CLASS, confidence, "PROPOSED", "MISSING_UNIT_MODEL_PROPOSAL")
              for i, (box, confidence) in enumerate(missing)]
    totals["frames"] += 1
    totals["prior_boxes"] += len(labels)
    totals["proposals"] += len(missing)
    if missing:
        totals["frames_to_review"] += 1
        (review / "proposals" / f"{stem}.json").write_text(
            json.dumps({"image": record["image"], "proposals": boxes}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    else:
        (review / "labels" / f"{stem}.txt").write_text(
            "".join(_yolo_line(box, width, height) + "\n" for box in boxes), encoding="utf-8")
        (review / "reviews" / f"{stem}.json").write_text(json.dumps({
            "image": record["image"], "review_status": "REVIEWED_EMPTY" if not boxes else "REVIEWED",
            "accepted_count": len(boxes), "boxes": boxes, "rejected_proposal_count": 0,
            "reviewer": "PRIOR_LABELS_NO_MISSING_PROPOSAL"}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return True


def append_from_pools(model, args) -> dict:
    """Add every human-saved frame of ``args.source/*/review`` that the pool lacks."""
    review = args.out / "review"
    manifest_path = review / "manifest.jsonl"
    existing = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    known = {original_stem(Path(str(row["image"])).stem) for row in existing}
    known |= {original_stem(Path(str(row["image"])).stem).split("__", 1)[-1] for row in existing
              if row.get("source_pool")}
    totals = {"frames": 0, "prior_boxes": 0, "proposals": 0, "frames_to_review": 0, "already_present": 0}
    added = []
    for review_dir in sorted(args.source.glob("*/review/reviews")):
        pool = review_dir.parent.parent
        for review_path in sorted(review_dir.glob("*.json")):
            saved = json.loads(review_path.read_text(encoding="utf-8"))
            if saved.get("review_status") not in {"REVIEWED", "REVIEWED_EMPTY"}:
                continue
            stem = review_path.stem
            if stem in known:
                totals["already_present"] += 1
                continue
            image = pool / str(saved["image"]).replace("\\", "/")
            label = pool / "review" / "labels" / f"{stem}.txt"
            if not image.is_file() or not label.is_file():
                continue
            target_name = f"{pool.name}__{stem}{image.suffix.lower()}"
            record = {"image": f"review/images/{target_name}", "split": None,
                      "source_dataset": pool.name, "source_pool": pool.name}
            if _add_frame(model, args, review, image, label, record, target_name, totals):
                added.append(record)
                known.add(stem)
    if added:
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.writelines(json.dumps(record, ensure_ascii=False) + "\n" for record in added)
    return totals


UNIT_MODEL_TO_BUTTON = {0: UNIT_CLASS, 1: 3, 2: 5}  # 3-class unit model -> annotator buttons


def append_unlabeled_frames(model, args, pool_dir: Path) -> dict:
    """Add never-saved frames of one pool as UNREVIEWED frames with model proposals.

    No review file is written, even when the model proposes nothing, because an
    empty proposal list is not evidence that the frame contains no unit."""
    import cv2

    review = args.out / "review"
    manifest_path = review / "manifest.jsonl"
    existing = {json.loads(line)["image"] for line in manifest_path.read_text(encoding="utf-8").splitlines()
                if line.strip()}
    source = pool_dir / "review"
    records = [json.loads(line) for line in (source / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    totals = {"frames": 0, "proposals": 0, "skipped_saved": 0, "already_present": 0}
    added = []
    for row in records:
        image = pool_dir / str(row["image"]).replace("\\", "/")
        stem = image.stem
        if (source / "reviews" / f"{stem}.json").exists():
            totals["skipped_saved"] += 1
            continue
        target_name = f"{pool_dir.name}__{stem}{image.suffix.lower()}"
        record = {"image": f"review/images/{target_name}", "split": None,
                  "source_dataset": pool_dir.name, "source_pool": pool_dir.name}
        target = review / "images" / target_name
        if record["image"] in existing or target.exists():
            totals["already_present"] += 1
            continue
        frame = cv2.imread(str(image), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        result = model.predict(frame, conf=args.conf, imgsz=args.imgsz, device=args.device, verbose=False)[0]
        boxes = [_box(i, box.tolist(), UNIT_MODEL_TO_BUTTON[int(cls)], float(confidence), "PROPOSED",
                      "UNIT_MODEL_FRESH_PROPOSAL")
                 for i, (cls, box, confidence) in enumerate(zip(result.boxes.cls, result.boxes.xyxy, result.boxes.conf))
                 if int(cls) in UNIT_MODEL_TO_BUTTON]
        _link_or_copy(image, target)
        (review / "proposals" / f"{Path(target_name).stem}.json").write_text(
            json.dumps({"image": record["image"], "proposals": boxes}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        added.append(record)
        totals["frames"] += 1
        totals["proposals"] += len(boxes)
    if added:
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.writelines(json.dumps(record, ensure_ascii=False) + "\n" for record in added)
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="exported YOLO dataset with images/<split> and labels/<split>, "
                                                   "or with --append-from-pools the folder holding the review pools")
    parser.add_argument("out", type=Path, help="new review pool (must not exist unless appending)")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--conf", type=float, default=.06)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    parser.add_argument("--append-from-pools", action="store_true",
                        help="add missing human-saved frames from <source>/*/review to an existing pool; "
                             "existing images, reviews and proposals are never touched")
    parser.add_argument("--append-unlabeled-pool", type=Path,
                        help="add never-saved frames of this one review pool as UNREVIEWED frames with proposals "
                             "from a 3-class unit model (--model); <source> is ignored")
    args = parser.parse_args()
    if args.append_unlabeled_pool:
        if not (args.out / "review" / "manifest.jsonl").is_file():
            parser.error(f"not an existing review pool: {args.out}")
        from ultralytics import YOLO
        print(json.dumps(append_unlabeled_frames(YOLO(str(args.model)), args, args.append_unlabeled_pool)))
        return 0
    if args.append_from_pools:
        if not (args.out / "review" / "manifest.jsonl").is_file():
            parser.error(f"not an existing review pool: {args.out}")
    elif args.out.exists():
        parser.error(f"output already exists: {args.out}")

    from ultralytics import YOLO

    model = YOLO(str(args.model))
    if args.append_from_pools:
        print(json.dumps(append_from_pools(model, args)))
        return 0
    review = args.out / "review"
    for name in ("images", "proposals", "reviews", "labels"):
        (review / name).mkdir(parents=True, exist_ok=True)
    manifest = []
    totals = {"frames": 0, "prior_boxes": 0, "proposals": 0, "frames_to_review": 0}
    for split in ("train", "val", "test"):
        for image in sorted((args.source / "images" / split).glob("*")):
            if image.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            record = {"image": f"review/images/{image.name}", "split": split, "source_dataset": args.source.name}
            if _add_frame(model, args, review, image, args.source / "labels" / split / f"{image.stem}.txt",
                          record, image.name, totals):
                manifest.append(record)
    (review / "manifest.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in manifest), encoding="utf-8")
    (args.out / "README.txt").write_text(
        "Unit relabel pool. Review with: python tools/review_world3d_annotations.py <this folder> --start-unreviewed\n"
        "Use class 1 for EVERY visible unit (NPC, mob, corpse), 3 for a quest outline (also on an outlined unit), "
        "5 for the overhead symbol.\n"
        f"Built from {args.source} with {args.model.name}, conf>={args.conf}.\n", encoding="utf-8")
    print(json.dumps(totals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
