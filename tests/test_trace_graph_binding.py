from wowbot.navigation.path_geometry import PathGeometry, PathVertex
from wowbot.navigation.trace_graph_binding import SeedEdge, bind_geometry_to_seed_edges


def test_recorded_geometry_binds_only_matching_seed_edges_and_keeps_partial_scope():
    geom = PathGeometry("map:1409", None, (
        PathVertex(0.0, 0.0, 0),
        PathVertex(0.05, 0.0, 1),
        PathVertex(0.10, 0.0, 2),
    ), 0.10)
    edges = (
        SeedEdge("a:b", "a", "b", (0.0, 0.0), (0.10, 0.0)),
        SeedEdge("c:d", "c", "d", (0.0, 0.20), (0.10, 0.20)),
    )
    out = bind_geometry_to_seed_edges(geom, edges, max_distance=0.03)
    assert out["coverage_scope"] == "partial_route_only"
    assert out["seed_graph_authoritative"] is True
    assert [e["edge_id"] for e in out["bound_edges"]] == ["a:b"]
    assert out["unmatched_seed_edges"] == ["c:d"]


def test_topology_transition_is_reported_not_repaired():
    geom = PathGeometry("map:1409", None, (
        PathVertex(0.0, 0.0, 0),
        PathVertex(1.0, 0.0, 1),
    ), 1.0)
    edges = (
        SeedEdge("a:b", "a", "b", (0.0, 0.0), (0.5, 0.0)),
        SeedEdge("x:y", "x", "y", (0.5, 0.0), (1.0, 0.0)),
    )
    out = bind_geometry_to_seed_edges(geom, edges, max_distance=0.6)
    assert out["bound_edges"] == []
    assert len(out["single_vertex_candidates"]) == 2


def test_single_vertex_match_is_not_promoted_to_route_edge():
    geom = PathGeometry("map:1409", None, (
        PathVertex(0.0, 0.0, 0),
        PathVertex(0.5, 0.0, 1),
    ), 0.5)
    edges = (
        SeedEdge("a:b", "a", "b", (0.0, 0.0), (1.0, 0.0)),
        SeedEdge("side", "s", "t", (0.5, 0.0), (0.5, 0.1)),
    )
    out = bind_geometry_to_seed_edges(geom, edges, max_distance=0.02)
    assert [e["edge_id"] for e in out["bound_edges"]] == ["a:b"]
