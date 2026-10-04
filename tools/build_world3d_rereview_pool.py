"""Build a full re-review pool from an existing, human-reviewed unit pool.

User 2026-10-02 ("átnézem újra a képeket"): every frame is reviewed again under
one consistent rule set.  The source pool is only read; nothing in it changes.

Each frame of the new pool starts UNREVIEWED with:
  * the previously saved boxes as ACCEPTED (source PRIOR_REVIEW),
  * model detections that overlap no saved box of the same class as PROPOSED
    (source REREVIEW_MODEL_PROPOSAL); many were rejected before, so they are
    shown again for a consistent decision,
  * when no saved unit stands in the own-avatar zone, the model's best unit
    detection there (even a weak one) as PROPOSED, candidate_kind
    ``self_avatar`` -- the avatar was labeled in only ~25 % of frames.

Annotator buttons: 1 = unit, 3 = quest outline, 5 = overhead symbol.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil

UNIT_MODEL_TO_BUTTON = {0: 1, 1: 3, 2: 5}  # 3-class unit model -> annotator buttons
UNIT_BUTTON = 1
AVATAR_MAX_CENTER_OFFSET = .10   # wider than the live tracker's .06: proposal only
AVATAR_MIN_BOTTOM = .55
AVATAR_MIN_HEIGHT = .12
AVATAR_MIN_CONFIDENCE = .05
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

RULES = """Re-review rules (proposed 2026-10-02, confirm with the user):
  1 = unit: EVERY unit that can be targeted -- NPC, mob, critter, other player,
      training dummy, corpse -- including far/small ones you can still recognise
      and ones cut by the screen edge when at least about half is visible.
      Your OWN character always gets a unit box too.
  3 = quest outline: drawn again on the outlined unit/object.
  5 = overhead symbol: only the ! or ? itself.
  Never: UI (quest-window portraits, nameplates, chat bubbles), fire, props,
  buildings, mounts' empty saddles, minimap.
Keys: ENTER save+next unreviewed, <-/-> previous/next, SPACE accept/toggle,
  D delete, A accept all, X delete unaccepted, E save empty, Q quit.
