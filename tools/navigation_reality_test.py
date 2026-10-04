from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path


def load_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def position(data: dict) -> tuple[float, float]:
    p = data.get("position") or {}
    return float(p.get("x", 0.0)), float(p.get("y", 0.0))


def main() -> int:
    parser = argparse.ArgumentParser(description="Passive M7.2 live A->B map-position reality test.")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--target-x", type=float, required=True)
    parser.add_argument("--target-y", type=float, required=True)
    parser.add_argument("--tolerance", type=float, default=0.015)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    print("=" * 72)
    print("WoW Navigation — M7.2 Reality Test")
    print("PASSIVE MODE: no keyboard/mouse input is sent")
    print(f"target        : x={args.target_x:.5f} y={args.target_y:.5f}")
    print(f"tolerance     : {args.tolerance:.5f}")
    print(f"state         : {args.state}")
    print("=" * 72)

    baseline = None
    previous_distance = None
    last_sig = None

    try:
        while True:
            data = load_state(args.state)
            x, y = position(data)
            dist = math.hypot(x - args.target_x, y - args.target_y)

            if baseline is None:
                baseline = dist
            delta = 0.0 if previous_distance is None else previous_distance - dist

            sig = (
                data.get("state_written_at"),
                data.get("timestamp"),
                data.get("map_id"),
                data.get("zone_name"),
                data.get("subzone_name"),
                x, y,
            )
            if sig != last_sig:
                if dist <= args.tolerance:
                    status = "ARRIVED"
                elif delta > 1e-9:
                    status = "PROGRESS"
                else:
                    status = "NO_PROGRESS"
                print(
                    f"[{status:<11}] pos=({x:.5f},{y:.5f}) "
                    f"dist={dist:.5f} delta={delta:+.5f} "
                    f"map={data.get('map_id')} context={data.get('zone_name')}"
                )
                last_sig = sig
                previous_distance = dist

            if dist <= args.tolerance:
                print(f"[RESULT] baseline_reduction={(baseline - dist):+.5f}")
                return 0

            time.sleep(max(args.interval, 0.1))
    except KeyboardInterrupt:
        print("[STOPPED] passive test interrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
