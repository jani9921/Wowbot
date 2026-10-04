from __future__ import annotations

from dataclasses import dataclass
import heapq
from typing import Optional

from wowbot.vision.models import WorldPosition
from .graph import NavGraph, NavGraphNode
from .learning import LearningPolicy


class NoRouteError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlannedRoute:
    node_ids: tuple[str, ...]
    total_cost: float


class RoutePlanner:
    def __init__(self, graph: NavGraph, *, learning: LearningPolicy | None = None) -> None:
        self.graph = graph
        self.learning = learning

    def plan(self, start: WorldPosition, destination: WorldPosition) -> PlannedRoute:
        start_node = self.graph.nearest_node(start)
        end_node = self.graph.nearest_node(destination)
        return self.plan_between(start_node, end_node)

    def plan_between(self, start: NavGraphNode, end: NavGraphNode) -> PlannedRoute:
        frontier: list[tuple[float, str]] = [(0.0, start.node_id)]
        cost_so_far: dict[str, float] = {start.node_id: 0.0}
        previous: dict[str, Optional[str]] = {start.node_id: None}

        while frontier:
            cost, node_id = heapq.heappop(frontier)
            if node_id == end.node_id:
                return PlannedRoute(self._reconstruct(previous, end.node_id), cost)
            if cost > cost_so_far.get(node_id, float("inf")):
                continue
            for edge in self.graph.outgoing_edges(node_id):
                edge_cost = edge.cost
                if self.learning is not None:
                    edge_cost *= self.learning.segment_cost_multiplier(edge.edge_id)
                next_cost = cost + edge_cost
                if next_cost < cost_so_far.get(edge.to_node, float("inf")):
                    cost_so_far[edge.to_node] = next_cost
                    previous[edge.to_node] = node_id
                    heapq.heappush(frontier, (next_cost, edge.to_node))
        raise NoRouteError(f"no route from {start.node_id} to {end.node_id}")

    @staticmethod
    def _reconstruct(previous: dict[str, Optional[str]], end_id: str) -> tuple[str, ...]:
        path: list[str] = []
        current: Optional[str] = end_id
        while current is not None:
            path.append(current)
            current = previous[current]
        path.reverse()
        return tuple(path)
