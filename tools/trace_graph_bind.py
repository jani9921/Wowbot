from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.navigation.path_geometry import PathGeometry, PathVertex
from wowbot.navigation.trace_graph_binding import SeedEdge, bind_geometry_to_seed_edges


def load_geometry(path: Path) -> PathGeometry:
    data = json.loads(path.read_text(encoding="utf-8"))
    return PathGeometry(
        context_id=data["context_id"],
        edge_id=data.get("edge_id"),
        length=float(data["length"]),
        vertices=tuple(PathVertex(
            x=float(v["x"]), y=float(v["y"]),
            source_sample_index=int(v["source_sample_index"]),
            turn_angle_deg=v.get("turn_angle_deg"),
        ) for v in data["vertices"]),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Bind recorded main-route geometry to the sparse seed graph (passive).")
    ap.add_argument("--geometry", default="runtime/client-1/path_geometry.json")
    ap.add_argument("--graph", default="samples/exile_reach_seed_graph.json")
    ap.add_argument("--output", default="runtime/client-1/path_graph_binding.json")
    ap.add_argument("--max-distance", type=float, default=0.035)
    args = ap.parse_args()

    geometry = load_geometry(Path(args.geometry))
    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    nodes = {n["id"]: (float(n["x"]), float(n["y"])) for n in graph["nodes"]}
    edges = tuple(SeedEdge(e["a"] + ":" + e["b"], e["a"], e["b"], nodes[e["a"]], nodes[e["b"]]) for e in graph["edges"])
    result = bind_geometry_to_seed_edges(geometry, edges, max_distance=args.max_distance)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[bind] geometry_vertices={result['source_geometry']['vertex_count']} matched={result['matched_vertex_count']} bound_edges={len(result['bound_edges'])}")
    print(f"[bind] output={out}")
    for item in result["bound_edges"]:
        print(f"  {item['edge_id']}: points={item['observation_point_count']} deviation={item['max_deviation']:.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
