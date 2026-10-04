from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable

from .path_geometry import PathGeometry


@dataclass(frozen=True)
class SeedEdge:
    edge_id: str
    from_node: str
    to_node: str
    a: tuple[float, float]
    b: tuple[float, float]


@dataclass(frozen=True)
class EdgeMatch:
    geometry_vertex_index: int
    edge_id: str
    distance: float
    progress: float


@dataclass(frozen=True)
class BoundEdge:
    edge_id: str
    from_node: str
    to_node: str
    geometry_vertices: tuple[tuple[float, float], ...]
    observed_length: float
    seed_straight_length: float
    max_deviation: float
    observation_point_count: int


def point_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom <= 1e-12:
        return hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    qx, qy = ax + t * dx, ay + t * dy
    return hypot(px - qx, py - qy), t


def _polyline_length(points: Iterable[tuple[float, float]]) -> float:
    pts = list(points)
    return sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def _max_deviation(points: Iterable[tuple[float, float]], a: tuple[float, float], b: tuple[float, float]) -> float:
    return max((point_to_segment(x, y, a[0], a[1], b[0], b[1])[0] for x, y in points), default=0.0)


def match_geometry_to_edges(
    geometry: PathGeometry,
    seed_edges: tuple[SeedEdge, ...],
    *,
    max_distance: float = 0.035,
) -> tuple[EdgeMatch, ...]:
    matches: list[EdgeMatch] = []
    for i, vertex in enumerate(geometry.vertices):
        candidates = []
        for edge in seed_edges:
            d, t = point_to_segment(vertex.x, vertex.y, edge.a[0], edge.a[1], edge.b[0], edge.b[1])
            candidates.append((d, edge.edge_id, t))
        if not candidates:
            continue
        d, edge_id, t = min(candidates, key=lambda item: (item[0], item[1]))
        if d <= max_distance:
            matches.append(EdgeMatch(i, edge_id, d, t))
    return tuple(matches)


def bind_geometry_to_seed_edges(
    geometry: PathGeometry,
    seed_edges: tuple[SeedEdge, ...],
    *,
    max_distance: float = 0.035,
) -> dict:
    edge_by_id = {e.edge_id: e for e in seed_edges}
    matches = match_geometry_to_edges(geometry, seed_edges, max_distance=max_distance)

    # Preserve traversal order; never reverse or reorder the observed trace.
    groups: list[list[EdgeMatch]] = []
    for m in matches:
        if not groups or groups[-1][-1].edge_id != m.edge_id:
            groups.append([m])
        else:
            groups[-1].append(m)

    bound: list[BoundEdge] = []
    point_candidates: list[dict] = []
    for group in groups:
        edge = edge_by_id[group[0].edge_id]
        points = tuple((geometry.vertices[m.geometry_vertex_index].x, geometry.vertices[m.geometry_vertex_index].y) for m in group)
        if len(points) < 2:
            point_candidates.append({
                "edge_id": edge.edge_id,
                "geometry_vertex_indices": [m.geometry_vertex_index for m in group],
                "distance": min(m.distance for m in group),
            })
            continue
        bound.append(BoundEdge(
            edge_id=edge.edge_id,
            from_node=edge.from_node,
            to_node=edge.to_node,
            geometry_vertices=points,
            observed_length=_polyline_length(points),
            seed_straight_length=hypot(edge.b[0] - edge.a[0], edge.b[1] - edge.a[1]),
            max_deviation=_max_deviation(points, edge.a, edge.b),
            observation_point_count=len(group),
        ))

    transitions = []
    for left, right in zip(bound, bound[1:]):
        left_edge, right_edge = edge_by_id[left.edge_id], edge_by_id[right.edge_id]
        contiguous = (
            left_edge.to_node == right_edge.from_node
            or left_edge.from_node == right_edge.to_node
            or left_edge.from_node == right_edge.from_node
            or left_edge.to_node == right_edge.to_node
        )
        transitions.append({
            "from_edge": left.edge_id,
            "to_edge": right.edge_id,
            "topologically_contiguous": contiguous,
        })

    return {
        "context_id": geometry.context_id,
        "source": "recorded_main_route",
        "coverage_scope": "partial_route_only",
        "seed_graph_authoritative": True,
        "max_match_distance": max_distance,
        "source_geometry": {
            "vertex_count": len(geometry.vertices),
            "length": geometry.length,
        },
        "matched_vertex_count": len(matches),
        "unmatched_vertex_count": len(geometry.vertices) - len(matches),
        "single_vertex_candidates": point_candidates,
        "bound_edges": [
            {
                "edge_id": b.edge_id,
                "from_node": b.from_node,
                "to_node": b.to_node,
                "geometry_vertices": [[x, y] for x, y in b.geometry_vertices],
                "observed_length": b.observed_length,
                "seed_straight_length": b.seed_straight_length,
                "max_deviation": b.max_deviation,
                "observation_point_count": b.observation_point_count,
            }
            for b in bound
        ],
        "transitions": transitions,
        "unmatched_seed_edges": [
            e.edge_id for e in seed_edges if e.edge_id not in {b.edge_id for b in bound}
        ],
    }
