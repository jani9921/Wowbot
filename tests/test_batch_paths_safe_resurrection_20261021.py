"""Spawn choice by walking length; resurrect away from the killers (user 2026-10-20).

"Csináld meg mind", after PixelBuddy's FindPathBatch (first reachable of
several spawns) and PlanResurrection (safe spot near the corpse).
"""
import math
from types import SimpleNamespace

import pytest

from wowbot.agent import tdb_locations
from wowbot.agent.death_recovery_planning import DeathRecoveryPolicy
from wowbot.navigation import NavigationService

STATE = {"player_world_position": {"x": 0., "y": 0., "z": 10., "instance_id": 1,
                                   "coordinate_space": "WORLD_YARDS"}}


def spot(x, y, name):
    return {"x": x, "y": y, "z": 10., "z_known": True, "name": name}


def test_the_spawn_with_the_shortest_walk_wins_over_the_straight_line_nearest():
    across_the_river = spot(20., 0., "near but 300 yd around")
    walkable = spot(60., 0., "farther but straight")
    walks = {"near but 300 yd around": 300., "farther but straight": 62.}
    cost = lambda state, row: walks[row["name"]]
    assert tdb_locations._nearest(STATE, [across_the_river, walkable], travel_cost=cost) is walkable


def test_an_unreachable_spawn_loses_and_without_any_path_the_nearest_stays():
    unreachable, reachable = spot(10., 0., "a"), spot(80., 0., "b")
    cost = lambda state, row: None if row["name"] == "a" else 85.
    assert tdb_locations._nearest(STATE, [unreachable, reachable], travel_cost=cost) is reachable
    assert tdb_locations._nearest(STATE, [unreachable, reachable], travel_cost=lambda *a: None) is unreachable
    assert tdb_locations._nearest(STATE, [reachable, unreachable]) is unreachable


def test_walk_cost_is_the_navmesh_path_length_and_none_without_a_path():
    class Mesh:
        calls = 0

        def find_path(self, instance_id, start, end):
            Mesh.calls += 1
            if end["x"] > 100:
                return None
            return SimpleNamespace(anchors=({"x": 0., "y": 0., "z": 10.}, {"x": end["x"], "y": 0., "z": 10.}),
                                   cost=end["x"] * 1.2)

    nav = NavigationService(navmesh=Mesh())
    assert nav.walk_cost(STATE, {"x": 50., "y": 0., "z": 10., "instance_id": 1}) == pytest.approx(60.)
    assert nav.walk_cost(STATE, {"x": 50., "y": 0., "z": 10., "instance_id": 1}) == pytest.approx(60.)
    assert Mesh.calls == 1                                         # cached
    assert nav.walk_cost(STATE, {"x": 150., "y": 0., "instance_id": 1}) is None
    assert nav.walk_cost(STATE, {"x": 50., "y": 0., "instance_id": 2}) is None   # another map


GHOST = {"is_ghost": True, "is_dead": False,
         "player_world_position": {"x": -80., "y": 0., "z": 0., "instance_id": 1,
                                   "coordinate_space": "WORLD_YARDS"},
         "death_recovery": {"corpse": {"x": 0., "y": 0., "z": 0., "instance_id": 1,
                                       "coordinate_space": "WORLD_YARDS"},
                            "popup": "RECOVER_CORPSE", "x": .5, "y": .6, "recovery_delay": 0}}
KILLERS = [{"x": 5., "y": 3.}, {"x": 8., "y": -2.}]


def test_with_the_killers_at_the_corpse_the_ghost_walks_to_a_safe_spot_first():
    policy = DeathRecoveryPolicy()
    (move,) = policy.propose(GHOST, 1., hostile_units=lambda state, corpse: KILLERS)
    assert move.skill == "MOVE" and move.parameters["safe_resurrection_spot"] is True
    x, y = move.parameters["x"], move.parameters["y"]
    assert math.hypot(x, y) <= DeathRecoveryPolicy.RECLAIM_YARDS                  # still in corpse range
    assert min(math.hypot(x-k["x"], y-k["y"]) for k in KILLERS) >= 20.
    arrived = {**GHOST, "player_world_position": {**GHOST["player_world_position"], "x": x, "y": y}}
    (click,) = policy.propose(arrived, 2., hostile_units=lambda state, corpse: KILLERS)
    assert click.skill == "DEATH_RECOVERY" and click.parameters["action"] == "RECOVER_CORPSE"


def test_an_unreachable_spot_is_skipped_and_no_killers_means_the_old_way():
    policy = DeathRecoveryPolicy()
    reachable = lambda state, point: None if point["x"] < -10 else 40.
    (move,) = policy.propose(GHOST, 1., hostile_units=lambda state, corpse: KILLERS, walk_cost=reachable)
    assert move.parameters["x"] >= -10
    (click,) = DeathRecoveryPolicy().propose(GHOST, 1., hostile_units=lambda state, corpse: [])
    assert click.skill == "DEATH_RECOVERY"
