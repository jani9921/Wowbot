"""OpenCV review UI for World3D proposals; only explicit saves create labels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time
from uuid import uuid4

import cv2

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.world3d.annotation_review import AnnotationBox, contains, yolo_line
from wowbot.vision.world3d.video_dataset import WORLD3D_YOLO_CLASSES


WINDOW = "AIPC World3D semi-auto annotator"
# cv2.waitKeyEx codes (Windows, then GTK); waitKey's & 0xFF masked them away.
LEFT_KEYS = frozenset({2424832, 65361})
RIGHT_KEYS = frozenset({2555904, 65363})
DELETE_KEYS = frozenset({3014656, 65535})   # Delete key (Windows, GTK)
HEADER = 142
CLASS_COLORS = (
    (255, 210, 40),   # humanoid - cyan
    (40, 150, 255),   # creature - orange
    (220, 60, 220),   # corpse - magenta
    (40, 240, 240),   # quest outline - yellow
    (255, 120, 40),   # world object - blue
    (20, 210, 255),   # overhead symbol - gold
    (190, 80, 255),   # entrance/door - violet
)
CLASS_TITLES = (
    "Humanoid / NPC-like",
    "Creature / mob-like",
    "Corpse",
    "Quest-object outline",
    "World object",
    "Overhead symbol",
    "Entrance / door",
)


class Reviewer:
    def __init__(self, dataset: Path, *, reviewed_only: bool = False) -> None:
        self.dataset = dataset
        self.reviewed_only = reviewed_only
        self.manifest = dataset / "review" / "manifest.jsonl"
        self.records: list[dict] = []
        self.pool_is_growing = not self.manifest.is_file()
        self.proposal_dir = dataset / "review" / "proposals"
        self.label_dir = dataset / "review" / "labels"
        self.review_dir = dataset / "review" / "reviews"
        self.label_dir.mkdir(parents=True, exist_ok=True)
        self.review_dir.mkdir(parents=True, exist_ok=True)
        self.index = 0
        self.active_class = 0
        self.selected: int | None = None
        self.boxes: list[AnnotationBox] = []
        self.frame = None
        self.scale = 1.0
        self.drag_start: tuple[int, int] | None = None
        self.drag_now: tuple[int, int] | None = None
        self.message = ""
        # Unsaved edits on this frame; paging away asks once before dropping them.
        self.dirty = False
        self.pending_navigation: tuple[str, int] | None = None
        # Frame deletion needs a second press; deleted frames go to
        # review/deleted/<stem>/ and U restores the last one (user 2026-10-02).
        self.pending_delete: str | None = None
        self.deleted_stack: list[Path] = []
        self.class_buttons: list[tuple[int, int, int, int]] = []
        self.action_buttons: list[tuple[str, tuple[int, int, int, int]]] = []
        self.refresh_records()
        if not self.records:
            scope = "reviewed images" if reviewed_only else "extracted images"
            raise RuntimeError(f"No {scope} yet under {dataset / 'review' / 'images'}")
        self.load()

    def refresh_records(self) -> int:
        """Discover frames while the video extractor is still writing the pool."""
        known = {str(record["image"]).replace("\\", "/") for record in self.records}
        if self.manifest.is_file():
            discovered = [json.loads(line) for line in
                          self.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.pool_is_growing = False
        else:
            image_dir = self.dataset / "review" / "images"
            discovered = [{"image": path.relative_to(self.dataset).as_posix()}
                          for path in sorted(image_dir.glob("*"))
                          if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
            self.pool_is_growing = True
        if self.reviewed_only:
            discovered = [
                record for record in discovered
                if (self.review_dir / f"{Path(record['image']).stem}.json").is_file()
            ]
        added = [record for record in discovered
                 if str(record["image"]).replace("\\", "/") not in known]
        self.records.extend(added)
        return len(added)

    @property
    def image_path(self) -> Path:
        return self.dataset / self.records[self.index]["image"]

    def load(self) -> None:
        self.frame = cv2.imread(str(self.image_path), cv2.IMREAD_COLOR)
        if self.frame is None:
            raise RuntimeError(f"Cannot read {self.image_path}")
        proposal_path = self.proposal_dir / f"{self.image_path.stem}.json"
        review_path = self.review_dir / f"{self.image_path.stem}.json"
        source = review_path if review_path.exists() else proposal_path
        payload = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {}
        key = "boxes" if source == review_path else "proposals"
        self.boxes = [AnnotationBox.from_dict(item) for item in payload.get(key, [])]
        self.selected = None
        self.drag_start = self.drag_now = None
        self.dirty = False
        self.pending_navigation = None
        self.pending_delete = None
        if review_path.exists():
            status = str(payload.get("review_status") or "REVIEWED")
            accepted = int(payload.get("accepted_count") or len(self.boxes))
            reviewer = str(payload.get("reviewer") or "HUMAN")
            self.message = f"{status} | boxes={accepted} | by={reviewer}"
        else:
            self.message = "UNREVIEWED"

    def save(self, *, empty: bool = False) -> None:
        accepted = [] if empty else [box for box in self.boxes if box.status == "ACCEPTED"]
        height, width = self.frame.shape[:2]
        label = self.label_dir / f"{self.image_path.stem}.txt"
        label.write_text("".join(yolo_line(box, width, height) + "\n" for box in accepted),
                         encoding="utf-8")
        review = {
            "image": self.records[self.index]["image"],
            "review_status": "REVIEWED_EMPTY" if empty else "REVIEWED",
            "accepted_count": len(accepted),
            "boxes": [box.to_dict() for box in accepted],
            "rejected_proposal_count": len([box for box in self.boxes
                                             if box.status != "ACCEPTED"]),
        }
        (self.review_dir / f"{self.image_path.stem}.json").write_text(
            json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        self.message = f"SAVED: {len(accepted)} boxes"
        self.dirty = False
        self.pending_navigation = None

    def move(self, amount: int) -> None:
        if amount > 0 and self.index >= len(self.records) - 1:
            self.refresh_records()
        self.index = min(len(self.records) - 1, max(0, self.index + amount))
        self.load()

    def move_unreviewed(self, amount: int) -> None:
        if amount > 0:
            self.refresh_records()
        candidate = self.index
        while True:
            candidate += amount
            if not 0 <= candidate < len(self.records):
                self.message = ("Waiting for newly extracted frames" if self.pool_is_growing
                                else "No more unreviewed frames")
                return
            stem = Path(self.records[candidate]["image"]).stem
            if not (self.review_dir / f"{stem}.json").exists():
                self.index = candidate
                self.load()
                return

    def navigate(self, kind: str, amount: int) -> None:
        """Page like N/P ([/]) but never drop unsaved edits silently.

        With unsaved edits the first press only warns; pressing the same key
        again discards them and moves (user 2026-10-02: arrow-key paging)."""
        if self.dirty and self.pending_navigation != (kind, amount):
            self.pending_navigation = (kind, amount)
            self.message = "UNSAVED CHANGES: ENTER/S saves, press the same key again to discard"
            return
        self.pending_navigation = None
        (self.move if kind == "move" else self.move_unreviewed)(amount)

    def request_delete_frame(self) -> None:
        stem = self.image_path.stem
        if self.pending_delete != stem:
            self.pending_delete = stem
            self.message = "DELETE IMAGE + LABELS? press DEL again (U undoes)"
            return
        self.pending_delete = None
        self.delete_frame()

    def _manifest_lines(self) -> list[str]:
        if not self.manifest.is_file():
            return []
        return [line for line in self.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]

    def delete_frame(self) -> None:
        """Move the frame's image, label, review and proposals out of the pool.

        Nothing is destroyed: the files go to review/deleted/<stem>/ with a
        record.json, the manifest loses only this line (other records, even
        ones hidden by --reviewed-only, stay), and U restores it."""
        if len(self.records) <= 1:
            self.message = "The last frame of the pool cannot be deleted"
            return
        record = self.records[self.index]
        image = self.image_path
        stem = image.stem
        key = str(record["image"]).replace("\\", "/")
        lines = self._manifest_lines()
        manifest_line = next((number for number, line in enumerate(lines)
                              if str(json.loads(line).get("image", "")).replace("\\", "/") == key), None)
        trash = self.dataset / "review" / "deleted" / stem
        trash.mkdir(parents=True, exist_ok=True)
        moved = []
        for source in (image, self.label_dir / f"{stem}.txt", self.review_dir / f"{stem}.json",
                       self.proposal_dir / f"{stem}.json"):
            if source.exists():
                target = trash / f"{source.parent.name}__{source.name}"
                shutil.move(str(source), str(target))
                moved.append([str(source), str(target)])
        if manifest_line is not None:
            del lines[manifest_line]
            self.manifest.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        (trash / "record.json").write_text(json.dumps({
            "record": record, "index": self.index, "manifest_line": manifest_line,
            "moved": moved, "deleted_at": time.time()}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.deleted_stack.append(trash)
        self.records.pop(self.index)
        self.index = min(self.index, len(self.records) - 1)
        self.load()
        self.message = f"DELETED {stem} -> review/deleted (U = undo)"

    def undo_delete(self) -> None:
        if not self.deleted_stack:
            self.message = "Nothing to undo"
            return
        trash = self.deleted_stack.pop()
        info = json.loads((trash / "record.json").read_text(encoding="utf-8"))
        for source, target in info["moved"]:
            Path(source).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(target, source)
        if info["manifest_line"] is not None:
            lines = self._manifest_lines()
            lines.insert(min(info["manifest_line"], len(lines)), json.dumps(info["record"], ensure_ascii=False))
            self.manifest.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        (trash / "record.json").unlink()
        try:
            trash.rmdir()
        except OSError:
            pass
        self.index = min(info["index"], len(self.records))
        self.records.insert(self.index, info["record"])
        self.load()
        self.message = f"RESTORED {Path(info['record']['image']).stem}"

    def delete_unaccepted(self) -> None:
        removed = len([box for box in self.boxes if box.status != "ACCEPTED"])
        self.boxes = [box for box in self.boxes if box.status == "ACCEPTED"]
        self.selected = None
        self.dirty = self.dirty or removed > 0
        self.message = f"Deleted {removed} unaccepted (not saved yet; N then P reloads)"

    def delete_all(self) -> None:
        removed = len(self.boxes)
        self.boxes = []
        self.selected = None
        self.dirty = self.dirty or removed > 0
        self.message = f"Deleted all {removed} boxes (not saved yet; N then P reloads)"

    def image_point(self, x: int, y: int) -> tuple[int, int] | None:
        if y < HEADER:
            return None
        px, py = round(x / self.scale), round((y - HEADER) / self.scale)
        height, width = self.frame.shape[:2]
        return min(width - 1, max(0, px)), min(height - 1, max(0, py))

    def mouse(self, event: int, x: int, y: int, _flags: int, _data) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and y < HEADER:
            for class_id, (left, top, right, bottom) in enumerate(self.class_buttons):
                if left <= x <= right and top <= y <= bottom:
                    self.active_class = class_id
                    if self.selected is not None:
                        self.boxes[self.selected].class_id = class_id
                        self.boxes[self.selected].status = "ACCEPTED"
                        self.dirty = True
                    self.message = f"Active: {CLASS_TITLES[class_id]}"
                    return
            for action, (left, top, right, bottom) in self.action_buttons:
                if left <= x <= right and top <= y <= bottom:
                    if action == "unaccepted":
                        self.delete_unaccepted()
                    elif action == "frame":
                        self.request_delete_frame()
                    else:
                        self.delete_all()
                    return
        point = self.image_point(x, y)
        if point is None:
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            hit = [index for index, box in enumerate(self.boxes) if contains(box, *point)]
            if hit:
                self.selected = min(hit, key=lambda index: self.boxes[index].width * self.boxes[index].height)
                self.drag_start = self.drag_now = None
            else:
                self.selected = None
                self.drag_start = self.drag_now = point
        elif event == cv2.EVENT_MOUSEMOVE and self.drag_start is not None:
            self.drag_now = point
        elif event == cv2.EVENT_LBUTTONUP and self.drag_start is not None:
            left, right = sorted((self.drag_start[0], point[0]))
            top, bottom = sorted((self.drag_start[1], point[1]))
            if right - left >= 8 and bottom - top >= 8:
                self.boxes.append(AnnotationBox(
                    box_id=uuid4().hex[:12], left=left, top=top, right=right, bottom=bottom,
                    class_id=self.active_class, confidence=1.0, status="ACCEPTED",
                    source="HUMAN_DRAWN", candidate_kind="human_review",
                ))
                self.selected = len(self.boxes) - 1
                self.dirty = True
            self.drag_start = self.drag_now = None

    def render(self):
        height, width = self.frame.shape[:2]
        self.scale = min(1.0, 1400 / width, 780 / height)
        shown = cv2.resize(self.frame, (round(width * self.scale), round(height * self.scale)))
        canvas = cv2.copyMakeBorder(shown, HEADER, 0, 0, 0, cv2.BORDER_CONSTANT,
                                    value=(22, 22, 22))
        for index, box in enumerate(self.boxes):
            selected = index == self.selected
            accepted = box.status == "ACCEPTED"
            color = CLASS_COLORS[box.class_id] if accepted else (80, 150, 170)
            if selected:
                color = (255, 255, 255)
            x1, y1 = round(box.left * self.scale), HEADER + round(box.top * self.scale)
            x2, y2 = round(box.right * self.scale), HEADER + round(box.bottom * self.scale)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 3 if selected else 2)
            label = f"{box.class_id}:{WORLD3D_YOLO_CLASSES[box.class_id]} {box.confidence:.2f}"
            cv2.putText(canvas, label, (x1, max(HEADER + 14, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, .45, color, 1, cv2.LINE_AA)
        if self.drag_start and self.drag_now:
            a, b = self.drag_start, self.drag_now
            cv2.rectangle(canvas,
                          (round(a[0]*self.scale), HEADER+round(a[1]*self.scale)),
                          (round(b[0]*self.scale), HEADER+round(b[1]*self.scale)),
                          CLASS_COLORS[self.active_class], 3)
        growth = "  [EXTRACTING: live folder]" if self.pool_is_growing else ""
        mode = "  [REVIEW ALL SAVED]" if self.reviewed_only else ""
        title = (f"{self.index+1}/{len(self.records)}{growth}{mode}  class {self.active_class}:"
                 f"{CLASS_TITLES[self.active_class]}  {self.message}")
        cv2.putText(canvas, title, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, .58,
                    (245, 245, 245), 1, cv2.LINE_AA)
        self.class_buttons = []
        for class_id, class_title in enumerate(CLASS_TITLES):
            row, column = divmod(class_id, 4)
            left, top = 10 + column * 245, 34 + row * 31
            right, bottom = left + 235, top + 25
            self.class_buttons.append((left, top, right, bottom))
            color = CLASS_COLORS[class_id]
            thickness = 3 if class_id == self.active_class else 1
            cv2.rectangle(canvas, (left, top), (right, bottom), color, thickness)
            cv2.putText(canvas, f"{class_id}  {class_title}", (left + 7, top + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, .43, color, 1, cv2.LINE_AA)
        self.action_buttons = []
        for column, (action, text, color) in enumerate((
                ("unaccepted", "X  Delete unaccepted", (60, 170, 255)),
                ("all", "Z  Delete ALL boxes", (60, 60, 255)),
                ("frame", "DEL  Delete IMAGE+labels", (40, 40, 230)))):
            left, top = 10 + column * 245, 96
            right, bottom = left + 235, top + 22
            self.action_buttons.append((action, (left, top, right, bottom)))
            cv2.rectangle(canvas, (left, top), (right, bottom), color, 1)
            cv2.putText(canvas, text, (left + 7, top + 16), cv2.FONT_HERSHEY_SIMPLEX, .43,
                        color, 1, cv2.LINE_AA)
        help_text = ("drag: draw | click: select | SPACE: accept/toggle | 0-6: class | "
                     "A: accept all | D: delete | X/Z: bulk delete | ENTER: save+next | E: empty | "
                     "<-/-> or P/N: prev/next | [/]: unreviewed | DEL x2: delete image | U: undo | Q")
        cv2.putText(canvas, help_text, (10, 130), cv2.FONT_HERSHEY_SIMPLEX, .40,
                    (190, 190, 190), 1, cv2.LINE_AA)
        return canvas

    def handle_key(self, raw: int) -> bool:
        """Apply one cv2.waitKeyEx code; False quits."""
        if raw in DELETE_KEYS:
            self.request_delete_frame()
            return True
        if raw != -1:
            self.pending_delete = None   # any other key cancels a pending delete
        if raw in LEFT_KEYS:
            self.navigate("move", -1)
            return True
        if raw in RIGHT_KEYS:
            self.navigate("move", 1)
            return True
        key = raw & 0xFF
        if key in (ord("q"), 27):
            return False
        if ord("0") <= key <= ord("6"):
            self.active_class = key - ord("0")
            if self.selected is not None:
                self.boxes[self.selected].class_id = self.active_class
                self.boxes[self.selected].status = "ACCEPTED"
                self.dirty = True
        elif key == ord(" ") and self.selected is not None:
            box = self.boxes[self.selected]
            box.status = "PROPOSED" if box.status == "ACCEPTED" else "ACCEPTED"
            self.dirty = True
        elif key in (ord("d"), 8, 127) and self.selected is not None:
            self.boxes.pop(self.selected)
            self.selected = None
            self.dirty = True
        elif key == ord("x"):
            self.delete_unaccepted()
        elif key == ord("z"):
            self.delete_all()
        elif key == ord("a"):
            self.dirty = self.dirty or any(box.status != "ACCEPTED" for box in self.boxes)
            for box in self.boxes:
                box.status = "ACCEPTED"
        elif key == ord("u"):
            self.undo_delete()
        elif key == ord("s"):
            self.save()
        elif key in (10, 13):
            self.save()
            if self.reviewed_only:
                self.move(1)
            else:
                self.move_unreviewed(1)
        elif key == ord("r"):
            self.save(empty=True)
        elif key == ord("e"):
            self.save(empty=True)
            self.move_unreviewed(1)
        elif key == ord("n"):
            self.navigate("move", 1)
        elif key == ord("p"):
            self.navigate("move", -1)
        elif key == ord("]"):
            self.navigate("unreviewed", 1)
        elif key == ord("["):
            self.navigate("unreviewed", -1)
        return True

    def run(self) -> None:
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(WINDOW, self.mouse)
        while True:
            cv2.imshow(WINDOW, self.render())
            if not self.handle_key(cv2.waitKeyEx(20)):
                break
        cv2.destroyAllWindows()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--start-unreviewed", action="store_true")
    parser.add_argument(
        "--reviewed-only", action="store_true",
        help="Load only explicitly reviewed frames; Enter saves and advances sequentially",
    )
    args = parser.parse_args()
    if args.start_unreviewed and args.reviewed_only:
        parser.error("--start-unreviewed and --reviewed-only cannot be combined")
    reviewer = Reviewer(args.dataset.resolve(), reviewed_only=args.reviewed_only)
    if args.start_unreviewed and (reviewer.review_dir / f"{reviewer.image_path.stem}.json").exists():
        reviewer.move_unreviewed(1)
    reviewer.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
