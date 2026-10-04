from __future__ import annotations

from wowbot.vision.models import WorldPosition
from .graph import NavGraph, NavGraphNode

# First calibrated exemplar only. Coordinates are normalized map-space (0..1),
# based on the supplied Exile's Reach World Map. These are seed hypotheses,
# not claims about the whole zone's topology.
SEED_NODES: tuple[tuple[str, str, float, float], ...] = (
    ("player_start", "START", 0.619, 0.843),
    ("murloc_hideaway", "POI", 0.585, 0.815),
    ("abandoned_camp", "JUNCTION", 0.548, 0.698),
    ("central_crossing", "JUNCTION", 0.516, 0.552),
    ("darkmaul_plains", "POI", 0.505, 0.620),
    ("darkmaul_citadel", "POI", 0.446, 0.350),
    ("citadel_west_junction", "JUNCTION", 0.365, 0.360),
    ("north_central_junction", "JUNCTION", 0.505, 0.245),
    ("harpy_roost", "POI", 0.595, 0.405),
    ("quilboar_briarpatch", "POI", 0.655, 0.675),
    ("southern_road_junction", "JUNCTION", 0.560, 0.755),
)

SEED_EDGES: tuple[tuple[str, str], ...] = (
    ("player_start", "murloc_hideaway"),
    ("murloc_hideaway", "abandoned_camp"),
    ("abandoned_camp", "central_crossing"),
    ("central_crossing", "darkmaul_plains"),
    ("darkmaul_plains", "southern_road_junction"),
    ("southern_road_junction", "quilboar_briarpatch"),
    ("central_crossing", "darkmaul_citadel"),
    ("darkmaul_citadel", "citadel_west_junction"),
    ("darkmaul_citadel", "north_central_junction"),
    ("central_crossing", "harpy_roost"),
    ("central_crossing", "quilboar_briarpatch"),
)


def build_exile_reach_seed_graph() -> NavGraph:
    graph = NavGraph()
    for node_id, node_type, x, y in SEED_NODES:
        graph.add_node(
            NavGraphNode(
                node_id=f"exile:{node_id}",
                position=WorldPosition(x, y, 0.0),
                node_type=node_type,
                confidence=0.68,
            )
        )
    for a, b in SEED_EDGES:
        graph.add_edge_from_nodes(f"seed:{a}:{b}", f"exile:{a}", f"exile:{b}", confidence=0.62)
    return graph
