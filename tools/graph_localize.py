from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.navigation.exile_reach_seed import build_exile_reach_seed_graph
from wowbot.navigation.graph_localization import GraphLocalizer
from wowbot.vision.models import WorldPosition


def load_state(path: Path) -> dict[str, object] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Map live player map-position onto the Exile's Reach sparse graph.")
    parser.add_argument("--state", type=Path, default=Path("runtime/client-1/state.json"))
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    graph = build_exile_reach_seed_graph()
    locator = GraphLocalizer(graph)
    last = None
    while True:
        data = load_state(args.state)
        if data is None:
            print(f"[localize] waiting for state: {args.state}")
        else:
            pos = data.get("position")
            if isinstance(pos, dict):
                p = WorldPosition(float(pos.get("x", 0.0)), float(pos.get("y", 0.0)), float(pos.get("z", 0.0)))
                loc = locator.locate(p)
                sig = (data.get("timestamp"), p.x, p.y, loc.nearest_node_id, loc.nearest_edge_id)
                if sig != last:
                    print("=" * 72)
                    print("WoW Navigation — Graph Localization")
                    print("=" * 72)
                    print(f"character      : {data.get('character_name')}")
                    print(f"map_id         : {data.get('map_id')}")
                    print(f"zone           : {data.get('zone_name')}")
                    print(f"position       : x={p.x:.5f} y={p.y:.5f}")
                    print(f"nearest node   : {loc.nearest_node_id} d={loc.nearest_node_distance:.5f}" if loc.nearest_node_distance is not None else "nearest node   : <none>")
                    print(f"nearest edge   : {loc.nearest_edge_id} d={loc.nearest_edge_distance:.5f} progress={loc.edge_progress:.3f}" if loc.nearest_edge_distance is not None else "nearest edge   : <none>")
                    print(f"confidence     : {loc.confidence:.2f}")
                    print("=" * 72)
                    last = sig
        if not args.watch:
            return 0
        time.sleep(max(args.interval, 0.1))


if __name__ == "__main__":
    raise SystemExit(main())
