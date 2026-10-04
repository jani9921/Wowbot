"""Train an optional YOLO World3D proposal model after strict data audit.

The command refuses structurally invalid or leaking datasets.  A successful
run creates a model artifact; it does not promote the model into live FULL_AI.
Promotion requires held-out replay and live validation separately.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.world3d.dataset_audit import audit_yolo_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path, help="YOLO data.yaml")
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--patience", type=int, default=100,
                        help="stop after this many epochs without validation improvement")
    parser.add_argument("--device", default="auto", help="auto, cpu, or CUDA device index")
    parser.add_argument("--name", default="yolo",
                        help="Separate Ultralytics run directory name")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "models" / "world3d_yolo.pt")
    args = parser.parse_args()

    dataset_root = args.data.resolve().parent
    audit = audit_yolo_dataset(dataset_root)
    if not audit.training_ready:
        print("Training refused: dataset audit failed:", file=sys.stderr)
        for error in audit.errors:
            print(f"  - {error}", file=sys.stderr)
        return 2

    try:
        import torch
        from ultralytics import YOLO  # type: ignore[import-not-found]
    except ImportError as exc:
        print(f"Training dependency missing: {exc}", file=sys.stderr)
        return 3

    if args.device == "auto":
        device: str | int = 0 if torch.cuda.is_available() else "cpu"
    else:
        device = int(args.device) if args.device.isdigit() else args.device
    model = YOLO(args.model)
    result = model.train(
        data=str(args.data.resolve()), epochs=max(1, args.epochs),
        imgsz=max(64, args.imgsz), batch=args.batch, device=device, patience=max(1, args.patience),
        workers=0, project=str(PROJECT_ROOT / "runs" / "world3d"),
        name=str(args.name), exist_ok=False,
    )
    best = Path(result.save_dir) / "weights" / "best.pt"
    if not best.is_file():
        print(f"Training finished without best weights: {best}", file=sys.stderr)
        return 4
    args.out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, args.out)
    print(f"Model artifact: {args.out.resolve()}")
    print("Status: OFFLINE_TRAINED; not live-promoted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
