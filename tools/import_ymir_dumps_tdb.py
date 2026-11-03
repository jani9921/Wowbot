"""Update the TrinityCore TDB from the Ymir dumps through WowPacketParser.

Started by the GUI button "Ymir dumpok -> TDB" (and, when ticked, after the
Ymir capture stops); it can also be run by hand:

    python tools/import_ymir_dumps_tdb.py

Progress goes to output/agent/ymir-bootstrap/tdb_import_progress.json.
"""
from __future__ import annotations

import logging  # Load stdlib before adding this repository's src/logging directory.
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from wowbot.agent.pkt_dump_import import import_dumps as import_learned
from wowbot.agent.pkt_dump_import import learned_has
from wowbot.agent.profile_store import profile_directory
from wowbot.agent.wpp_tdb_import import WPP_EXE, import_dumps, revert_column

PROGRESS = ROOT / "output" / "agent" / "ymir-bootstrap" / "tdb_import_progress.json"


def configured_tdb() -> Path | None:
    try:
        path = json.loads((ROOT / "config" / "reference_catalog.local.json").read_text(encoding="utf-8"))["path"]
    except (OSError, ValueError, KeyError):
        return None
    return Path(path) if path else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tdb", type=Path, default=configured_tdb())
    parser.add_argument("--dumps", type=Path, default=ROOT / "runtime" / "ymir" / "dumps")
    parser.add_argument("--work", type=Path, default=ROOT / "runtime" / "ymir" / "wpp_work")
    parser.add_argument("--progress", type=Path, default=PROGRESS)
    parser.add_argument("--wpp", type=Path, default=WPP_EXE)
    parser.add_argument("--settle", type=float, default=30.,
                        help="skip dumps modified this recently (a running Ymir may still write them)")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "agent",
                        help="the GUI output folder; the profile's tdb_learned.sqlite3 is filled first")
    parser.add_argument("--recycle", action="store_true",
                        help="move each dump that is in both databases to the Recycle Bin afterwards")
    parser.add_argument("--revert-column", metavar="TABLE.COLUMN",
                        help="only undo the logged WPP updates of one column (e.g. quest_objectives.ConditionalAmount)")
    args = parser.parse_args(argv)
    if args.tdb is None or not args.tdb.is_file():
        args.progress.parent.mkdir(parents=True, exist_ok=True)
        args.progress.write_text(json.dumps({"state": "error", "errors": [f"TDB not found: {args.tdb}"]}),
                                 encoding="utf-8")
        return 2
    if args.revert_column:
        table, _, column = args.revert_column.partition(".")
        print(f"{revert_column(args.tdb, table, column)} sor visszaállítva ({args.revert_column})")
        return 0
    # The learned TDB first: a dump leaves the folder only when both have it.
    learned_path = profile_directory(args.output / "pid-0") / "tdb_learned.sqlite3"
    import_learned(args.dumps, learned_path, settled_seconds=args.settle)
    summary = import_dumps(args.dumps, args.tdb, work=args.work, progress=args.progress,
                           settled_seconds=args.settle, exe=args.wpp,
                           recycle_when=(lambda path: learned_has(learned_path, path)) if args.recycle else None)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary.get("state") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
