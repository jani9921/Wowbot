"""Type ``/reload`` into the selected WoW client (after an addon update).

Keys go only to the exact PID while it is the foreground window (same
guards as tools/wow_auto_start.py).  Usage: python tools/wow_reload_ui.py --pid 17996
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tools.wow_auto_start import press_enter, type_text  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    args = parser.parse_args()
    press_enter(args.pid)          # open the chat edit box
    time.sleep(.3)
    type_text(args.pid, "/reload")
    time.sleep(.1)
    press_enter(args.pid)
    print("/reload sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
