"""Export reviewed video annotations to leakage-aware YOLO train/val/test folders."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.world3d.dataset_export import export_reviewed_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--cluster-gap-seconds", type=float, default=30.0)
    parser.add_argument("--max-cluster-duration-seconds", type=float, default=120.0,
                        help="Keep continuous video blocks bounded without frame-level leakage")
    args = parser.parse_args()
    summary = export_reviewed_dataset(
        args.dataset, args.out, cluster_gap_seconds=args.cluster_gap_seconds,
        max_cluster_duration_seconds=args.max_cluster_duration_seconds)
    print(f"reviewed_frames={summary.reviewed_frames} boxes={summary.boxes} "
          f"clusters={summary.clusters} splits={summary.split_frames}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
