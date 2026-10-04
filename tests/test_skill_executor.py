from types import SimpleNamespace

from wowbot.agent.models import Command, Proposal
from wowbot.agent.skills import SkillRegistry
from wowbot.runtime import (ActiveSkillRuntime, SkillExecutor, SkillResult,
                            SkillStatus)


class Navigation:
    max_reach_seconds = 9.
    def __init__(self): self.started = None
    def start_skill_request(self, *args): self.started = args
    def command(self, *args): return (Command("BIND", "MOVEFORWARD"),)


class Registry:
    contracts = {"WAIT": SimpleNamespace(
        expected="waited", success_condition="time_elapsed", recovery="replan",
        timeout=2.),
        "TARGET": SimpleNamespace(
            expected="target selected", success_condition="target_changed",
            recovery="replan", timeout=2.)}
    def commands(self, proposal, world): return (Command("BIND", "JUMP"),)


class Direct:
    def commands_for(self, intent): return (Command("BIND", "INTERACTTARGET"),)


class M0:
    def handles(self, skill): return skill == "TARGET"
    def begin(self, active, state, now):
        return SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "TARGETNEARESTENEMY"),))


class Search:
    max_seconds = 4.
    def begin(self, *args): return SkillResult(SkillStatus.RUNNING)


def executor():
    return SkillExecutor(
        registry=Registry(), navigation=Navigation(), target_skill=Direct(),
        interact_skill=Direct(), m0_skills=M0(), search_skill=Search(),
        visual_approach_skill=Search())


def test_movement_preparation_delegates_to_navigation_without_dispatching():
    value = executor()
    world = SimpleNamespace(state={})
    prepared = value.prepare(Proposal.make("MOVE", "go", {"x": .5, "y": .5}),
                             world, "obs", 1.)
    assert prepared.set_segment_baseline is True
    assert prepared.commands[0].binding == "MOVEFORWARD"
    assert value.navigation.started is not None


def test_deferred_skill_can_start_without_preflight_command():
    prepared = executor().prepare(
        Proposal.make("LOOT", "corpse"), SimpleNamespace(state={}), "obs", 1.)
    assert prepared.commands == ()
    assert SkillExecutor.allows_empty_start("LOOT") is True


def test_active_begin_routes_to_domain_skill_and_returns_typed_result():
    active = SimpleNamespace(skill_type="TARGET")
    result = executor().begin(active, {}, "visual:1", 1., ())
    assert result.status is SkillStatus.RUNNING
    assert result.commands[0].binding == "TARGETNEARESTENEMY"


def test_camera_request_is_data_not_a_camera_or_input_side_effect():
    prepared = executor().prepare(
        Proposal.make("REACQUIRE_TARGET", "look", {"degrees": 20}),
        SimpleNamespace(state={}), "obs", 1.)
    assert prepared.camera_parameters["camera_action"] == "REACQUIRE_TRACK"


def test_attempt_uses_canonical_world_baseline_and_typed_verification_window():
    value = executor()
    world = SimpleNamespace(
        state={"inventory": {"item:1": 2}},
        latest=SimpleNamespace(observation_id="obs:1"))
    timeouts = SimpleNamespace(resolve=lambda skill, base, state: base)
    attempt = value.create_attempt(
        Proposal.make("WAIT", "bounded"), (), world=world,
        goal=SimpleNamespace(domain="quest"),
        current_plan=SimpleNamespace(plan_id="plan:1"),
        timeouts=timeouts, memory=None, now=10.)
    world.state["inventory"]["item:1"] = 3
    assert attempt.baseline["inventory"]["item:1"] == 2
    assert attempt.deadline == 12.
    assert attempt.prediction.expected == "waited"


def test_install_attempt_uses_supplied_single_active_skill_authority():
    value = executor()
    active = ActiveSkillRuntime()
    world = SimpleNamespace(
        state={"target": None},
        latest=SimpleNamespace(observation_id="obs:1"))
    timeouts = SimpleNamespace(resolve=lambda skill, base, state: base)
    proposal = Proposal.make(
        "TARGET", "select", {"guid": "Creature-0-0-0-0-42-0000000001"})

    launch = value.install_attempt(
        proposal, (), active_skill=active, world=world,
        goal=SimpleNamespace(domain="QUEST"),
        current_plan=SimpleNamespace(plan_id="plan:1"),
        timeouts=timeouts, memory=None,
        visual_observation_id="visual:1", now=10.)

    assert active.attempt is launch.attempt
    assert active.state.skill_type == "TARGET"
    assert str(active.state.target_ref) == "Creature-0-0-0-0-42-0000000001"
    assert launch.start_result.status is SkillStatus.RUNNING
    assert launch.commands[0].binding == "TARGETNEARESTENEMY"


def test_install_attempt_does_not_create_parallel_active_skill():
    value = executor()
    active = ActiveSkillRuntime()
    world = SimpleNamespace(
        state={}, latest=SimpleNamespace(observation_id="obs:1"))
    timeouts = SimpleNamespace(resolve=lambda skill, base, state: base)
    proposal = Proposal.make("TARGET", "select")
    kwargs = dict(
        active_skill=active, world=world,
        goal=SimpleNamespace(domain="QUEST"),
        current_plan=SimpleNamespace(plan_id="plan:1"),
        timeouts=timeouts, memory=None,
        visual_observation_id="visual:1")

    value.install_attempt(proposal, (), now=10., **kwargs)
    try:
        value.install_attempt(proposal, (), now=11., **kwargs)
    except RuntimeError as error:
        assert "second skill" in str(error).lower()
    else:
        raise AssertionError("parallel active skill was accepted")


def test_every_registered_skill_defines_the_complete_m1_6_contract():
    for contract in SkillRegistry().contracts.values():
        assert isinstance(contract.preconditions, tuple)
        assert contract.expected_postconditions == (contract.success_condition,)
        assert contract.timeout > 0
        assert contract.retry_budget >= 0
        assert contract.recovery_policy
        assert contract.verification_method == "GENERIC_POSTCONDITION_ENGINE"
