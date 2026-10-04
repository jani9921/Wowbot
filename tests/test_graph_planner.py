from wowbot.navigation.graph import NavGraph, NavGraphNode
from wowbot.navigation.planner import RoutePlanner
from wowbot.vision.models import WorldPosition


def test_planner_prefers_lower_cost_route():
    graph = NavGraph()
    for node_id, xy in {"A": (0, 0), "B": (1, 0), "C": (0, 1), "D": (2, 0)}.items():
        graph.add_node(NavGraphNode(node_id, WorldPosition(*xy)))
    graph.add_edge_from_nodes("ab", "A", "B", estimated_time=1, risk=0.0)
    graph.add_edge_from_nodes("bd", "B", "D", estimated_time=1, risk=0.0)
    graph.add_edge_from_nodes("ac", "A", "C", estimated_time=4, risk=0.0)
    graph.add_edge_from_nodes("cd", "C", "D", estimated_time=4, risk=0.0)

    route = RoutePlanner(graph).plan(WorldPosition(0, 0), WorldPosition(2, 0))

    assert route.node_ids == ("A", "B", "D")


def test_planner_reports_disconnected_graph():
    graph = NavGraph()
    graph.add_node(NavGraphNode("A", WorldPosition(0, 0)))
    graph.add_node(NavGraphNode("B", WorldPosition(10, 0)))
    try:
        RoutePlanner(graph).plan(WorldPosition(0, 0), WorldPosition(10, 0))
    except Exception as exc:
        assert exc.__class__.__name__ == "NoRouteError"
    else:
        raise AssertionError("expected NoRouteError")
