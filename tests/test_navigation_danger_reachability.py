from wowbot.navigation.danger import DangerMap
from wowbot.navigation.reachability import ReachabilityModel


def test_danger_map_is_expiring_and_respects_intended_hostile_exemption():
    danger = DangerMap()
    danger.add(danger_id="hostile:a", kind="HOSTILE_AGGRO", x=10., y=10., radius=8., cost=8.,
               confidence=1., now=1., ttl=2., source="TEST", entity_id="a")
    assert not danger.permits(10., 10., 1.5, avoid_combat=True, allow_combat=False)
    assert danger.permits(10., 10., 1.5, avoid_combat=True, allow_combat=False, exempt_entity_id="a")
    assert danger.permits(10., 10., 3.1, avoid_combat=True, allow_combat=False)


def test_reachability_cools_only_after_repeated_entity_failures_and_success_clears_it():
    model = ReachabilityModel()
    for _ in range(3):
        model.report_failure("npc", "LINE_OF_SIGHT", 2.)
    assert not model.permits("npc", 3.)
    model.report_success("npc", 3.)
    assert model.permits("npc", 3.)
