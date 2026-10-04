"""Death recovery (user 2026-10-03: release spirit, run back, resurrect).

Live 2026-10-03 13:59 a Coastal Goat killed the character; the agent could
only stop (MANUAL).  Addon 0.9.45 exports the death popup button and the
corpse position; the planner then proposes only these steps.
"""
from types import SimpleNamespace

from wowbot.agent.death_recovery_planning import DeathRecoveryPolicy
from wowbot.agent.models import Attempt, Outcome, Prediction, Proposal
from wowbot.agent.skills import SkillRegistry

CORPSE = {"x": .58, "y": .74, "map_id": 1409, "coordinate_space": "NORMALIZED_MAP",
          "world_position": {"x": -240., "y": -2490., "instance_id": 2175,
                             "coordinate_space": "WORLD_YARDS", "ui_map_id": 1409}}


def _state(**extra):
    return {"is_dead": True, "is_ghost": False, "monotonic_time": 10.,
            "player_world_position": {"x": -100., "y": -2400., "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "death_recovery": {"popup": "RELEASE_SPIRIT", "x": .5, "y": .8, "enabled": True,
                               "corpse": CORPSE, "recovery_delay": 0}, **extra}


def test_dead_releases_the_spirit_once_per_interval():
    policy = DeathRecoveryPolicy()
    first = policy.propose(_state(), 10.)
    assert [(p.skill, p.parameters["action"]) for p in first] == [("DEATH_RECOVERY", "RELEASE_SPIRIT")]
    policy.note_dispatched(first[0], 10.)
    assert policy.propose(_state(), 11.)[0].skill == "WAIT"
    assert policy.propose(_state(), 13.5)[0].skill == "DEATH_RECOVERY"


def test_ghost_runs_to_the_corpse_then_resurrects():
    policy = DeathRecoveryPolicy()
    ghost = _state(is_dead=False, is_ghost=True,
                   death_recovery={"popup": "", "corpse": CORPSE, "recovery_delay": 0})
    move = policy.propose(ghost, 20.)[0]
    assert move.skill == "MOVE" and move.parameters["purpose"] == "CORPSE_RUN"
    assert (move.parameters["x"], move.parameters["y"]) == (-240., -2490.)
    near = {**ghost, "death_recovery": {"popup": "RECOVER_CORPSE", "x": .5, "y": .6,
                                        "enabled": True, "corpse": CORPSE, "recovery_delay": 0}}
    assert policy.propose(near, 30.)[0].parameters["action"] == "RECOVER_CORPSE"
    # Still in the corpse-retrieval delay: keep running/waiting, no click.
    delayed = {**near, "death_recovery": {**near["death_recovery"], "recovery_delay": 12}}
    assert all(p.skill != "DEATH_RECOVERY" for p in policy.propose(delayed, 30.))


def test_alive_proposes_nothing_and_unknown_popups_are_never_clicked():
    policy = DeathRecoveryPolicy()
    assert policy.propose({"is_dead": False, "is_ghost": False}, 1.) == []
    other = _state(death_recovery={"popup": "", "x": .5, "y": .8})
    assert policy.propose(other, 1.)[0].skill == "WAIT"


def test_registry_clicks_the_exported_point_and_verifies_the_state_change():
    registry = SkillRegistry()
    proposal = Proposal.make("DEATH_RECOVERY", "t", {"action": "RELEASE_SPIRIT", "x": .5, "y": .8})
    commands = registry.commands(proposal, SimpleNamespace(state={}))
    assert [(c.kind, c.x, c.y) for c in commands] == [("CLICK", .5, .8)]
    assert "DEATH_RECOVERY" in registry.contracts


def test_planner_offers_only_death_steps_while_dead():
    from wowbot.agent.planner import Planner
    from wowbot.agent.models import Goal
    planner = Planner(SkillRegistry())
    world = SimpleNamespace(state=_state())
    proposals = planner.candidates(Goal.parse("Questelj", 0.), world, 10.)
    assert [p.skill for p in proposals] == ["DEATH_RECOVERY"]


def test_agent_stays_in_full_ai_and_clicks_release_spirit_when_dead():
    from test_agent_core import agent, state
    value, executor = agent()
    value.tick(state(1.), 1.)
    dead = state(2., is_dead=True, health=0,
                 death_recovery={"popup": "RELEASE_SPIRIT", "x": .5, "y": .8, "enabled": True,
                                 "corpse": None, "recovery_delay": 0})
    result = None
    for t in (2., 2.6, 3.2, 3.8):
        result = value.tick({**dead, "timestamp": t, "monotonic_time": t, "frame_id": f"d:{t}"}, t)
    assert result["mode"] == "FULL_AI"
    clicks = [c for c in executor.commands if c.kind == "CLICK"]
    assert clicks and (clicks[0].x, clicks[0].y) == (.5, .8)


def test_without_the_addon_export_death_still_stops_safely():
    from test_agent_core import agent, state
    value, _ = agent()
    value.tick(state(1.), 1.)
    result = value.tick(state(2., is_dead=True, health=0), 2.)
    assert result["mode"] == "MANUAL"          # old addon: the safe stop at once


def test_new_addon_gets_a_short_grace_for_the_slow_death_export():
    from test_agent_core import agent, state
    value, _ = agent()
    value.tick(state(1., addon_version="0.9.45"), 1.)
    early = value.tick(state(2., is_dead=True, health=0, addon_version="0.9.45"), 2.)
    assert early["mode"] == "FULL_AI"
    late = value.tick(state(12.5, is_dead=True, health=0, addon_version="0.9.45"), 12.5)
    assert late["mode"] == "MANUAL"


def test_agent_runs_to_the_corpse_as_a_ghost():
    from test_agent_core import agent, state
    value, executor = agent()
    value.tick(state(1., map_id=1409), 1.)
    ghost = state(2., is_dead=False, is_ghost=True, map_id=1409,
                  player_world_position={"x": -100., "y": -2400., "instance_id": 2175,
                                         "coordinate_space": "WORLD_YARDS"},
                  death_recovery={"popup": "", "corpse": CORPSE, "recovery_delay": 0})
    decisions = []
    for t in (2., 2.5, 3., 3.5):
        result = value.tick({**ghost, "timestamp": t, "monotonic_time": t, "frame_id": f"g:{t}"}, t)
        assert result["mode"] == "FULL_AI"
        decisions.append((result["decision"]["skill"],
                          (result["decision"].get("parameters") or {}).get("purpose")))
    # (Offline there is no navmesh, so the MOVE itself fails and is retried.)
    assert ("MOVE", "CORPSE_RUN") in decisions
    assert not any(skill in {"COMBAT", "TARGET", "LOOT", "INTERACT"} for skill, _ in decisions)
