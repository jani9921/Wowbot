from wowbot.navigation.engine import NavigationEngine
from wowbot.navigation.graph import NavGraph, NavGraphNode
from wowbot.navigation.memory import NavigationMemory
from wowbot.navigation.models import ArrivalCondition, DestinationIntent, DestinationKind, NavigationStatus
from wowbot.vision.models import NavigationVisionObservation, WorldPosition


def graph() -> NavGraph:
    g = NavGraph()
    g.add_node(NavGraphNode('A', WorldPosition(0, 0)))
    g.add_node(NavGraphNode('B', WorldPosition(1, 0)))
    g.add_node(NavGraphNode('C', WorldPosition(2, 0)))
    g.add_edge_from_nodes('ab', 'A', 'B')
    g.add_edge_from_nodes('bc', 'B', 'C')
    return g


def test_engine_starts_and_arrives(tmp_path):
    memory = NavigationMemory(tmp_path / 'nav.db')
    engine = NavigationEngine(graph=graph(), memory=memory)
    destination = DestinationIntent(DestinationKind.POINT, WorldPosition(2, 0), 'test', ArrivalCondition('POINT', 0.05))
    plan = engine.start(destination, WorldPosition(0, 0))
    obs = NavigationVisionObservation(addon_facts={})
    engine.tick(position=WorldPosition(0, 0), observation=obs, now=0)
    engine.tick(position=WorldPosition(1, 0), observation=obs, now=1)
    result = engine.tick(position=WorldPosition(2, 0), observation=obs, now=2)
    assert result.status == NavigationStatus.ARRIVED
    assert memory.get_experience(engine.route_id).successes == 1
    assert plan.route_node_ids == ['A', 'B', 'C']
