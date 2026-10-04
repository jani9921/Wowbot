"""Render what the production World3D learned detector admits on live frames."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import cv2

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.world3d.learned_detector import (
    build_runtime_learned_detector,
    default_runtime_model_path,
)
from wowbot.vision.world3d.scene import build_scene_roi


COLORS = {
    "humanoid_unit_like": (60, 220, 60),
    "creature_unit_like": (0, 170, 255),
    "corpse_like": (180, 80, 220),
    "quest_object_outline_like": (255, 160, 30),
    "overhead_symbol_like": (0, 255, 255),
    "world_object_like": (255, 120, 0),
    "entrance_or_door_like": (255, 255, 255),
}


def _sample(paths: list[Path], count: int) -> list[Path]:
    if len(paths) <= count:
        return paths
    return [paths[round(index * (len(paths) - 1) / (count - 1))]
            for index in range(count)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()

    images = sorted(path for path in args.capture_directory.iterdir()
                    if path.suffix.lower() in {".jpg", ".jpeg", ".png"})
    selected = _sample(images, max(1, args.count))
    if not selected:
        raise SystemExit(f"No capture images found in {args.capture_directory}")
    args.output.mkdir(parents=True, exist_ok=True)
    detector = build_runtime_learned_detector(default_runtime_model_path())
    if detector is None:
        raise SystemExit("Runtime learned detector is not configured")
    # The production backend warms TensorRT in its child process. Live runtime
    # naturally receives frames during that period; an offline ten-frame audit
    # must wait or it would misleadingly render ten empty "warming" results.
    deadline = time.monotonic() + 30.
    while getattr(detector.backend, "status", "ready") == "warming":
        poll = getattr(detector.backend, "_poll_status", None)
        if callable(poll):
            poll()
        if getattr(detector.backend, "status", "ready") != "warming":
            break
        if time.monotonic() >= deadline:
            raise SystemExit("Runtime detector did not finish warm-up in 30 seconds")
        time.sleep(.05)
    manifest = []
    try:
        for index, source in enumerate(selected, 1):
            image = cv2.imread(str(source), cv2.IMREAD_COLOR)
            if image is None:
                continue
            height, width = image.shape[:2]
            bgra = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
            candidates = detector.detect(
                bgra.tobytes(), width, height, build_scene_roi(width, height))
            diagnostics = dict(detector.last_diagnostics)
            labels = []
            for candidate in candidates:
                label = str(candidate.appearance.get("learned_label_hypothesis") or
                            candidate.kind)
                confidence = float(candidate.appearance.get(
                    "learned_confidence", candidate.confidence))
                color = COLORS.get(label, (220, 220, 220))
                rect = candidate.rect
                cv2.rectangle(image, (rect.left, rect.top),
                              (rect.right, rect.bottom), color, 2)
                text = f"{label} {confidence:.3f}"
                text_width = cv2.getTextSize(
                    text, cv2.FONT_HERSHEY_SIMPLEX, .48, 1)[0][0]
                cv2.rectangle(image, (rect.left, max(0, rect.top - 20)),
                              (min(width - 1, rect.left + text_width + 8), rect.top),
                              (20, 20, 20), -1)
                cv2.putText(image, text, (rect.left + 3, max(13, rect.top - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, .48, color, 1, cv2.LINE_AA)
                labels.append({"label": label, "confidence": confidence,
                               "bbox": [rect.left, rect.top, rect.right, rect.bottom]})
            banner = (f"RUNTIME DETECTOR | {diagnostics.get('sampling_mode')} | "
                      f"admitted={len(candidates)} raw={diagnostics.get('raw_detections')} "
                      f"rejected={diagnostics.get('rejected')}")
            cv2.rectangle(image, (0, 0), (width, 28), (15, 15, 15), -1)
            cv2.putText(image, banner, (8, 19), cv2.FONT_HERSHEY_SIMPLEX,
                        .52, (255, 255, 255), 1, cv2.LINE_AA)
            output = args.output / f"{index:02d}-{source.stem}-runtime.png"
            cv2.imwrite(str(output), image)
            manifest.append({"source": str(source), "output": str(output),
                             "detections": labels, "diagnostics": diagnostics})
            print(f"{index:02d}: {source.name} -> {len(labels)} detections")
    finally:
        close = getattr(detector, "close", None)
        if callable(close):
            close()
    (args.output / "runtime-detections.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
