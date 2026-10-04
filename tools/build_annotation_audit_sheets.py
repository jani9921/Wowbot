"""Build large contact sheets for visual audit of annotation proposals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--source", default="COCO_BOOTSTRAP_REVIEW")
    parser.add_argument("--class-id", type=int, action="append", default=[],
                        help="Keep only these proposal class ids (repeatable)")
    parser.add_argument("--include-all", action="store_true",
                        help="Include every eligible frame even without a matching proposal")
    parser.add_argument("--unreviewed-only", action="store_true",
                        help="Skip frames which already have an explicit review JSON")
    parser.add_argument("--minimum-confidence", type=float, default=.45)
    parser.add_argument("--absence-of-source", action="store_true",
                        help="Audit frames with no proposal from the selected source")
    parser.add_argument("--sample-limit", type=int, default=0)
    args = parser.parse_args()

    rows = []
    for proposal_file in sorted((args.dataset / "review" / "proposals").glob("*.json")):
        payload = json.loads(proposal_file.read_text(encoding="utf-8"))
        if args.unreviewed_only:
            review_path = (args.dataset / "review" / "reviews" /
                           f"{Path(payload['image']).stem}.json")
            if review_path.is_file():
                continue
        boxes = [(index, box) for index, box in enumerate(payload.get("proposals", []))
                 if (args.source == "*" or box.get("source") == args.source)
                 and float(box.get("confidence") or 0) >= args.minimum_confidence
                 and (not args.class_id or int(box.get("class_id", -1)) in args.class_id)]
        if args.include_all or ((boxes and not args.absence_of_source)
                                or (not boxes and args.absence_of_source)):
            rows.append((proposal_file, payload, boxes))

    if args.sample_limit and len(rows) > args.sample_limit:
        count = max(1, args.sample_limit)
        rows = [rows[round(index * (len(rows) - 1) / (count - 1))]
                for index in range(count)] if count > 1 else [rows[0]]

    args.out.mkdir(parents=True, exist_ok=True)
    mapping = []
    for offset in range(0, len(rows), 4):
        tiles = []
        for local_index, (proposal_file, payload, boxes) in enumerate(rows[offset:offset + 4]):
            frame_id = offset + local_index
            image = cv2.imread(str(args.dataset / payload["image"]), cv2.IMREAD_COLOR)
            if image is None:
                raise RuntimeError(f"Cannot read {payload['image']}")
            mapped_boxes = []
            for box_index, box in boxes:
                color = (0, 255, 0) if int(box["class_id"]) == 0 else (0, 165, 255)
                cv2.rectangle(image, (int(box["left"]), int(box["top"])),
                              (int(box["right"]), int(box["bottom"])), color, 3)
                text = f"B{box_index} c{box['class_id']} {float(box['confidence']):.2f}"
                cv2.putText(image, text, (int(box["left"]), max(22, int(box["top"]) - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, .6, color, 2, cv2.LINE_AA)
                mapped_boxes.append({"box_index": box_index, **box})
            cv2.rectangle(image, (0, 0), (560, 34), (0, 0, 0), -1)
            cv2.putText(image, f"F{frame_id:02d} {Path(payload['image']).name[-42:]}",
                        (6, 24), cv2.FONT_HERSHEY_SIMPLEX, .55,
                        (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(cv2.resize(image, (640, 360), interpolation=cv2.INTER_AREA))
            mapping.append({
                "frame_id": frame_id,
                "proposal_file": proposal_file.name,
                "image": payload["image"],
                "boxes": mapped_boxes,
            })
        while len(tiles) < 4:
            tiles.append(np.zeros((360, 640, 3), dtype=np.uint8))
        sheet = np.vstack((np.hstack(tiles[:2]), np.hstack(tiles[2:4])))
        cv2.imwrite(str(args.out / f"sheet_{offset // 4:02d}.jpg"), sheet,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    (args.out / "mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"frames={len(rows)} sheets={(len(rows) + 3) // 4} mapping={args.out / 'mapping.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
