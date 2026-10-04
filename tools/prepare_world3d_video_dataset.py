"""Create an unlabelled World3D annotation pool from gameplay videos."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.world3d.video_dataset import prepare_review_pool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", action="append", required=True, type=Path,
                        help="Gameplay video; repeat for each independent source")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--interval-seconds", type=float, default=3.0)
    parser.add_argument("--minimum-difference", type=float, default=2.5)
    parser.add_argument("--jpeg-quality", type=int, default=92)
    parser.add_argument("--limit-per-video", type=int, default=0,
                        help="0 means unlimited; useful for a small pilot pool")
    parser.add_argument("--exclude-manifest", action="append", type=Path, default=[],
                        help="Skip source frames already present in this manifest; repeatable")
    args = parser.parse_args()

    summary = prepare_review_pool(
        args.video,
        args.out,
        interval_seconds=args.interval_seconds,
        minimum_difference=args.minimum_difference,
        jpeg_quality=args.jpeg_quality,
        limit_per_video=max(0, args.limit_per_video),
        exclude_manifests=args.exclude_manifest,
    )
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
