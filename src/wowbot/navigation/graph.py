from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

from wowbot.vision.models import WorldPosition


@dataclass(frozen=True, slots=True)
class NavGraphNode:
    node_id: str
    position: WorldPosition
    node_type: str = "WAYPOINT"
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class NavGraphEdge:
    edge_id: str
    from_node: str
    to_node: str
    distance: float
    estimated_time: float
    risk: float = 0.0
    confidence: float = 1.0

    @property
    def cost(self) -> float:
        return self.distance + self.estimated_time + (self.risk * 10.0)


class NavGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, NavGraphNode] = {}
        self.edges: dict[str, NavGraphEdge] = {}
        self._outgoing: dict[str, list[str]] = {}

    def add_node(self, node: NavGraphNode) -> None:
        self.nodes[node.node_id] = node
        self._outgoing.setdefault(node.node_id, [])

    def add_edge(self, edge: NavGraphEdge, *, bidirectional: bool = True) -> None:
        if edge.from_node not in self.nodes or edge.to_node not in self.nodes:
            raise KeyError("both edge endpoints must exist")
        self.edges[edge.edge_id] = edge
        self._outgoing.setdefault(edge.from_node, []).append(edge.edge_id)
        if bidirectional:
            reverse_id = f"{edge.edge_id}:reverse"
            reverse = NavGraphEdge(reverse_id, edge.to_node, edge.from_node, edge.distance, edge.estimated_time, edge.risk, edge.confidence)
            self.edges[reverse_id] = reverse
            self._outgoing.setdefault(edge.to_node, []).append(reverse_id)

    def outgoing_edges(self, node_id: str) -> Iterable[NavGraphEdge]:
        for edge_id in self._outgoing.get(node_id, []):
            yield self.edges[edge_id]

    def nearest_node(self, position: WorldPosition) -> NavGraphNode:
        if not self.nodes:
            raise LookupError("graph has no nodes")
        return min(self.nodes.values(), key=lambda n: _distance(n.position, position))

    def add_edge_from_nodes(self, edge_id: str, from_node: str, to_node: str, *, estimated_time: float | None = None, risk: float = 0.0, confidence: float = 1.0) -> None:
        a = self.nodes[from_node]
        b = self.nodes[to_node]
        dist = _distance(a.position, b.position)
        self.add_edge(NavGraphEdge(edge_id, from_node, to_node, dist, dist if estimated_time is None else estimated_time, risk, confidence))


def _distance(a: WorldPosition, b: WorldPosition) -> float:
    return math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2 + (a.z-b.z)**2)
