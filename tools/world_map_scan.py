from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from wowbot.vision.world_map_raster import WorldMapRasterFeatureExtractor, WorldMapRasterConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a WoW World Map screenshot into feature candidates.")
    parser.add_argument("image")
    parser.add_argument("--output", default="world_map_features.json")
    parser.add_argument("--annotated-output", default=None)
    parser.add_argument("--roi", nargs=4, type=float, metavar=("LEFT","TOP","RIGHT","BOTTOM"), default=None)
    args = parser.parse_args()
    image = Image.open(args.image).convert("RGB")
    arr = np.asarray(image)
    cfg = WorldMapRasterConfig()
    if args.roi:
        cfg = WorldMapRasterConfig(roi_left=args.roi[0], roi_top=args.roi[1], roi_right=args.roi[2], roi_bottom=args.roi[3])
    features = WorldMapRasterFeatureExtractor(cfg).extract(arr)
    payload = [{"feature_type": f.feature_type.value, "x": f.center.x, "y": f.center.y, "confidence": f.confidence, "width": f.width, "height": f.height, "metadata": f.metadata} for f in features]
    Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.annotated_output:
        out = image.copy(); draw = ImageDraw.Draw(out)
        for f in features:
            x, y = f.center.x, f.center.y
            r = max(3, min(12, int(round(max(f.width, f.height) * 0.08))))
            if f.feature_type.value == "INTERSECTION":
                draw.ellipse((x-r,y-r,x+r,y+r), outline=(255,60,60), width=2)
            else:
                draw.ellipse((x-r,y-r,x+r,y+r), outline=(60,220,255), width=2)
            draw.text((x+4,y+2), f.feature_type.value, fill=(255,255,255))
        out.save(args.annotated_output)
    print(f"features={len(payload)} output={args.output}")
    if args.annotated_output:
        print(f"annotated={args.annotated_output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
