"""Gather collected World Map / minimap crops into a review pool.

Default sources: every ``output/agent/pid-*/map-marker-dataset`` (live
collector) and ``map-marker-dataset-bootstrap`` (measure tool) folder.
Re-running only adds new samples; review decisions are kept.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.map_marker_dataset import build_review_pool  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", choices=("WORLD_MAP", "MINIMAP"), default="WORLD_MAP")
    parser.add_argument("--dataset", type=Path,
                        help="default: datasets/map_markers_<surface>")
    parser.add_argument("sources", nargs="*", type=Path)
    args = parser.parse_args()
    dataset = args.dataset or ROOT / "datasets" / f"map_markers_{args.surface.lower()}"
    sources = args.sources or sorted(
        [*ROOT.glob("output/agent/pid-*/map-marker-dataset"),
         *ROOT.glob("output/agent/pid-*/map-marker-dataset-bootstrap")])
    result = build_review_pool(sources, dataset, surface=args.surface)
    print(json.dumps({"dataset": str(dataset), "sources": [str(s) for s in sources], **result},
                     indent=1))
    print(f"Next: python tools/review_map_marker_annotations.py \"{dataset}\" --start-unreviewed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
