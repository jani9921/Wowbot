from __future__ import annotations

from dataclasses import dataclass
import math

from wowbot.vision.models import WorldPosition
from .graph import NavGraph, NavGraphEdge


@dataclass(frozen=True, slots=True)
class GraphLocation:
    position: WorldPosition
    nearest_node_id: str | None
    nearest_node_distance: float | None
    nearest_edge_id: str | None
    nearest_edge_distance: float | None
    edge_progress: float | None
    confidence: float


class GraphLocalizer:
    """Map a live player position onto the sparse navigation graph.

    Node distances are useful for semantic waypoints. Edge distance is the
    primary signal for deciding which route segment the player is currently on.
    All geometry is assumed to be in the same normalized map-space coordinate
    system (0..1 for x/y in the current Exile's Reach implementation).
    """

    def __init__(self, graph: NavGraph) -> None:
        self.graph = graph

    def locate(self, position: WorldPosition) -> GraphLocation:
        nearest_node_id = None
        nearest_node_distance = None
        if self.graph.nodes:
            node = min(self.graph.nodes.values(), key=lambda n: _distance(position, n.position))
            nearest_node_id = node.node_id
            nearest_node_distance = _distance(position, node.position)

        nearest_edge_id = None
        nearest_edge_distance = None
        edge_progress = None
        for edge in self.graph.edges.values():
            # Ignore generated reverse duplicates only for reporting; the geometry
            # is equivalent and the first encountered one is enough.
            if edge.edge_id.endswith(":reverse"):
                continue
            a = self.graph.nodes[edge.from_node].position
            b = self.graph.nodes[edge.to_node].position
            distance, progress = _point_to_segment(position, a, b)
            if nearest_edge_distance is None or distance < nearest_edge_distance:
                nearest_edge_distance = distance
                nearest_edge_id = edge.edge_id
                edge_progress = progress

        node_conf = max(0.0, min(1.0, 1.0 - (nearest_node_distance or 0.0) / 0.08)) if nearest_node_distance is not None else 0.0
        edge_conf = max(0.0, min(1.0, 1.0 - (nearest_edge_distance or 1.0) * 8.0)) if nearest_edge_distance is not None else 0.0
        confidence = max(node_conf, edge_conf * 0.9)
        return GraphLocation(
            position=position,
            nearest_node_id=nearest_node_id,
            nearest_node_distance=nearest_node_distance,
            nearest_edge_id=nearest_edge_id,
            nearest_edge_distance=nearest_edge_distance,
            edge_progress=edge_progress,
            confidence=confidence,
        )


def _distance(a: WorldPosition, b: WorldPosition) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _point_to_segment(p: WorldPosition, a: WorldPosition, b: WorldPosition) -> tuple[float, float]:
    vx = b.x - a.x
    vy = b.y - a.y
    vz = b.z - a.z
    wx = p.x - a.x
    wy = p.y - a.y
    wz = p.z - a.z
    vv = vx * vx + vy * vy + vz * vz
    if vv <= 1e-12:
        return _distance(p, a), 0.0
    t = max(0.0, min(1.0, (wx * vx + wy * vy + wz * vz) / vv))
    q = WorldPosition(a.x + t * vx, a.y + t * vy, a.z + t * vz)
    return _distance(p, q), t
