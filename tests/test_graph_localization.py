from wowbot.navigation.exile_reach_seed import build_exile_reach_seed_graph
from wowbot.navigation.graph_localization import GraphLocalizer
from wowbot.vision.models import WorldPosition


def test_nearest_node_and_edge_are_reported():
    graph = build_exile_reach_seed_graph()
    loc = GraphLocalizer(graph).locate(WorldPosition(0.619, 0.843, 0))
    assert loc.nearest_node_id == "exile:player_start"
    assert loc.nearest_node_distance == 0.0
    assert loc.nearest_edge_id is not None
    assert loc.confidence > 0.8


def test_location_can_be_on_edge_without_being_at_node():
    graph = build_exile_reach_seed_graph()
    a = graph.nodes["exile:player_start"].position
    b = graph.nodes["exile:murloc_hideaway"].position
    p = WorldPosition((a.x + b.x) / 2, (a.y + b.y) / 2, 0)
    loc = GraphLocalizer(graph).locate(p)
    assert loc.nearest_edge_id in {"seed:player_start:murloc_hideaway", "seed:player_start:murloc_hideaway:reverse"}
    assert loc.nearest_edge_distance < 1e-9
    assert 0.45 < (loc.edge_progress or 0.0) < 0.55
