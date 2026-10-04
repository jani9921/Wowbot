from __future__ import annotations

import sys
from pathlib import Path


try:
    import numpy as np
except ModuleNotFoundError:
    vendor = Path(__file__).resolve().parents[2] / ".vendor"
    if vendor.is_dir():
        sys.path.insert(0, str(vendor))
    import numpy as np


__all__ = ["np"]
