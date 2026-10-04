from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from wowbot.navigation.path_sampling import PathSample, PathTrace
from wowbot.navigation.path_geometry import geometry_to_json, simplify_path


def main() -> int:
    p = argparse.ArgumentParser(description="Convert a recorded path trace into simplified path geometry.")
    p.add_argument("--input", default="runtime/client-1/path_trace.json")
    p.add_argument("--output", default="runtime/client-1/path_geometry.json")
    p.add_argument("--min-turn-deg", type=float, default=18.0)
    p.add_argument("--min-vertex-spacing", type=float, default=0.012)
    args = p.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    trace = PathTrace(
        context_id=data["context_id"],
        edge_id=data.get("edge_id"),
        min_spacing=0.0,
        samples=[PathSample(**s) for s in data["samples"]],
    )
    geometry = simplify_path(
        trace,
        min_turn_deg=args.min_turn_deg,
        min_vertex_spacing=args.min_vertex_spacing,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(geometry_to_json(geometry), indent=2), encoding="utf-8")
    print(f"[geometry] samples={len(trace.samples)} vertices={len(geometry.vertices)} length={geometry.length:.5f}")
    print(f"[geometry] output={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
