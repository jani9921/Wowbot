"""Extract every Nth frame from a video into frame_%07d.png files.

Matches the existing datasets/video_frames convention: stride=30 at 60fps
source video (one frame every 0.5s), frame_<absolute_frame_index>.png.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--stride", type=int, default=30)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        print(f"Could not open video: {args.video}")
        return 1

    index = 0
    written = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % args.stride == 0:
            out_path = args.out / f"frame_{index:07d}.png"
            cv2.imwrite(str(out_path), frame)
            written += 1
        index += 1
        if index % 6000 == 0:
            print(f"{index} frames scanned, {written} written")

    cap.release()
    print(f"DONE: scanned {index} frames, wrote {written} to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
