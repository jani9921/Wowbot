
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Allow direct execution from the project root without requiring
# `pip install -e .` first.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wowbot.navigation.path_sampling import PathTrace


def main() -> int:
    p = argparse.ArgumentParser(description="Record live WoW map-position path samples.")
    p.add_argument("--state", default="runtime/client-1/state.json")
    p.add_argument("--context", default=None)
    p.add_argument("--edge", default=None)
    p.add_argument("--interval", type=float, default=0.5)
    p.add_argument("--spacing", type=float, default=0.003)
    p.add_argument("--output", default="runtime/client-1/path_trace.json")
    args = p.parse_args()

    state_path = Path(args.state)
    out_path = Path(args.output)
    trace = None
    last_written = None

    print("=" * 72)
    print("WoW Navigation — M7.3.4 Live Path Sampling")
    print("PASSIVE MODE: no keyboard/mouse input is sent")
    print(f"state  : {state_path}")
    print(f"output : {out_path}")
    print("=" * 72)

    try:
        while True:
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(args.interval)
                continue

            pos = payload.get("position") or {}
            x, y = pos.get("x"), pos.get("y")
            if x is None or y is None:
                time.sleep(args.interval)
                continue

            context_id = args.context or f"map:{payload.get('map_id')}"
            if trace is None or trace.context_id != context_id:
                trace = PathTrace(
                    context_id=context_id,
                    edge_id=args.edge,
                    min_spacing=args.spacing,
                )

            changed = trace.add(
                float(x),
                float(y),
                float(payload.get("state_written_at") or payload.get("timestamp") or time.time()),
            )
            if changed:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = out_path.with_suffix(out_path.suffix + ".tmp")
                tmp.write_text(
                    json.dumps(
                        {
                            "context_id": trace.context_id,
                            "edge_id": trace.edge_id,
                            "samples": [s.__dict__ for s in trace.samples],
                            "sample_count": len(trace.samples),
                            "length": trace.length,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                tmp.replace(out_path)
                if last_written != payload.get("state_written_at"):
                    print(
                        f"[SAMPLE] x={float(x):.5f} y={float(y):.5f} "
                        f"count={len(trace.samples)} length={trace.length:.5f}"
                    )
                    last_written = payload.get("state_written_at")
            time.sleep(max(args.interval, 0.1))
    except KeyboardInterrupt:
        print("[sampler] stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
