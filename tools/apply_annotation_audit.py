"""Apply explicit visual-audit decisions to review labels with provenance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.world3d.annotation_review import AnnotationBox, yolo_line
from uuid import uuid4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("decisions", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    mapping = {int(item["frame_id"]): item for item in
               json.loads(args.mapping.read_text(encoding="utf-8"))}
    decision_payload = json.loads(args.decisions.read_text(encoding="utf-8"))
    label_dir = args.dataset / "review" / "labels"
    review_dir = args.dataset / "review" / "reviews"
    label_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for decision in decision_payload["decisions"]:
        explicit_empty = bool(decision.get("empty", False))
        if explicit_empty and (
            decision.get("accept_box_indices")
            or decision.get("manual_boxes")
            or decision.get("class_overrides")
        ):
            raise ValueError(
                f"Frame {decision['frame_id']} is explicitly empty but also contains "
                "accepted boxes or class overrides"
            )
        row = mapping[int(decision["frame_id"])]
        proposal_file = args.dataset / "review" / "proposals" / row["proposal_file"]
        proposal_payload = json.loads(proposal_file.read_text(encoding="utf-8"))
        proposal_by_index = {index: AnnotationBox.from_dict(box) for index, box in
                             enumerate(proposal_payload["proposals"])}
        accepted = []
        overrides = {int(key): int(value) for key, value in
                     decision.get("class_overrides", {}).items()}
        for index in decision.get("accept_box_indices", []):
            box = proposal_by_index[int(index)]
            box.status = "ACCEPTED"
            if int(index) in overrides:
                box.class_id = overrides[int(index)]
            accepted.append(box)
        for manual in decision.get("manual_boxes", []):
            accepted.append(AnnotationBox(
                box_id=uuid4().hex[:12],
                left=int(manual["left"]), top=int(manual["top"]),
                right=int(manual["right"]), bottom=int(manual["bottom"]),
                class_id=int(manual["class_id"]), confidence=1.0,
                status="ACCEPTED", source="ASSISTANT_VISUAL_REVIEW",
                candidate_kind="human_review",
            ))
        image_path = args.dataset / row["image"]
        import cv2
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"Cannot read {image_path}")
        height, width = image.shape[:2]
        stem = image_path.stem
        label_path = label_dir / f"{stem}.txt"
        review_path = review_dir / f"{stem}.json"
        if (label_path.exists() or review_path.exists()) and not args.overwrite:
            raise FileExistsError(f"Review already exists: {stem}")
        label_path.write_text(
            "".join(yolo_line(box, width, height) + "\n" for box in accepted),
            encoding="utf-8")
        review_path.write_text(json.dumps({
            "image": row["image"],
            "review_status": "REVIEWED_EMPTY" if explicit_empty else "REVIEWED",
            "reviewer": decision_payload.get("reviewer", "VISUAL_AUDIT"),
            "audit_sheet": decision.get("audit_sheet"),
            "frame_id": decision["frame_id"],
            "accepted_count": len(accepted),
            "boxes": [box.to_dict() for box in accepted],
            "notes": decision.get("notes", ""),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1
    print(f"reviewed_frames={written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
