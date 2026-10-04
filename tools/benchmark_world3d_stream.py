"""Benchmark the production continuous World3D detector on saved live frames."""
from __future__ import annotations

import argparse
from itertools import cycle
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered)-1, int((len(ordered)-1)*quantile))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=6.)
    parser.add_argument("--source-hz", type=float, default=40.)
    parser.add_argument("--frames", type=int, default=8)
    args = parser.parse_args()

    import cv2
    from wowbot.vision.world3d.learned_detector import (
        build_runtime_learned_detector, default_runtime_model_path)
    from wowbot.vision.world3d.models import PixelRect, WorldSceneROI
    from wowbot.vision.world3d.v3 import World3DPerceptionV3

    paths = sorted((ROOT / "output" / "agent").rglob("*.jpg"),
                   key=lambda path: path.stat().st_mtime)[-max(1, args.frames):]
    frames = []
    warm_image = None
    for path in paths:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        warm_image = image
        bgra = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
        frames.append((bgra.tobytes(), bgra.shape[1], bgra.shape[0]))
    if not frames:
        raise SystemExit("no decodable live capture")

    learned = build_runtime_learned_detector(default_runtime_model_path())
    if learned is None:
        raise SystemExit("no runtime learned detector configured")
    warm_deadline = time.monotonic() + 90.
    while (getattr(learned.backend, "status", "ready") == "warming"
           and time.monotonic() < warm_deadline):
        learned.backend.predict(warm_image, confidence=.01, iou=.45)
        time.sleep(.05)
    if getattr(learned.backend, "status", "ready") != "ready":
        raise SystemExit(getattr(learned.backend, "load_error", None)
                         or "learned detector did not become ready")
    pipeline = World3DPerceptionV3(
        learned_detector=learned, proposal_mode="YOLO_ONLY",
        continuous_detector=True)
    process_ms: list[float] = []
    refresh_ms: list[float] = []
    calls = refreshes = 0
    interval = 1. / max(1., args.source_hz)
    started = time.monotonic()
    next_at = started
    try:
        for raw, width, height in cycle(frames):
            now = time.monotonic()
            if now-started >= max(.5, args.seconds):
                break
            if now < next_at:
                time.sleep(next_at-now)
            observed_at = time.monotonic()
            before = time.perf_counter()
            pipeline.process(raw, width, height,
                             WorldSceneROI(PixelRect(0, 0, width, height)),
                             observed_at=observed_at,
                             ui_hints={"world3d_profile": {"detector_hz": 5.}})
            process_ms.append((time.perf_counter()-before)*1000.)
            calls += 1
            detector = pipeline.last_diagnostics.get("detector") or {}
            if detector.get("refreshed"):
                refreshes += 1
                if detector.get("last_refresh_ms") is not None:
                    refresh_ms.append(float(detector["last_refresh_ms"]))
            next_at = max(next_at+interval, time.monotonic())
    finally:
        pipeline.close()
    elapsed = max(.001, time.monotonic()-started)
    diagnostics = pipeline.last_diagnostics.get("detector") or {}
    print(
        f"elapsed_s={elapsed:.2f} source_calls_hz={calls/elapsed:.2f} "
        f"detector_refresh_hz={refreshes/elapsed:.2f} "
        f"call_p50_ms={statistics.median(process_ms):.2f} "
        f"call_p95_ms={percentile(process_ms, .95):.2f} "
        f"refresh_p50_ms={statistics.median(refresh_ms) if refresh_ms else 0:.2f} "
        f"refresh_p95_ms={percentile(refresh_ms, .95) if refresh_ms else 0:.2f} "
        f"submissions={diagnostics.get('submissions')} "
        f"completions={diagnostics.get('completions')} "
        f"busy_frames_superseded={diagnostics.get('busy_frames_superseded')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
