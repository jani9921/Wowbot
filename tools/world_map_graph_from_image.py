from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from wowbot.vision.world_map_graph_vision import WorldMapGraphVision, WorldMapGraphVisionConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Build conservative Exile's Reach World Map graph candidates from a screenshot.")
    parser.add_argument("image")
    parser.add_argument("--output", default="world_map_graph_features.json")
    parser.add_argument("--annotated-output", default="world_map_graph_annotated.png")
    args = parser.parse_args()

    bgr = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit(f"cannot read image: {args.image}")
    arr = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    features = WorldMapGraphVision(WorldMapGraphVisionConfig()).extract(arr)
    payload = [
        {
            "feature_type": f.feature_type.value,
            "x": f.center.x,
            "y": f.center.y,
            "confidence": f.confidence,
            "width": f.width,
            "height": f.height,
            "metadata": f.metadata,
        }
        for f in features
    ]
    Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = bgr.copy()
    for f in features:
        x, y = f.center.x, f.center.y
        if f.feature_type.value == "INTERSECTION":
            r = 7
            cv2.circle(out, (int(round(x)), int(round(y))), r, (70, 70, 255), 2)
            cv2.putText(out, f"J:{f.confidence:.2f}", (int(x+8), int(y-7)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255,255,255), 1, cv2.LINE_AA)
        else:
            cv2.circle(out, (int(round(x)), int(round(y))), 3, (255,220,50), -1)
    cv2.imwrite(args.annotated_output, out)
    print(f"features={len(payload)} output={args.output} annotated={args.annotated_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
