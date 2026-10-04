from wowbot.navigation.graph_builder import WorldMapGraphBuilder
from wowbot.vision.models import FeatureType, DetectedFeature, MapPoint, NavigationVisionObservation, WorldMapObservation


def test_world_map_graph_builder_creates_sparse_graph():
    obs = NavigationVisionObservation(world_map=WorldMapObservation(
        1000, 800, None,
        features=(
            DetectedFeature(FeatureType.INTERSECTION, MapPoint(200, 300), 0.9),
            DetectedFeature(FeatureType.BRIDGE, MapPoint(400, 300), 0.9),
            DetectedFeature(FeatureType.ENTRANCE, MapPoint(600, 300), 0.8),
        ),
    ))
    graph = WorldMapGraphBuilder().build(obs)
    assert len(graph.nodes) == 3
    assert len(graph.edges) >= 2


def test_exile_reach_seed_graph_is_connected_enough_for_bootstrap():
    from wowbot.navigation.exile_reach_seed import build_exile_reach_seed_graph
    graph = build_exile_reach_seed_graph()
    assert len(graph.nodes) == 11
    assert len(graph.edges) >= 11
    assert graph.nearest_node(next(iter(graph.nodes.values())).position).node_id in graph.nodes
