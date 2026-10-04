from __future__ import annotations

import argparse
import cv2
import json
from pathlib import Path

from wowbot.navigation.exile_reach_seed import SEED_EDGES, SEED_NODES


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview the calibrated Exile's Reach seed graph on a World Map image.")
    parser.add_argument("image")
    parser.add_argument("--output", default="exile_reach_seed_graph.png")
    parser.add_argument("--json-output", default="exile_reach_seed_graph.json")
    args = parser.parse_args()

    image = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"cannot read image: {args.image}")
    h, w = image.shape[:2]
    # Map ROI calibrated for the supplied screenshot.
    x0, y0, x1, y1 = int(.045*w), int(.108*h), int(.955*w), int(.958*h)
    nodes = {nid: (x0 + int(x*(x1-x0)), y0 + int(y*(y1-y0))) for nid, _, x, y in SEED_NODES}
    for a, b in SEED_EDGES:
        pa = nodes[a]; pb = nodes[b]
        cv2.line(image, pa, pb, (255, 180, 50), 2, cv2.LINE_AA)
    for nid, typ, x, y in SEED_NODES:
        px, py = nodes[nid]
        cv2.circle(image, (px, py), 6, (50, 220, 255), -1)
        cv2.putText(image, nid, (px+7, py-5), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (255,255,255), 1, cv2.LINE_AA)
    cv2.imwrite(args.output, image)
    Path(args.json_output).write_text(json.dumps({"nodes": [dict(id=nid, type=typ, x=x, y=y) for nid,typ,x,y in SEED_NODES], "edges": [dict(a=a,b=b) for a,b in SEED_EDGES]}, indent=2), encoding="utf-8")
    print(f"nodes={len(SEED_NODES)} edges={len(SEED_EDGES)} output={args.output} json={args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
