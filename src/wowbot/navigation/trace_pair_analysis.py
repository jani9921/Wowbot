from __future__ import annotations
from dataclasses import dataclass
from math import hypot
from typing import Sequence

from .path_geometry import PathGeometry


@dataclass(frozen=True)
class RouteComparison:
    context_id: str
    vertex_counts: tuple[int, int]
    lengths: tuple[float, float]
    start_separation: float
    end_separation: float
    common_vertex_pairs: tuple[tuple[int, int, float], ...]
    main_only_vertices: tuple[int, ...]
    alt_only_vertices: tuple[int, ...]
    divergence_index_main: int | None
    divergence_index_alt: int | None


def _monotonic_matches(a: Sequence[tuple[float, float]], b: Sequence[tuple[float, float]], threshold: float) -> tuple[tuple[int,int,float], ...]:
    out = []
    j0 = 0
    for i, p in enumerate(a):
        candidates = []
        for j in range(j0, len(b)):
            d = hypot(p[0] - b[j][0], p[1] - b[j][1])
            if d <= threshold:
                candidates.append((d, j))
        if not candidates:
            continue
        d, j = min(candidates, key=lambda item: (item[0], item[1]))
        out.append((i, j, d))
        j0 = j + 1
    return tuple(out)


def compare_geometries(main: PathGeometry, alt: PathGeometry, *, common_threshold: float = 0.025) -> RouteComparison:
    if main.context_id != alt.context_id:
        raise ValueError("Cannot compare geometries from different contexts")
    a=[(v.x,v.y) for v in main.vertices]
    b=[(v.x,v.y) for v in alt.vertices]
    pairs=_monotonic_matches(a,b,common_threshold)
    matched_main={p[0] for p in pairs}; matched_alt={p[1] for p in pairs}
    div_m=next((i for i in range(len(a)) if i not in matched_main), None)
    div_a=next((i for i in range(len(b)) if i not in matched_alt), None)
    return RouteComparison(
        context_id=main.context_id,
        vertex_counts=(len(a),len(b)), lengths=(main.length,alt.length),
        start_separation=hypot(a[0][0]-b[0][0],a[0][1]-b[0][1]),
        end_separation=hypot(a[-1][0]-b[-1][0],a[-1][1]-b[-1][1]),
        common_vertex_pairs=pairs,
        main_only_vertices=tuple(i for i in range(len(a)) if i not in matched_main),
        alt_only_vertices=tuple(i for i in range(len(b)) if i not in matched_alt),
        divergence_index_main=div_m, divergence_index_alt=div_a,
    )


def comparison_to_json(c: RouteComparison) -> dict:
    return {
        "context_id": c.context_id,
        "routes": {
            "main": {"vertex_count": c.vertex_counts[0], "length": c.lengths[0]},
            "alternate": {"vertex_count": c.vertex_counts[1], "length": c.lengths[1]},
        },
        "start_separation": c.start_separation,
        "end_separation": c.end_separation,
        "common_vertex_pairs": [
            {"main_vertex": i, "alternate_vertex": j, "distance": d}
            for i,j,d in c.common_vertex_pairs
        ],
        "main_only_vertices": list(c.main_only_vertices),
        "alternate_only_vertices": list(c.alt_only_vertices),
        "first_unmatched_main_vertex": c.divergence_index_main,
        "first_unmatched_alternate_vertex": c.divergence_index_alt,
    }
