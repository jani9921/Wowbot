from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from wowbot.vision.world_map_calibration import EXILE_REACH_12_1_5


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate a WoW World Map screenshot into normalized map-space.")
    parser.add_argument("image")
    parser.add_argument("--player-x", type=float, default=None, help="Known map-space player X (0..1)")
    parser.add_argument("--player-y", type=float, default=None, help="Known map-space player Y (0..1)")
    parser.add_argument("--output", default="world_map_calibrated.png")
    args = parser.parse_args()

    image = cv2.imread(args.image)
    if image is None:
        raise SystemExit(f"cannot read image: {args.image}")

    c = EXILE_REACH_12_1_5
    out = image.copy()
    cv2.rectangle(out, (c.left_px, c.top_px), (c.right_px, c.bottom_px), (0, 200, 255), 2)

    for i in range(1, 10):
        x = round(c.left_px + i * c.width_px / 10)
        y = round(c.top_px + i * c.height_px / 10)
        cv2.line(out, (x, c.top_px), (x, c.bottom_px), (120, 120, 120), 1)
        cv2.line(out, (c.left_px, y), (c.right_px, y), (120, 120, 120), 1)

    if args.player_x is not None and args.player_y is not None:
        px, py = c.map_to_pixel(args.player_x, args.player_y)
        cv2.circle(out, (round(px), round(py)), 8, (0, 255, 0), 2)
        label = f"PLAYER map=({args.player_x:.4f},{args.player_y:.4f})"
        cv2.putText(out, label, (round(px) + 10, round(py) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)

    cv2.imwrite(args.output, out)
    print(f"map_roi={c.left_px},{c.top_px},{c.right_px},{c.bottom_px}")
    if args.player_x is not None and args.player_y is not None:
        px, py = c.map_to_pixel(args.player_x, args.player_y)
        print(f"player_pixel={px:.2f},{py:.2f}")
    print(f"output={Path(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
