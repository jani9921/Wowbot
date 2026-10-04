"""Generate review-only bbox proposals with the existing World3D V3 stack."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.world3d.annotation_review import (
    bootstrap_box,
    proposal_from_candidate,
    suppress_overlapping_proposals,
)
from wowbot.vision.world3d.scene import build_scene_roi
from wowbot.vision.world3d.v3 import World3DPerceptionV3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--minimum-confidence", type=float, default=.54)
    parser.add_argument("--max-proposals", type=int, default=14)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--unreviewed-only", action="store_true",
                        help="Skip frames which already have an explicit review JSON")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after this many eligible frames; 0 means unlimited")
    parser.add_argument("--bootstrap-model", default="yolo11n.pt",
                        help="Generic pretrained proposal model; empty disables it")
    parser.add_argument("--bootstrap-confidence", type=float, default=.20,
                        help="Inference/review floor for bootstrap-model proposals")
    parser.add_argument("--model-only", action="store_true",
                        help="Use only bootstrap-model boxes; omit heuristic V3 proposals")
    args = parser.parse_args()

    manifest_path = args.dataset / "review" / "manifest.jsonl"
    if not manifest_path.is_file():
        raise SystemExit(f"Missing review manifest: {manifest_path}")
    records = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    proposal_dir = args.dataset / "review" / "proposals"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    pipelines: dict[str, World3DPerceptionV3] = {}
    bootstrap_model = None
    if args.bootstrap_model:
        from ultralytics import YOLO
        bootstrap_model = YOLO(args.bootstrap_model)
    totals: Counter[str] = Counter()

    eligible = []
    review_dir = args.dataset / "review" / "reviews"
    for record in records:
        image_path = args.dataset / record["image"]
        if (args.unreviewed_only
                and (review_dir / f"{image_path.stem}.json").is_file()):
            totals["reviewed_skipped"] += 1
            continue
        eligible.append(record)
        if args.limit > 0 and len(eligible) >= args.limit:
            break

    for index, record in enumerate(eligible, 1):
        image_path = args.dataset / record["image"]
        output_path = proposal_dir / f"{image_path.stem}.json"
        if output_path.exists() and not args.overwrite:
            totals["existing"] += 1
            continue
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            totals["unreadable"] += 1
            continue
        height, width = frame.shape[:2]
        raw = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA).tobytes()
        source = str(record["source_id"])
        pipeline = pipelines.setdefault(source, World3DPerceptionV3(detector_hz=15.0))
        scene = build_scene_roi(width, height)
        proposals = []
        if not args.model_only:
            candidates = pipeline.process(
                raw, width, height, scene,
                observed_at=float(record.get("timestamp_seconds") or index),
            )
            proposals = [proposal for candidate in candidates
                         if (proposal := proposal_from_candidate(
                             candidate, width, height,
                             minimum_confidence=args.minimum_confidence)) is not None]
        if bootstrap_model is not None:
            result = bootstrap_model.predict(
                frame, imgsz=960, conf=max(.001, args.bootstrap_confidence),
                device=0, verbose=False)[0]
            names = result.names or {}
            for detected in (() if result.boxes is None else result.boxes):
                class_id = int(detected.cls[0].item())
                label = str(names.get(class_id, class_id) if isinstance(names, dict)
                            else names[class_id])
                proposal = bootstrap_box(
                    label, float(detected.conf[0].item()), detected.xyxy[0].tolist(),
                    width, height, excluded=scene.excluded_rects,
                    minimum_confidence=max(.001, args.bootstrap_confidence))
                if proposal is not None:
                    proposals.append(proposal)
        proposals = suppress_overlapping_proposals(
            proposals, limit=max(1, args.max_proposals))
        output_path.write_text(json.dumps({
            "image": record["image"],
            "source_id": source,
            "timestamp_seconds": record.get("timestamp_seconds"),
            "generator": "WORLD3D_V3_REVIEW_PROPOSAL",
            "semantic_contract": "UNKNOWN_FIRST_HUMAN_REVIEW_REQUIRED",
            "proposals": [item.to_dict() for item in proposals],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        totals["generated"] += 1
        totals["boxes"] += len(proposals)
        if index % 50 == 0:
            print(f"{index}/{len(eligible)} frames; proposals={totals['boxes']}")
    print(json.dumps(dict(totals), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
