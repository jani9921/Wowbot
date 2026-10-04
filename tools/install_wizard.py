"""Installation wizard launcher (see src/wowbot/install/wizard.py)."""
from __future__ import annotations

import logging  # Preload stdlib before adding the existing src/logging directory.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


if __name__ == "__main__":
    from wowbot.install.wizard import main
    raise SystemExit(main())
