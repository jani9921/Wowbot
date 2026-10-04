"""Compare IsIndoors-verified entrances with the MAP+MMAP computed ones.

Usage: python tools/compare_entrances.py [--map 2175] [--profile DIR]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main() -> int:
    from wowbot.agent.profile_store import profile_name
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", type=int, default=2175)
    parser.add_argument("--profile", default=str(ROOT / "output/agent/profiles" / profile_name()))
    args = parser.parse_args()
    labels = json.loads((ROOT / f"output/navigation/surface_labels_{args.map}.json").read_text(encoding="utf-8"))
    computed = labels["entrances"]
    path = Path(args.profile) / "verified_entrances.jsonl"
    if not path.exists():
        print(f"Nincs még ellenőrzött bejárat: {path}")
        return 0
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        before, after = record["before"], record["after"]
        mid = ((before["x"] + after["x"]) / 2, (before["y"] + after["y"]) / 2)
        nearest = min(computed, key=lambda e: math.dist(mid, e["centre_world"][:2]), default=None)
        distance = math.dist(mid, nearest["centre_world"][:2]) if nearest else float("inf")
        print(f"{record['direction']:5s} {record.get('subzone') or record.get('zone')!s:24s} "
              f"at ({mid[0]:.1f}, {mid[1]:.1f}) -> computed entrance #{nearest and nearest['entrance_id']} "
              f"{distance:.1f} yd away")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
