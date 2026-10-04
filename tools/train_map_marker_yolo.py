"""Export reviewed map-marker crops and train a small YOLO model.

Order of gates (any failure refuses training):
1. export reviewed frames with whole-session splits (no leakage),
2. structural YOLO audit (shared with World3D),
3. quest-class coverage: at least one quest marker class must have enough
   reviewed boxes in train and val.  A player-arrow-only model is refused,
   because it would look trained while detecting no quest marker at all.

A successful run writes models/world_map_markers.pt (or minimap_markers.pt),
which the runtime picks up automatically (AIPC_MAP_MARKER_MODEL=0 disables).
Status after training is OFFLINE_TRAINED only; live validation is separate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.map_marker_dataset import export_dataset, quest_class_coverage  # noqa: E402
from wowbot.vision.map_markers import DEFAULT_MODEL_NAMES  # noqa: E402
from wowbot.vision.world3d.dataset_audit import audit_yolo_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", choices=("WORLD_MAP", "MINIMAP"), default="WORLD_MAP")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--imgsz", type=int, default=None, help="default 960 map / 320 minimap")
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--min-train", type=int, default=20)
    parser.add_argument("--min-val", type=int, default=3)
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    dataset = (args.dataset or ROOT / "datasets" / f"map_markers_{args.surface.lower()}").resolve()
    summary = export_dataset(dataset)
    coverage = quest_class_coverage(summary, minimum_train=args.min_train,
                                    minimum_val=args.min_val)
    audit = audit_yolo_dataset(dataset)
    print(json.dumps({"export": summary, "coverage": coverage,
                      "audit_errors": audit.errors, "audit_warnings": audit.warnings}, indent=1))
    if args.export_only:
        return 0
    if not audit.training_ready:
        print("Training refused: dataset audit failed", file=sys.stderr)
        return 2
    if not coverage["training_ready"]:
        print("Training refused: no quest marker class has enough reviewed boxes "
              f"(need >= {args.min_train} train / {args.min_val} val)", file=sys.stderr)
        return 5
    try:
        import torch
        from ultralytics import YOLO  # type: ignore[import-not-found]
    except ImportError as exc:
        print(f"Training dependency missing: {exc}", file=sys.stderr)
        return 3
    device = (0 if torch.cuda.is_available() else "cpu") if args.device == "auto" else \
        int(args.device) if args.device.isdigit() else args.device
    imgsz = args.imgsz or (960 if args.surface == "WORLD_MAP" else 320)
    result = YOLO(args.model).train(
        data=str(dataset / "data.yaml"), epochs=max(1, args.epochs), imgsz=imgsz,
        batch=args.batch, device=device, workers=0, patience=40,
        # Map icons are orientation- and colour-defined: no flips or hue shifts.
        fliplr=0.0, flipud=0.0, hsv_h=0.0, mosaic=0.5,
        project=str(ROOT / "runs" / "map_markers"), name=args.surface.lower(), exist_ok=False)
    best = Path(result.save_dir) / "weights" / "best.pt"
    if not best.is_file():
        print(f"Training finished without best weights: {best}", file=sys.stderr)
        return 4
    out = args.out or ROOT / "models" / DEFAULT_MODEL_NAMES[args.surface]
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, out)
    print(f"Model artifact: {out}")
    print("Status: OFFLINE_TRAINED; not live-validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
