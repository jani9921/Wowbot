"""Read-only viewer for an exported YOLO dataset (images/<split>, labels/<split>, data.yaml).

Keys: N / D / Right = next, P / A / Left = previous, F = next frame with boxes,
1-3 = train/val/test, Q / Esc = quit.  Nothing is ever written.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

import cv2

COLORS = ((40, 150, 255), (40, 240, 240), (20, 210, 255), (255, 210, 40), (220, 60, 220),
          (255, 120, 40), (190, 80, 255))
WINDOW = "YOLO dataset viewer (read-only)"
SPLITS = ("train", "val", "test")


def class_names(dataset: Path) -> dict[int, str]:
    names: dict[int, str] = {}
    yaml = dataset / "data.yaml"
    if yaml.is_file():
        for line in yaml.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"\s+(\d+):\s*(\S+)\s*", line)
            if match:
                names[int(match[1])] = match[2]
    return names


def read_boxes(label: Path) -> list[tuple[int, float, float, float, float]]:
    if not label.is_file():
        return []
    boxes = []
    for line in label.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 5:
            boxes.append((int(float(parts[0])), *map(float, parts[1:5])))
    return boxes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--split", choices=SPLITS, default="train")
    args = parser.parse_args()
    names = class_names(args.dataset)
    split = args.split
    images = sorted((args.dataset / "images" / split).glob("*"))
    index = 0
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    while images:
        image = images[index]
        frame = cv2.imread(str(image))
        boxes = read_boxes(args.dataset / "labels" / split / f"{image.stem}.txt")
        height, width = frame.shape[:2]
        scale = min(1.0, 1500 / width, 820 / height)
        frame = cv2.resize(frame, (round(width * scale), round(height * scale)))
        h, w = frame.shape[:2]
        counts: dict[str, int] = {}
        for class_id, cx, cy, bw, bh in boxes:
            color = COLORS[class_id % len(COLORS)]
            name = names.get(class_id, str(class_id))
            counts[name] = counts.get(name, 0) + 1
            x1, y1 = round((cx - bw / 2) * w), round((cy - bh / 2) * h)
            x2, y2 = round((cx + bw / 2) * w), round((cy + bh / 2) * h)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"{class_id}:{name}", (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX,
                        .45, color, 1, cv2.LINE_AA)
        summary = ", ".join(f"{name}={count}" for name, count in counts.items()) or "no boxes"
        header = f"[{split}] {index + 1}/{len(images)}  {summary}   N/P next/prev  F next with boxes  1-3 split  Q quit"
        canvas = cv2.copyMakeBorder(frame, 30, 0, 0, 0, cv2.BORDER_CONSTANT, value=(22, 22, 22))
        cv2.putText(canvas, header, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, .5, (240, 240, 240), 1, cv2.LINE_AA)
        cv2.imshow(WINDOW, canvas)
        key = cv2.waitKeyEx(0)
        char = chr(key & 0xFF).lower() if key & 0xFF < 128 else ""
        if char == "q" or key == 27:
            break
        if char in ("n", "d") or key in (2555904, 65363):
            index = (index + 1) % len(images)
        elif char in ("p", "a") or key in (2424832, 65361):
            index = (index - 1) % len(images)
        elif char == "f":
            for step in range(1, len(images)):
                candidate = (index + step) % len(images)
                if read_boxes(args.dataset / "labels" / split / f"{images[candidate].stem}.txt"):
                    index = candidate
                    break
        elif char in ("1", "2", "3"):
            split = SPLITS[int(char) - 1]
            images = sorted((args.dataset / "images" / split).glob("*"))
            index = 0
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
