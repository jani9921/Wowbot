"""Smoke/latency benchmark for the process-isolated runtime YOLO backend."""
from __future__ import annotations

import argparse
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument("--model", type=Path, default=None,
                        help="model to benchmark; defaults to runtime selection")
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--alternate-model", type=Path, default=None)
    parser.add_argument("--request-size", type=int, default=None)
    args = parser.parse_args()
    import cv2
    from wowbot.vision.world3d.learned_detector import default_runtime_model_path
    from wowbot.vision.world3d.process_yolo_backend import ProcessYoloBackend

    images = sorted((ROOT / "output" / "agent").rglob("*.jpg"),
                    key=lambda path: path.stat().st_mtime)
    if not images:
        raise SystemExit("no live screenshot available for benchmark")
    image = cv2.imread(str(images[-1]))
    if image is None:
        raise SystemExit(f"cannot decode {images[-1]}")
    model_path = args.model or default_runtime_model_path()
    alternate_model = args.alternate_model
    if alternate_model is None and model_path.suffix.lower() == ".engine":
        candidate = model_path.with_name(f"{model_path.stem}_512.engine")
        alternate_model = candidate if candidate.is_file() else None
    backend = ProcessYoloBackend(
        model_path, device="auto",
        image_size=args.image_size,
        max_detections=18, timeout_seconds=30.,
        alternate_model_path=alternate_model, alternate_image_size=512)
    try:
        warm_deadline = time.monotonic() + 90.
        while backend.status == "warming" and time.monotonic() < warm_deadline:
            backend.predict(image, confidence=.05, iou=.45)
            time.sleep(.10)
        if backend.status != "ready":
            raise SystemExit(backend.load_error or f"backend status={backend.status}")
        timings = []
        counts = []
        for _ in range(max(1, args.iterations)):
            started = time.perf_counter()
            counts.append(len(backend.predict_at_size(
                image, confidence=.05, iou=.45,
                image_size=args.request_size or args.image_size)))
            timings.append((time.perf_counter() - started) * 1000)
        ordered = sorted(timings)
        p95 = ordered[min(len(ordered)-1, int(len(ordered)*.95))]
        print(f"status={backend.status} device={backend.active_device} "
              f"detections={counts[-1]} median_ms={statistics.median(timings):.2f} "
              f"p95_ms={p95:.2f} max_ms={max(timings):.2f}")
        return 0
    finally:
        backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
