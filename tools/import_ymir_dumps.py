"""Fill the profile's learned TDB from finished Ymir dumps.

Runs by itself when the GUI's Ymir capture stops; it can also be started by
hand to import every earlier dump once:

    python tools/import_ymir_dumps.py
"""
from __future__ import annotations

import logging  # Load stdlib before adding this repository's src/logging directory.
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from wowbot.agent.pkt_dump_import import import_dumps
from wowbot.agent.profile_store import profile_directory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dumps", type=Path, default=ROOT / "runtime" / "ymir" / "dumps")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "agent",
                        help="the GUI output folder; the profile's tdb_learned.sqlite3 is filled")
    parser.add_argument("--settle", type=float, default=30.,
                        help="skip dumps modified this recently (a running Ymir may still write them)")
    args = parser.parse_args(argv)
    learned_path = profile_directory(args.output / "pid-0") / "tdb_learned.sqlite3"
    started = time.time()
    summary = import_dumps(args.dumps, learned_path, settled_seconds=args.settle)
    summary.update(learned=str(learned_path), seconds=round(time.time()-started, 1), finished_at=time.time())
    log = args.output / "ymir-bootstrap" / "dump_import.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
