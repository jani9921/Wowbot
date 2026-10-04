"""Resume an interrupted World3D YOLO run and copy its best weights.

Usage: python tools/resume_world3d_yolo.py runs/world3d/<run> models/<name>.pt

Continues from ``<run>/weights/last.pt`` with Ultralytics' own resume (same
epochs, optimizer state and data), then copies ``best.pt`` to the model path.
The artifact is OFFLINE_TRAINED only; it is never promoted into live FULL_AI.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    run, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    last = run / "weights" / "last.pt"
    if not last.is_file():
        print(f"No checkpoint to resume: {last}", file=sys.stderr)
        return 3
    from ultralytics import YOLO  # type: ignore[import-not-found]
    YOLO(str(last)).train(resume=True)
    best = run / "weights" / "best.pt"
    if not best.is_file():
        print(f"Training finished without best weights: {best}", file=sys.stderr)
        return 4
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, out)
    print(f"Model artifact: {out}")
    print("Status: OFFLINE_TRAINED; not live-promoted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
