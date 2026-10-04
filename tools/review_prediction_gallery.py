"""Keyboard-driven OpenCV viewer for rendered model-prediction galleries."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
WINDOW_TITLE = "World3D model prediction review"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gallery", type=Path)
    parser.add_argument("--start", type=int, default=1, help="One-based starting image")
    args = parser.parse_args()

    gallery = args.gallery.resolve()
    if not gallery.is_dir():
        raise SystemExit(f"Prediction gallery does not exist: {gallery}")
    images = sorted(
        path for path in gallery.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not images:
        raise SystemExit(f"No rendered prediction images found in: {gallery}")

    index = min(max(args.start - 1, 0), len(images) - 1)
    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_TITLE, 1400, 850)

    while True:
        image_path = images[index]
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            index = min(index + 1, len(images) - 1)
            continue

        banner = frame.copy()
        label = (
            f"{index + 1}/{len(images)}  {image_path.name}  |  "
            "ENTER/RIGHT: next  LEFT: previous  HOME/END  Q/ESC: close"
        )
        cv2.rectangle(banner, (0, 0), (frame.shape[1], 34), (20, 20, 20), -1)
        cv2.putText(
            banner, label, (10, 23), cv2.FONT_HERSHEY_SIMPLEX,
            0.58, (255, 255, 255), 1, cv2.LINE_AA,
        )
        cv2.imshow(WINDOW_TITLE, banner)
        key = cv2.waitKeyEx(0)
        if key in (27, ord("q"), ord("Q")):
            break
        if key in (13, 10, 32, 83, 2555904):  # Enter, Space, Right
            index = min(index + 1, len(images) - 1)
        elif key in (81, 2424832):  # Left
            index = max(index - 1, 0)
        elif key in (71, 2359296):  # Home
            index = 0
        elif key in (79, 2293760):  # End
            index = len(images) - 1

    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
