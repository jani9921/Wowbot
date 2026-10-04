from __future__ import annotations

# Keep the stdlib logging module available before Pillow or any project-local
# package named logging can be imported.
import logging as _stdlib_logging
import sys as _bootstrap_sys
if not hasattr(_stdlib_logging, "getLogger"):
    raise RuntimeError("standard logging module unavailable")

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SRC = ROOT / "src"
for entry in (ROOT, SRC):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from src.adapters.pixel_bridge import capture_hwnd_bgra  # noqa: E402
from tools.wow_window import find_best_wow_window  # noqa: E402
from .scene import build_scene_roi  # noqa: E402
from .models import WorldFrameObservation  # noqa: E402
from .candidates import detect_world_candidates  # noqa: E402
from .tracking import WorldCandidateTracker  # noqa: E402
from .normalization import world_frame_to_observation  # noqa: E402
from .validation import validate_fusion_observation  # noqa: E402
from wowbot.vision.fusion.pipeline import PerceptionFusion  # noqa: E402
from wowbot.vision.fusion.local import LocalWorldProjector  # noqa: E402


def save_png(raw: bytes, width: int, height: int, path: Path) -> None:
    from PIL import Image

    rgb = bytearray(width * height * 3)
    for i in range(width * height):
        off4 = i * 4
        off3 = i * 3
        rgb[off3:off3 + 3] = bytes((raw[off4 + 2], raw[off4 + 1], raw[off4]))
    Image.frombytes("RGB", (width, height), bytes(rgb)).save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Passive M7.5.7 3D World Vision validation probe")
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--snapshot", type=Path, default=None)
    args = parser.parse_args()

    window = find_best_wow_window(preferred_pid=args.pid)
    if window is None:
        raise RuntimeError("no visible World of Warcraft window found")
    print(f"[wow] using PID {window.pid} hwnd={window.hwnd} title={window.title!r}")

    tracker = WorldCandidateTracker()
    fusioner = PerceptionFusion()
    projector = LocalWorldProjector()
    samples: list[dict[str, object]] = []
    last_raw: bytes | None = None
    last_width = last_height = 0
    print("=" * 72)
    print("WoW Navigation — M7.5.7 3D Vision / NavigationObservation Probe")
    print("=" * 72)
    print("Passive only: no keyboard/mouse input is sent.")
    print("Validates class-color metadata, temporal tracks, WorldObservation and NavigationObservation.")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            raw, width, height = capture_hwnd_bgra(window.hwnd)
            roi = build_scene_roi(width, height)
            candidates = detect_world_candidates(raw, width, height, roi)
            tracked = tracker.update(candidates)
            frame = WorldFrameObservation(
                width=width,
                height=height,
                scene=roi,
                frame_id=f"probe:{len(samples) + 1}",
                client_id=f"pid:{window.pid}",
                candidates=tracked,
                observed_at=time.time(),
                source="screen_capture",
            )
            world = world_frame_to_observation(frame)
            fusion = fusioner.build_from_world3d(frame)
            # Use the normalized frame result for deterministic validation.
            validation = validate_fusion_observation(fusion, len(tracked))
            local_world = projector.project(fusion)
            world_entities = list(world.visible_entities)
            payload = {
                "width": width,
                "height": height,
                "scene_roi": {
                    "left": roi.rect.left,
                    "top": roi.rect.top,
                    "right": roi.rect.right,
                    "bottom": roi.rect.bottom,
                    "profile": roi.profile,
                },
                "candidate_count": len(tracked),
                "candidate_kinds": {kind: sum(c.kind == kind for c in tracked) for kind in sorted({c.kind for c in tracked})},
                "candidates": [
                    {
                        "kind": c.kind,
                        "rect": {"left": c.rect.left, "top": c.rect.top, "right": c.rect.right, "bottom": c.rect.bottom},
                        "confidence": c.confidence,
                        "evidence": c.evidence,
                        "relation": c.relation,
                        "class_name": c.class_name,
                        "class_color": c.class_color,
                        "track_id": c.track_id,
                        "previous_relation": c.previous_relation,
                        "relation_changed": c.relation_changed,
                    }
                    for c in tracked
                ],
                "world_observation": {
                    "visible_entities": world_entities,
                    "obstacles": [],
                    "observed_at": world.observed_at,
                },
                "navigation_observation": {
                    "has_world": fusion.world is not None,
                    "observed_at": fusion.observed_at,
                },
                "validation": validation.to_dict(),
                "local_world_model": local_world.to_dict(),
                "observed_at": frame.observed_at,
                "source": frame.source,
                "notes": list(frame.notes),
            }
            print(json.dumps(payload, ensure_ascii=False))
            samples.append(payload)
            last_raw, last_width, last_height = raw, width, height
            time.sleep(max(args.interval, 0.05))
    except KeyboardInterrupt:
        return 0
    finally:
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({"samples": samples}, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.snapshot is not None and last_raw is not None:
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            save_png(last_raw, last_width, last_height, args.snapshot)


if __name__ == "__main__":
    raise SystemExit(main())
