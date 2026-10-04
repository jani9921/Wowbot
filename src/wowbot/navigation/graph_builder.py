from __future__ import annotations

from collections import defaultdict
import math
from wowbot.vision.models import FeatureType, MapPoint, NavigationVisionObservation
from .graph import NavGraph, NavGraphNode


class WorldMapGraphBuilder:
    """Build a sparse navigation graph from world-map geometry and markers."""

    SUPPORTED = {
        FeatureType.ROAD,
        FeatureType.PATH,
        FeatureType.INTERSECTION,
        FeatureType.BRIDGE,
        FeatureType.ENTRANCE,
        FeatureType.POI,
        FeatureType.ZONE_BOUNDARY,
    }

    def build(self, observation: NavigationVisionObservation) -> NavGraph:
        graph = NavGraph()
        world_map = observation.world_map
        if world_map is None:
            return graph
        features = [f for f in world_map.features if f.feature_type in self.SUPPORTED]
        for idx, feature in enumerate(features):
            graph.add_node(
                NavGraphNode(
                    node_id=f"wm:{feature.feature_type}:{idx}",
                    position=WorldMapGraphBuilder._to_world(feature.center, world_map.width, world_map.height),
                    node_type=feature.feature_type.value,
                    confidence=feature.confidence,
                )
            )
        # Connect nearby graph features; exact route topology can later be supplied by addon/map metadata.
        nodes = list(graph.nodes.values())
        for i, a in enumerate(nodes):
            distances = sorted(((_distance(a.position, b.position), b) for b in nodes[i + 1:]), key=lambda x: x[0])
            for distance, b in distances[:3]:
                if distance <= 350:
                    graph.add_edge_from_nodes(f"geo:{a.node_id}:{b.node_id}", a.node_id, b.node_id)
        return graph

    @staticmethod
    def _to_world(point: MapPoint, width: int, height: int):
        from wowbot.vision.models import WorldPosition
        return WorldPosition(point.x / max(width, 1), point.y / max(height, 1), 0.0)


def _distance(a, b) -> float:
    return math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2 + (a.z-b.z)**2)
