"""A ghost on a flying mount hovering over its corpse (live 2026-10-21).

11:29:39 the ghost sat on a flying (ghost) mount about 40 yd above the corpse
(x 3513.45, y -1682.62, z 63.66; corpse 32 yd away).  No navmesh route starts
in the air; the navmesh-only corpse run failed ``required_navmesh_route_
unavailable`` 4300 times until 12:00.  User: "egy sárkányon ült ... a föld
felett lebegett, nem ment semerre".
"""
from types import SimpleNamespace

from wowbot.agent.death_recovery_planning import DeathRecoveryPolicy
from wowbot.agent.engine_finish import EngineFinishMixin
from wowbot.agent.models import Proposal

CORPSE = {"x": 3482.55, "y": -1691.87, "z_known": False, "instance_id": 2444,
          "coordinate_space": "WORLD_YARDS"}


def ghost(z=63.66, *, mounted=True, flying=None):
    return {"is_ghost": True, "is_dead": False, "is_mounted": mounted,
            "movement": {} if flying is None else {"flying": flying},
            "player_world_position": {"x": 3513.45, "y": -1682.62, "z": z, "z_observed": True,
                                      "instance_id": 2444, "coordinate_space": "WORLD_YARDS"},
            "death_recovery": {"corpse": CORPSE, "popup": "", "recovery_delay": 0}}


def test_a_hovering_ghost_requests_the_common_route_and_landing():
    policy = DeathRecoveryPolicy()
    (step,) = policy.propose(ghost(), 1., walk_cost=lambda state, point: None)
    assert step.skill == "MOVE" and step.parameters["require_navmesh"] is True
    assert step.parameters["purpose"] == "CORPSE_RUN"
    (step,) = policy.propose(ghost(58.), 2., walk_cost=lambda state, point: None)
    assert step.skill == "MOVE" and step.parameters["require_navmesh"] is True
    # On the ground a route exists: the ordinary navmesh corpse run.
    (move,) = policy.propose(ghost(25.), 3., walk_cost=lambda state, point: 35.)
    assert move.skill == "MOVE" and move.parameters["require_navmesh"] is True


def test_no_route_never_authorizes_straight_movement_to_the_corpse():
    policy = DeathRecoveryPolicy()
    for at in range(4):                                 # z does not change
        (step,) = policy.propose(ghost(), float(at), walk_cost=lambda state, point: None)
    assert step.skill == "MOVE" and step.parameters["require_navmesh"] is True
    assert (step.parameters["x"], step.parameters["y"]) == (CORPSE["x"], CORPSE["y"])
    # Never airborne and still no route: straight there as well, no descent.
    (move,) = DeathRecoveryPolicy().propose(ghost(mounted=False), 1., walk_cost=lambda state, point: None)
    assert move.skill == "MOVE" and move.parameters["require_navmesh"] is True


def test_flying_is_read_from_the_movement_flag_as_well():
    assert DeathRecoveryPolicy.airborne(ghost(mounted=False, flying=True))
    assert not DeathRecoveryPolicy.airborne(ghost(mounted=False, flying=False))
    alive_mounted = {**ghost(), "is_ghost": False}
    assert not DeathRecoveryPolicy.airborne(alive_mounted)


def test_descend_presses_sit_move_down_and_counts_a_lower_z_as_success():
    from wowbot.agent.models import Observation, Outcome
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    from test_agent_core import state
    registry = SkillRegistry()
    step = Proposal.make("RECOVER", "descend", {"recovery_step": "DESCEND", "purpose": "CORPSE_RUN"})
    assert [c.binding for c in registry.commands(step, WorldModel())] == ["SITORSTAND"] * 3

    def verify(z_after):
        air = {key: ghost()[key] for key in ("is_ghost", "is_dead", "is_mounted")}
        baseline = state(1., **air, player_world_position=ghost()["player_world_position"])
        world = WorldModel()
        world.ingest(Observation.create(state(2., **air, player_world_position=ghost(z_after)[
            "player_world_position"]), 2.))
        attempt = SimpleNamespace(observation_id="baseline", deadline=8., started_at=1., baseline=baseline,
                                  proposal=step, commands=())
        return registry.verify(attempt, world, 2.)[0]
    assert verify(55.) == Outcome.SUCCESS
    assert verify(63.66) != Outcome.SUCCESS


class Agent(EngineFinishMixin):
    pass


def test_a_confirmed_loop_that_lasts_three_minutes_stops_full_ai():
    agent = Agent()
    decision = SimpleNamespace(signature="ACTION:MOVE:proposal=0d52e2b5f3948579:INTERNAL_ERROR", count=42)
    for at in range(0, 180, 5):
        agent._note_persistent_loop(decision, "MOVE", float(at))
    assert "safety_stop" not in agent.__dict__
    agent._note_persistent_loop(decision, "MOVE", 180.)
    stop = agent.__dict__["safety_stop"]
    assert stop["reason"] == "persistent_loop_stopped" and stop["skill"] == "MOVE"
    # A pause longer than 30 s starts the clock again.
    fresh = Agent()
    fresh._note_persistent_loop(decision, "MOVE", 0.)
    fresh._note_persistent_loop(decision, "MOVE", 100.)
    fresh._note_persistent_loop(decision, "MOVE", 200.)
    assert "safety_stop" not in fresh.__dict__


def test_walk_cost_is_cached_per_start_height():
    from wowbot.navigation import NavigationService

    class Mesh:
        def find_path(self, instance_id, start, end):
            # Live map 2444: no route from 63.66 (in the air), 59 yd from below 40.
            return None if start["z"] > 50 else SimpleNamespace(cost=58.8, anchors=(start, end))
    nav = NavigationService(None)
    nav._navmesh = Mesh()
    assert nav.walk_cost(ghost(), CORPSE) is None
    assert nav.walk_cost(ghost(30.), CORPSE) == 58.8


def test_a_flying_ghost_far_from_its_corpse_still_requests_a_route():
    """Live 2026-10-26 16:39: z 336, the corpse 430 yd away; the navmesh
    corpse run failed (no route starts in the air) and the agent waited."""
    far = ghost(336., flying=True)
    far["player_world_position"] = {**far["player_world_position"], "x": 3913.45}
    (move,) = DeathRecoveryPolicy().propose(far, 1., walk_cost=lambda state, point: 500.)
    assert move.skill == "MOVE" and move.parameters["require_navmesh"] is True
    assert move.parameters["purpose"] == "CORPSE_RUN"
