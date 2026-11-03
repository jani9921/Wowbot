"""Design spec 31: combat-aware route choice.

31.2: a single mob keeps the straight route, but a corridor through several
ordinary hostiles already tries a navmesh detour (kept only when cheaper with
the danger counted).  Elites/rares/packs and a character low on health cost
more fight seconds.  31.3: a flight landing on an unknown floor carries risk.
31.4: the character's own won fights price the exposure."""
import math
from types import SimpleNamespace

from wowbot.agent.fight_statistics import expected_fight_seconds, record_fight
from wowbot.navigation.danger import DangerMap
from wowbot.navigation.route_score import RouteRiskEvaluator, character_fight_factor
from test_spawn_threats_20261021 import plan


def hostiles(*xs, kind="HOSTILE_SPAWN"):
    danger = DangerMap()
    for index, x in enumerate(xs):
        danger.add(danger_id=f"d{index}", kind=kind, x=x, y=0., radius=15., cost=8., confidence=.8,
                   now=0., ttl=600., source="TDB_SPAWN", entity_id=f"npc:{index}", z=0.)
    return danger


def test_a_corridor_through_two_ordinary_mobs_is_detoured_one_is_not():
    assert len(plan(hostiles(100.)).anchors) == 2
    route = plan(hostiles(70., 130.))
    assert route.regions[0]["danger_adapted"] is True
    assert min(math.hypot(p["x"]-70., p["y"]) for p in route.anchors) >= 15.
    assert len(plan(hostiles(70., 130.), allow_combat=True).anchors) == 2


def route(*points, flight=False):
    return SimpleNamespace(route_id="r", anchors=tuple({"x": x, "y": 0., "z": 0.} for x in points),
                           regions=({"route_source": "FLIGHT_PLAN"},) if flight else (), confidence=.9)


def request(**destination):
    return SimpleNamespace(destination={"x": 200., "y": 0., **destination}, target_entity_id=None)


def test_elites_and_low_health_cost_more_fight_seconds():
    evaluator = RouteRiskEvaluator()
    healthy = {"player_world_position": {"instance_id": None}, "health": 100, "max_health": 100}
    normal = evaluator.evaluate(route(0., 200.), request(), healthy, 1., danger_map=hostiles(100.))
    elite = evaluator.evaluate(route(0., 200.), request(), healthy, 1., danger_map=hostiles(100., kind="ELITE_SPAWN"))
    weak = evaluator.evaluate(route(0., 200.), request(), {**healthy, "health": 20}, 1., danger_map=hostiles(100.))
    assert elite.combat_seconds == normal.combat_seconds*3 and elite.failure_probability > normal.failure_probability
    assert weak.combat_seconds > normal.combat_seconds and character_fight_factor({"health": 20, "max_health": 100}) == 1.6


def test_a_flight_to_an_unknown_floor_carries_landing_risk():
    evaluator = RouteRiskEvaluator()
    known = evaluator.evaluate(route(0., 200., flight=True), request(z_known=True), {}, 1.)
    unknown = evaluator.evaluate(route(0., 200., flight=True), request(), {}, 1.)
    assert unknown.uncertainty_seconds > known.uncertainty_seconds
    assert "landing_floor_unknown" in unknown.assumptions


def test_the_characters_own_won_fights_price_the_exposure():
    world = SimpleNamespace()
    for seconds in (6., 9., 7.):
        record_fight(world, seconds)
    assert expected_fight_seconds(world) == 7.
    evaluator = RouteRiskEvaluator()
    quick = {"character_profile": {"expected_fight_seconds": 7.}, "player_world_position": {"instance_id": None}}
    slow = {"character_profile": {"expected_fight_seconds": 35.}, "player_world_position": {"instance_id": None}}
    assert (evaluator.evaluate(route(0., 200.), request(), quick, 1., danger_map=hostiles(100.)).combat_seconds
            < evaluator.evaluate(route(0., 200.), request(), slow, 1., danger_map=hostiles(100.)).combat_seconds)
