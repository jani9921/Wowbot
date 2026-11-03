"""Post-combat travel preparation must not lose the route or outrank loot."""
from types import SimpleNamespace

import pytest

from test_agent_core import agent, state
from test_travel_mode_20261020 import GOAL, long_move, world, favorite_mount, CAPABLE
from test_planning_orchestration import orchestrator, Supervisor
from wowbot.agent.models import Proposal, Observation, Goal
from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.agent.world import WorldModel
from wowbot.agent.autonomy_loop import AutonomousLoop
from wowbot.runtime import Intent


def observed_combat_dismount(policy):
    policy.observe(world(1., mounted=True), 1.)
    policy.observe(world(2., mounted=True, is_in_combat=True), 2.)
    policy.observe(world(3., is_in_combat=True), 3.)
    policy.observe(world(5., is_in_combat=False), 5.)


def test_combat_dismount_does_not_impose_another_twenty_seconds_on_the_next_route():
    policy = TravelModePolicy()
    observed_combat_dismount(policy)
    proposals = policy.apply([long_move()], GOAL, world(5.), 5.)
    assert any(p.skill == "MOUNT" for p in proposals)
    assert policy.dismounted_at == 3.


def test_loot_still_owns_input_before_post_combat_mount():
    policy = TravelModePolicy()
    observed_combat_dismount(policy)
    loot = Proposal.make("LOOT", "own corpse", {}, priority=120.)
    assert not any(p.skill == "MOUNT" for p in policy.apply([long_move(), loot], GOAL, world(5.), 5.))
    assert any(p.skill == "MOUNT" for p in policy.apply([long_move()], GOAL, world(6.), 6.))


@pytest.mark.parametrize("extra", [
    {"is_in_combat": True}, {"is_dead": True}, {"is_ghost": True},
    {"movement": {"indoors": True}}, {"movement": {"falling": True}},
    {"in_vehicle": True}, {"on_taxi": True}, {"is_casting": True},
    {"mount_capability": None}, {"actionbar": [favorite_mount(is_usable=False)]},
])
def test_combat_remount_never_bypasses_the_existing_safety_capability_or_action_gates(extra):
    policy = TravelModePolicy()
    observed_combat_dismount(policy)
    assert not any(p.skill == "MOUNT" for p in policy.apply([long_move()], GOAL, world(6., **extra), 6.))


def test_engine_observes_mount_transitions_while_the_combat_branch_returns_early():
    value, _ = agent("Menj oda", {"destination": {"map_id": 1609, "x": .5, "y": .4}})
    value.tick(state(1., is_mounted=True), 1.)
    value.tick(state(2., is_mounted=True, is_in_combat=True), 2.)
    value.tick(state(3., is_mounted=False, is_in_combat=True), 3.)
    assert value.planner.travel_mode.dismounted_at == 3.


def resume():
    return SimpleNamespace(intent=Intent("MOVE", long_move().parameters), token="resume:quest")


def test_resume_prepares_mount_before_move_and_keeps_supervisor_token():
    supervisor = Supervisor(resume())
    value, planner = orchestrator([Proposal.make("WAIT", "no other work")], supervisor=supervisor)
    planner.travel_mode = TravelModePolicy()
    result = value.choose(GOAL, world(30.), {}, 30., recovery_resume=None, recovery_resume_ready=False)
    assert result.proposal.skill == "MOUNT"
    assert "_resume_token" not in result.proposal.parameters
    assert supervisor.resume.token == "resume:quest"
    after = value.choose(GOAL, world(32., mounted=True), {}, 32., recovery_resume=None, recovery_resume_ready=False)
    assert after.proposal.skill == "MOVE"
    assert after.proposal.parameters["_resume_token"] == "resume:quest"


def test_recovery_resume_is_not_consumed_to_prepare_a_mount():
    value, planner = orchestrator([Proposal.make("WAIT", "no other work")])
    planner.travel_mode = TravelModePolicy()
    retained = long_move()
    result = value.choose(GOAL, world(30.), {}, 30., recovery_resume=retained, recovery_resume_ready=True)
    assert result.proposal.skill == "MOUNT"
    assert result.recovery_resume is retained
    assert result.recovery_resume_ready is True
    assert not any(name == "RECOVERY_RESUME_OFFERED" for name, _ in result.events)


