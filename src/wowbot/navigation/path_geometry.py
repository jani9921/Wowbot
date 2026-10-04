from __future__ import annotations

from dataclasses import dataclass
from math import atan2, hypot, pi
from typing import Sequence

from .path_sampling import PathSample, PathTrace


@dataclass(frozen=True)
class PathVertex:
    x: float
    y: float
    source_sample_index: int
    turn_angle_deg: float | None = None


@dataclass(frozen=True)
class PathGeometry:
    context_id: str
    edge_id: str | None
    vertices: tuple[PathVertex, ...]
    length: float


def _angle_change(a: PathSample, b: PathSample, c: PathSample) -> float:
    a1 = atan2(b.y - a.y, b.x - a.x)
    a2 = atan2(c.y - b.y, c.x - b.x)
    d = (a2 - a1 + pi) % (2 * pi) - pi
    return abs(d) * 180.0 / pi


def simplify_path(
    trace: PathTrace,
    *,
    min_turn_deg: float = 18.0,
    min_vertex_spacing: float = 0.012,
) -> PathGeometry:
    if not trace.samples:
        return PathGeometry(trace.context_id, trace.edge_id, (), 0.0)
    if len(trace.samples) <= 2:
        vertices = tuple(
            PathVertex(s.x, s.y, i) for i, s in enumerate(trace.samples)
        )
        return PathGeometry(trace.context_id, trace.edge_id, vertices, trace.length)

    selected = [0]
    last_idx = 0
    for i in range(1, len(trace.samples) - 1):
        s = trace.samples[i]
        if hypot(s.x - trace.samples[last_idx].x, s.y - trace.samples[last_idx].y) < min_vertex_spacing:
            continue
        turn = _angle_change(trace.samples[i - 1], s, trace.samples[i + 1])
        if turn >= min_turn_deg:
            selected.append(i)
            last_idx = i

    if selected[-1] != len(trace.samples) - 1:
        selected.append(len(trace.samples) - 1)

    vertices = []
    for pos, idx in enumerate(selected):
        turn = None
        if 0 < idx < len(trace.samples) - 1:
            turn = _angle_change(trace.samples[idx - 1], trace.samples[idx], trace.samples[idx + 1])
        s = trace.samples[idx]
        vertices.append(PathVertex(s.x, s.y, idx, turn))
    return PathGeometry(trace.context_id, trace.edge_id, tuple(vertices), trace.length)


def geometry_to_json(geometry: PathGeometry) -> dict:
    return {
        "context_id": geometry.context_id,
        "edge_id": geometry.edge_id,
        "length": geometry.length,
        "vertices": [
            {
                "x": v.x,
                "y": v.y,
                "source_sample_index": v.source_sample_index,
                "turn_angle_deg": v.turn_angle_deg,
            }
            for v in geometry.vertices
        ],
    }