"""


def iou(a, b) -> float:
    ix = max(0., min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0., min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.


def in_avatar_zone(box, width: int, height: int) -> bool:
    center = (box[0] + box[2]) / 2 / width
    return (abs(center - .5) < AVATAR_MAX_CENTER_OFFSET
            and box[3] / height > AVATAR_MIN_BOTTOM
            and (box[3] - box[1]) / height > AVATAR_MIN_HEIGHT)


def _box(box_id: str, box, class_id: int, confidence: float, status: str, source: str,
         kind: str = "") -> dict:
    left, top, right, bottom = (int(round(value)) for value in box)
    return {"box_id": box_id, "left": left, "top": top, "right": right, "bottom": bottom,
            "class_id": class_id, "confidence": round(float(confidence), 4),
            "status": status, "source": source, "candidate_kind": kind}


def rereview_boxes(prior: list[dict], detections: list[tuple[int, list[float], float]],
                   width: int, height: int, *, conf: float) -> list[dict]:
    """Prior boxes ACCEPTED + missing model boxes and an avatar box PROPOSED.

    ``detections`` are (annotator class, xyxy, confidence), any confidence."""
    boxes = [{**box, "status": "ACCEPTED", "source": "PRIOR_REVIEW",
              "box_id": f"p{index}"} for index, box in enumerate(prior)]
    prior_xyxy = [(box["class_id"], (box["left"], box["top"], box["right"], box["bottom"]))
                  for box in prior]
    proposed: list[tuple[int, list[float]]] = []
    for class_id, xyxy, confidence in sorted(detections, key=lambda item: -item[2]):
        if confidence < conf:
            continue
        if any(class_id == other_class and iou(xyxy, other) >= .3 for other_class, other in prior_xyxy):
            continue
        if any(class_id == other_class and iou(xyxy, other) >= .5 for other_class, other in proposed):
            continue
        proposed.append((class_id, xyxy))
        boxes.append(_box(f"m{len(proposed)}", xyxy, class_id, confidence, "PROPOSED",
                          "REREVIEW_MODEL_PROPOSAL"))
    avatar_labeled = any(class_id == UNIT_BUTTON and in_avatar_zone(xyxy, width, height)
                         for class_id, xyxy in prior_xyxy)
    if not avatar_labeled:
        candidates = [(confidence, xyxy) for class_id, xyxy, confidence in detections
                      if class_id == UNIT_BUTTON and confidence >= AVATAR_MIN_CONFIDENCE
                      and in_avatar_zone(xyxy, width, height)]
        if candidates:
            confidence, xyxy = max(candidates, key=lambda item: item[0])
            already = next((box for box in boxes if box["status"] == "PROPOSED"
                            and box["class_id"] == UNIT_BUTTON
                            and iou(xyxy, (box["left"], box["top"], box["right"], box["bottom"])) >= .5),
                           None)
            if already is not None:
                already["candidate_kind"] = "self_avatar"
            else:
                boxes.append(_box("avatar", xyxy, UNIT_BUTTON, confidence, "PROPOSED",
                                  "REREVIEW_AVATAR_PROPOSAL", "self_avatar"))
    return boxes


def _link_or_copy(source: Path, target: Path) -> None:
    if target.exists():
        return
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def build(model, source: Path, out: Path, *, conf: float, imgsz: int, device, batch: int = 16) -> dict:
    import cv2

    src_review, review = source / "review", out / "review"
    for name in ("images", "proposals", "reviews", "labels"):
        (review / name).mkdir(parents=True, exist_ok=True)
    records = [json.loads(line) for line in
               (src_review / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    totals = {"frames": 0, "prior_boxes": 0, "model_proposals": 0, "avatar_proposals": 0,
              "frames_without_saved_review": 0}
    kept = []
    for start in range(0, len(records), batch):
        chunk = []
        for record in records[start:start + batch]:
            image = source / str(record["image"]).replace("\\", "/")
            if image.suffix.lower() not in IMAGE_SUFFIXES or not image.is_file():
                continue
            frame = cv2.imread(str(image), cv2.IMREAD_COLOR)
            if frame is not None:
                chunk.append((record, image, frame))
        if not chunk:
            continue
        results = model.predict([frame for _, _, frame in chunk], conf=AVATAR_MIN_CONFIDENCE,
                                imgsz=imgsz, device=device, verbose=False)
        for (record, image, frame), result in zip(chunk, results):
            height, width = frame.shape[:2]
            saved = src_review / "reviews" / f"{image.stem}.json"
            if saved.is_file():
                prior = json.loads(saved.read_text(encoding="utf-8")).get("boxes") or []
            else:
                prior = []
                totals["frames_without_saved_review"] += 1
            detections = [(UNIT_MODEL_TO_BUTTON[int(cls)], [float(v) for v in xyxy], float(score))
                          for cls, xyxy, score in zip(result.boxes.cls.tolist(), result.boxes.xyxy.tolist(),
                                                      result.boxes.conf.tolist())
                          if int(cls) in UNIT_MODEL_TO_BUTTON]
            boxes = rereview_boxes(prior, detections, width, height, conf=conf)
            _link_or_copy(image, review / "images" / image.name)
            (review / "proposals" / f"{image.stem}.json").write_text(
                json.dumps({"image": record["image"], "proposals": boxes}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            kept.append(record)
            totals["frames"] += 1
            totals["prior_boxes"] += len(prior)
            totals["model_proposals"] += sum(box["source"] == "REREVIEW_MODEL_PROPOSAL" for box in boxes)
            totals["avatar_proposals"] += sum(box["candidate_kind"] == "self_avatar" for box in boxes)
    (review / "manifest.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in kept), encoding="utf-8")
    (out / "README.txt").write_text(
        f"Full re-review pool built from {source.name} (read-only) with conf>={conf}.\n"
        f"Review with: python tools/review_world3d_annotations.py {out.as_posix()} --start-unreviewed\n"
        f"Export with: python tools/export_world3d_unit_review_pool.py {out.as_posix()} <new dataset>\n\n"
        + RULES, encoding="utf-8")
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="existing review pool (read only)")
    parser.add_argument("out", type=Path, help="new pool folder (must not exist)")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--conf", type=float, default=.4, help="threshold for missing-box proposals")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()
    if not (args.source / "review" / "manifest.jsonl").is_file():
        parser.error(f"not a review pool: {args.source}")
    if args.out.exists():
        parser.error(f"output already exists: {args.out}")
    from ultralytics import YOLO
    print(json.dumps(build(YOLO(str(args.model)), args.source, args.out, conf=args.conf,
                           imgsz=args.imgsz, device=args.device)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
