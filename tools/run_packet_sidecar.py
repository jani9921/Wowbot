"""Launch the passive AIPC packet capture/decode/forward sidecar."""
from __future__ import annotations

import logging  # Load stdlib before adding this repository's src/logging directory.
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from wowbot.packetio.sidecar import main


if __name__ == "__main__":
    raise SystemExit(main())
