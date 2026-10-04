"""Audit a YOLO dataset before any World3D training run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.vision.world3d.dataset_audit import audit_yolo_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--allow-no-test", action="store_true",
                        help="Development-only: do not require a held-out test split")
    args = parser.parse_args()
    audit = audit_yolo_dataset(args.dataset, require_test_split=not args.allow_no_test)
    print(json.dumps(audit.to_dict(), ensure_ascii=False, indent=2))
    return 0 if audit.training_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())

