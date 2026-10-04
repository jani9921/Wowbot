from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Import Pillow before adding the project src/ directory to sys.path.
# The project intentionally contains src/logging/, which otherwise shadows
# Python's standard-library logging package during Pillow import.
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.adapters.minimap import detect_minimap  # noqa: E402


def read_image(path: Path) -> tuple[bytes, int, int]:
    image = Image.open(path).convert("RGBA")
    width, height = image.size
    return image.tobytes(), width, height


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Minimap perception from a screenshot without issuing input.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    raw, width, height = read_image(args.image)
    obs = detect_minimap(raw, width, height, observed_at=time.time())
    payload = {
        "width": obs.width,
        "height": obs.height,
        "player_marker": {"x": obs.player_marker.x, "y": obs.player_marker.y},
        "center_radius_px": obs.center_radius_px,
        "observed_at": obs.observed_at,
        "markers": [],
    }
    for marker in obs.markers:
        dx, dy = obs.marker_relative(marker)
        nx, ny = obs.marker_normalized(marker)
        payload["markers"].append({
            "type": marker.marker_type,
            "x": marker.position.x,
            "y": marker.position.y,
            "confidence": marker.confidence,
            "marker_color": marker.marker_color,
            "relation": marker.relation,
            "symbol": marker.symbol,
            "relative_x_px": dx,
            "relative_y_px": dy,
            "normalized_x": nx,
            "normalized_y": ny,
            "distance_px": obs.marker_distance_px(marker),
        })

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
