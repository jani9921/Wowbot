"""Render a World3D replay JSON debug overlay onto its referenced frame."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from wowbot.vision.world3d.debug_renderer import World3DDebugRenderer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("frame", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    replay = json.loads(args.replay.read_text(encoding="utf-8"))
    if replay.get("kind") != "WORLD3D_REPLAY" or not isinstance(replay.get("debug_overlay"), dict):
        raise SystemExit("invalid World3D replay record")
    image = Image.open(args.frame).convert("RGBA")
    # Convert RGBA to the BGRA byte contract used by live capture.
    red, green, blue, alpha = image.split()
    bgra = Image.merge("RGBA", (blue, green, red, alpha)).tobytes()
    World3DDebugRenderer().render((bgra, image.width, image.height),
                                  replay["debug_overlay"], args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

