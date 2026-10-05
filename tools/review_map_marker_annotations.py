"""OpenCV review UI for World Map / minimap marker crops.

Same workflow as tools/review_world3d_annotations.py: proposals (player
arrow, projected addon quest POIs, tooltip-confirmed hover pins, heuristic
blue areas) are only suggestions; only an explicit save writes labels.

Keys: drag = draw box | click = select | 1-9 = class (also re-labels the
selected box) | SPACE = accept/unaccept | A = accept all | D = delete box |
X = delete unaccepted | ENTER = save + next unreviewed | E = save EMPTY + next |
N/P = next/previous | [ ] = previous/next unreviewed | +/- = zoom | Q = quit
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

import cv2

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.map_markers import (MAP_MARKER_CLASS_TITLES,  # noqa: E402
                                       MAP_MARKER_YOLO_CLASSES, map_yolo_line)
from wowbot.vision.world3d.annotation_review import AnnotationBox, contains  # noqa: E402


WINDOW = "AIPC map-marker annotator"
HEADER = 166
CLASS_COLORS = (
    (40, 220, 255),   # quest_available - yellow
    (255, 170, 40),   # repeatable offer - blue
    (40, 120, 255),   # special offer - orange
    (80, 255, 255),   # turn-in - light yellow
    (255, 210, 120),  # repeatable turn-in - light blue
    (255, 80, 200),   # objective pin - violet
    (255, 120, 40),   # quest area - blue
    (60, 255, 120),   # edge arrow - green
    (240, 240, 240),  # player arrow - white
    (60, 230, 255),   # objective dot, same space - yellow
    (170, 170, 170),  # objective dot, other space - grey
    (120, 120, 200),  # objective dot below - grey/red
    (200, 120, 120),  # objective dot above - grey/blue
)


def load_boxes(payload: dict, key: str) -> list[AnnotationBox]:
    boxes = []
    for item in payload.get(key, []):
        item = {**item}
        item.setdefault("box_id", uuid4().hex[:12])
        item.setdefault("candidate_kind", str(item.get("source") or ""))
        box = AnnotationBox.from_dict(item)
        if 0 <= box.class_id < len(MAP_MARKER_YOLO_CLASSES) and box.width > 0 and box.height > 0:
            boxes.append(box)
    return boxes


def facts_line(facts: dict) -> str:
    state = facts.get("state") or {}
    verification = facts.get("verification") or {}
    quests = state.get("quests") or []
    pois = state.get("quest_locations") or []
    tooltip = ((state.get("map_mouseover") or {}).get("tooltip") or "").replace("\n", " | ")
    return (f"map={state.get('displayed_map_id') or state.get('map_id')} quests={len(quests)} "
            f"complete={sum(1 for q in quests if q.get('is_complete'))} pois={len(pois)} "
            f"projection={'OK' if verification.get('projection_verified') else 'unverified'} "
            f"tooltip={tooltip[:70]}")


class MapReviewer:
    def __init__(self, dataset: Path) -> None:
        self.dataset = dataset
        review = dataset / "review"
        manifest = review / "manifest.jsonl"
        if not manifest.is_file():
            raise RuntimeError(f"No review pool at {manifest}; run build_map_marker_review_pool.py")
        self.records = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()
                        if line.strip()]
        if not self.records:
            raise RuntimeError("Review pool is empty")
        self.proposal_dir, self.review_dir = review / "proposals", review / "reviews"
        self.label_dir = review / "labels"
        self.review_dir.mkdir(parents=True, exist_ok=True)
        self.label_dir.mkdir(parents=True, exist_ok=True)
        self.index = 0
        self.active_class = 0
        self.zoom = 1.0
        self.selected: int | None = None
        self.drag_start = self.drag_now = None
        self.boxes: list[AnnotationBox] = []
        self.facts: dict = {}
        self.message = ""
        self.scale = 1.0
        self.load()

    @property
    def image_path(self) -> Path:
        return self.dataset / self.records[self.index]["image"]

    def reviewed(self, index: int) -> bool:
        return (self.review_dir / f"{Path(self.records[index]['image']).stem}.json").is_file()

    def load(self) -> None:
        self.frame = cv2.imread(str(self.image_path), cv2.IMREAD_COLOR)
        if self.frame is None:
            raise RuntimeError(f"Cannot read {self.image_path}")
        stem = self.image_path.stem
        proposal = self.proposal_dir / f"{stem}.json"
        payload = json.loads(proposal.read_text(encoding="utf-8")) if proposal.is_file() else {}
        self.facts = payload.get("facts") or {}
        review = self.review_dir / f"{stem}.json"
        if review.is_file():
            saved = json.loads(review.read_text(encoding="utf-8"))
            self.boxes = load_boxes(saved, "boxes")
            self.message = f"{saved.get('review_status')} boxes={len(self.boxes)}"
        else:
            self.boxes = load_boxes(payload, "proposals")
            self.message = "UNREVIEWED"
        self.selected = None
        self.drag_start = self.drag_now = None

    def save(self, *, empty: bool = False) -> None:
        accepted = [] if empty else [box for box in self.boxes if box.status == "ACCEPTED"]
        height, width = self.frame.shape[:2]
        stem = self.image_path.stem
        (self.label_dir / f"{stem}.txt").write_text("".join(
            map_yolo_line(box.class_id, box.left, box.top, box.right, box.bottom, width, height) + "\n"
            for box in accepted), encoding="utf-8")
        (self.review_dir / f"{stem}.json").write_text(json.dumps({
            "image": self.records[self.index]["image"],
            "review_status": "REVIEWED_EMPTY" if empty else "REVIEWED",
            "accepted_count": len(accepted), "boxes": [box.to_dict() for box in accepted],
            "rejected_proposal_count": len(self.boxes) - len(accepted),
            "class_names": [MAP_MARKER_YOLO_CLASSES[box.class_id] for box in accepted],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        self.message = f"SAVED {len(accepted)} boxes"

    def move(self, amount: int, *, unreviewed: bool = False) -> None:
        candidate = self.index
        while True:
            candidate += amount
            if not 0 <= candidate < len(self.records):
                self.message = "No more frames" if unreviewed else self.message
                return
            if not unreviewed or not self.reviewed(candidate):
                self.index = candidate
                self.load()
                return

    def image_point(self, x: int, y: int):
        if y < HEADER:
            return None
        height, width = self.frame.shape[:2]
        return (min(width - 1, max(0, round(x / self.scale))),
                min(height - 1, max(0, round((y - HEADER) / self.scale))))

    def mouse(self, event, x, y, _flags, _data) -> None:
        point = self.image_point(x, y)
        if point is None:
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            hits = [i for i, box in enumerate(self.boxes) if contains(box, *point)]
            if hits:
                self.selected = min(hits, key=lambda i: self.boxes[i].width * self.boxes[i].height)
            else:
                self.selected = None
                self.drag_start = self.drag_now = point
        elif event == cv2.EVENT_MOUSEMOVE and self.drag_start is not None:
            self.drag_now = point
        elif event == cv2.EVENT_LBUTTONUP and self.drag_start is not None:
            left, right = sorted((self.drag_start[0], point[0]))
            top, bottom = sorted((self.drag_start[1], point[1]))
            if right - left >= 4 and bottom - top >= 4:
                self.boxes.append(AnnotationBox(
                    box_id=uuid4().hex[:12], left=left, top=top, right=right, bottom=bottom,
                    class_id=self.active_class, confidence=1.0, status="ACCEPTED",
                    source="HUMAN_DRAWN", candidate_kind="human_review"))
                self.selected = len(self.boxes) - 1
            self.drag_start = self.drag_now = None

    def render(self):
        height, width = self.frame.shape[:2]
        fit = min(1400 / width, 820 / height)
        self.scale = max(.25, min(6., fit * self.zoom))
        shown = cv2.resize(self.frame, (round(width * self.scale), round(height * self.scale)),
                           interpolation=cv2.INTER_NEAREST if self.scale > 1 else cv2.INTER_AREA)
        canvas = cv2.copyMakeBorder(shown, HEADER, 0, 0, max(0, 1000 - shown.shape[1]),
                                    cv2.BORDER_CONSTANT, value=(22, 22, 22))
        for index, box in enumerate(self.boxes):
            accepted = box.status == "ACCEPTED"
            color = (255, 255, 255) if index == self.selected else \
                CLASS_COLORS[box.class_id] if accepted else (90, 140, 160)
            p1 = (round(box.left * self.scale), HEADER + round(box.top * self.scale))
            p2 = (round(box.right * self.scale), HEADER + round(box.bottom * self.scale))
            cv2.rectangle(canvas, p1, p2, color, 2 if accepted else 1)
            cv2.putText(canvas, f"{box.class_id + 1}:{MAP_MARKER_YOLO_CLASSES[box.class_id]}"
                        f"{'' if accepted else ' ?'}", (p1[0], max(HEADER + 12, p1[1] - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, .4, color, 1, cv2.LINE_AA)
        if self.drag_start and self.drag_now:
            a, b = self.drag_start, self.drag_now
            cv2.rectangle(canvas, (round(a[0] * self.scale), HEADER + round(a[1] * self.scale)),
                          (round(b[0] * self.scale), HEADER + round(b[1] * self.scale)),
                          CLASS_COLORS[self.active_class], 2)
        done = sum(1 for i in range(len(self.records)) if self.reviewed(i))
        cv2.putText(canvas, f"{self.index + 1}/{len(self.records)} reviewed={done}  zoom={self.zoom:.1f}"
                    f"  {self.message}", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, .55, (245, 245, 245),
                    1, cv2.LINE_AA)
        cv2.putText(canvas, facts_line(self.facts), (10, 42), cv2.FONT_HERSHEY_SIMPLEX, .45,
                    (180, 220, 255), 1, cv2.LINE_AA)
        for class_id, title in enumerate(MAP_MARKER_CLASS_TITLES):
            row, column = divmod(class_id, 5)
            left, top = 10 + column * 196, 52 + row * 30
            cv2.rectangle(canvas, (left, top), (left + 188, top + 24), CLASS_COLORS[class_id],
                          3 if class_id == self.active_class else 1)
            cv2.putText(canvas, f"{class_id + 1} {title}", (left + 5, top + 17),
                        cv2.FONT_HERSHEY_SIMPLEX, .4, CLASS_COLORS[class_id], 1, cv2.LINE_AA)
        cv2.putText(canvas, "drag draw | click select | 1-9,0 class, C next | SPACE accept | A all | D del | "
                    "X del unaccepted | ENTER save+next | E empty+next | N/P | [ ] | +/- zoom | Q",
                    (10, HEADER - 4), cv2.FONT_HERSHEY_SIMPLEX, .4, (190, 190, 190), 1, cv2.LINE_AA)
        return canvas

    def run(self) -> None:
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(WINDOW, self.mouse)
        while True:
            cv2.imshow(WINDOW, self.render())
            key = cv2.waitKey(20) & 0xFF
            if key in (ord("q"), 27):
                break
            if ord("1") <= key <= ord("9") or key in (ord("0"), ord("c")):
                # 1-9, 0 = class 10, C = next class (13 classes since 2026-10-05)
                self.active_class = (9 if key == ord("0") else
                                     (self.active_class + 1) % len(MAP_MARKER_YOLO_CLASSES)
                                     if key == ord("c") else key - ord("1"))
                if self.selected is not None:
                    self.boxes[self.selected].class_id = self.active_class
                    self.boxes[self.selected].status = "ACCEPTED"
            elif key == ord(" ") and self.selected is not None:
                box = self.boxes[self.selected]
                box.status = "PROPOSED" if box.status == "ACCEPTED" else "ACCEPTED"
            elif key in (ord("d"), 8, 127) and self.selected is not None:
                self.boxes.pop(self.selected)
                self.selected = None
            elif key == ord("x"):
                self.boxes = [box for box in self.boxes if box.status == "ACCEPTED"]
                self.selected = None
            elif key == ord("a"):
                for box in self.boxes:
                    box.status = "ACCEPTED"
            elif key in (10, 13):
                self.save()
                self.move(1, unreviewed=True)
            elif key == ord("e"):
                self.save(empty=True)
                self.move(1, unreviewed=True)
            elif key == ord("s"):
                self.save()
            elif key == ord("n"):
                self.move(1)
            elif key == ord("p"):
                self.move(-1)
            elif key == ord("]"):
                self.move(1, unreviewed=True)
            elif key == ord("["):
                self.move(-1, unreviewed=True)
            elif key in (ord("+"), ord("=")):
                self.zoom = min(4., self.zoom * 1.25)
            elif key == ord("-"):
                self.zoom = max(.5, self.zoom / 1.25)
        cv2.destroyAllWindows()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--start-unreviewed", action="store_true")
    args = parser.parse_args()
    reviewer = MapReviewer(args.dataset.resolve())
    if args.start_unreviewed and reviewer.reviewed(reviewer.index):
        reviewer.move(1, unreviewed=True)
    reviewer.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