def test_a_location_commitment_cannot_silently_replace_prepared_mount_with_walking():
    wm = WorldModel()
    wm.ingest(Observation.create(state(30., **world(30.).state), 30.))
    loop = AutonomousLoop()
    move = long_move()
    goal = Goal("travel:1", "Menj oda", "MOVE", 1.)
    loop.choose([move], move, goal, wm, 30.)
    commitment = loop.commitment
    mount = TravelModePolicy().apply([move], GOAL, wm, 31.)[-1]
    assert mount.skill == "MOUNT"
    assert loop.choose([mount, move], mount, goal, wm, 31.).skill == "MOUNT"
    assert loop.commitment is commitment


def test_failed_mount_still_allows_the_retained_move_to_resume_on_foot():
    value, planner = orchestrator([Proposal.make("WAIT", "no other work")], supervisor=Supervisor(resume()))
    planner.travel_mode = TravelModePolicy()
    failed = {"skill": "MOUNT", "outcome": "FAILURE", "action_id": "failed:mount"}
    result = value.choose(GOAL, world(30., last_result=failed), {}, 30., recovery_resume=None, recovery_resume_ready=False)
    assert result.proposal.skill == "MOVE"
    assert result.proposal.parameters["_resume_token"] == "resume:quest"


def test_existing_equal_mount_proposal_cannot_make_resume_skip_preparation():
    value, planner = orchestrator(supervisor=Supervisor(resume()))
    planner.travel_mode = TravelModePolicy()
    candidate = Proposal.make("MOVE", "resume", {**long_move().parameters,
                             "_resume_token": "resume:quest"}, confidence=1., priority=101)
    planner.proposals = planner.travel_mode.apply([candidate], GOAL, world(30.), 30.)
    result = value.choose(GOAL, world(30.), {}, 30., recovery_resume=None, recovery_resume_ready=False)
    assert result.proposal.skill == "MOUNT"


def test_blocked_mount_preparation_does_not_discard_the_valid_route():
    value, planner = orchestrator(supervisor=Supervisor(resume()))
    planner.travel_mode = TravelModePolicy()
    mount = planner.travel_mode.apply([long_move()], GOAL, world(30.), 30.)[-1]
    planner.blocked_until[mount.key] = 60.
    result = value.choose(GOAL, world(30.), {}, 30., recovery_resume=None, recovery_resume_ready=False)
    assert result.proposal.skill == "MOVE"
    assert result.proposal.parameters["_resume_token"] == "resume:quest"


def test_recovery_waits_for_local_loot_before_mounting_or_consuming_the_route():
    loot = Proposal.make("LOOT", "corpse", {}, priority=120.)
    value, planner = orchestrator([loot])
    planner.travel_mode = TravelModePolicy()
    retained = long_move()
    result = value.choose(GOAL, world(30.), {}, 30., recovery_resume=retained, recovery_resume_ready=True)
    assert result.proposal is loot
    assert result.recovery_resume is retained and result.recovery_resume_ready


def test_a_short_resume_route_does_not_summon_a_mount():
    retained = Proposal.make("MOVE", "near", {**long_move().parameters, "x": 20.})
    value, planner = orchestrator()
    planner.travel_mode = TravelModePolicy()
    result = value.choose(GOAL, world(30.), {}, 30., recovery_resume=retained, recovery_resume_ready=True)
    assert result.proposal.skill == "MOVE"


def test_unknown_mount_state_does_not_count_as_a_dismount_transition():
    policy = TravelModePolicy()
    policy.observe(world(1., mounted=True), 1.)
    unknown = world(2.)
    unknown.state.pop("is_mounted")
    policy.observe(unknown, 2.)
    assert policy.dismounted_at is None


def test_full_agent_rechecks_mount_then_consumes_resume_only_when_move_starts():
    """RecordingExecutor only: no live combat, client input or quest credit."""
    bot, executor = agent("Menj oda", {"destination": {"map_id": 1609, "x": .5, "y": .1}})
    def tick(t, mounted, combat):
        return bot.tick(state(t, is_mounted=mounted, is_in_combat=combat,
                              mount_capability=CAPABLE, actionbar=[favorite_mount()]), t)
    tick(1., True, False)
    assert bot.pending.proposal.skill == "MOVE"
    tick(2., True, True)
    tick(3., False, True)
    token = bot.supervisor.snapshot()["suspended"]["token"]
    tick(4., False, False)
    assert bot.pending.proposal.skill == "MOUNT"
    assert executor.commands[-1].binding == "ACTIONBUTTON12"
    assert bot.supervisor.snapshot()["suspended"]["token"] == token
    tick(5., True, False)
    assert bot.last_result["skill"] == "MOUNT" and bot.last_result["outcome"] == "SUCCESS"
    assert bot.pending.proposal.skill == "MOVE"
    assert bot.pending.proposal.parameters["_resume_token"] == token
    assert bot.supervisor.snapshot()["suspended"] is None
