from types import SimpleNamespace

from wowbot.agent.active_skill_supervision import ActiveSkillSupervisor
from wowbot.agent.models import Command, Outcome, Proposal
from wowbot.runtime import FailureReason, SkillResult, SkillStatus


class M0:
    def __init__(self, result): self.result = result
    def verify(self, active, state, now): return self.result


class Verification:
    def confirm(self, skill, result, state, **kwargs):
        return SimpleNamespace(
            pending=result.status is SkillStatus.RUNNING,
            success=result.status is SkillStatus.SUCCESS,
            reason=result.metadata.get("legacy_reason", "verified"),
            typed_reason=result.reason,
            verifier=kwargs.get("verifier", "TEST_VERIFIER"),
            evidence=tuple(result.evidence))


class Runtime:
    def __init__(self, step): self.step = step
    def step_world_entity(self, *args): return self.step
    def step_visual(self, *args): return self.step
    def step_verification(self, *args, **kwargs): return self.step
    def continue_approach(self, *args): return self.step


class Registry:
    def verify(self, attempt, world, now): return Outcome.PENDING, "waiting"
    def commands(self, proposal, world): return (Command("BIND", "MOVEFORWARD"),)


def supervisor(result, runtime_step=None):
    empty = SimpleNamespace(
        commands=(), movement_lane=False, terminal_result=None,
        event_type=None, diagnostics={}, stop_movement=False,
        set_segment_baseline=False)
    runtime = Runtime(runtime_step or empty)
    return ActiveSkillSupervisor(
        m0_skills=M0(result), verification_engine=Verification(),
        interaction_runtime=runtime, combat_runtime=runtime,
        loot_runtime=runtime, registry=Registry(),
        movement_runtime=runtime, visual_runtime=runtime)


class MovementRuntime:
    def __init__(self, assessment, commands=()):
        self.assessment, self.commands = assessment, commands

    def step(self, *args):
        return SimpleNamespace(
            assessment=self.assessment, commands=self.commands,
            next_segment_baseline={"position": {"x": 1}})


def context(skill, *, skill_context=None):
    proposal = Proposal.make(skill, "test")
    attempt = SimpleNamespace(proposal=proposal)
    active = SimpleNamespace(skill_type=skill, skill_context=skill_context or {})
    world = SimpleNamespace(state={})
    return attempt, active, world


def test_target_verification_projects_terminal_without_dispatch_authority():
    value = supervisor(SkillResult(SkillStatus.SUCCESS))
    attempt, active, world = context("TARGET")

    step = value.step(
        attempt, active, world, world_observation_id="obs:1",
        visual_observation_id="visual:1", now=1.)

    assert step.terminal_outcome is Outcome.SUCCESS
    assert step.commands == ()
    assert not step.dispatch_failure_terminal


def test_interaction_approach_returns_commands_but_cannot_dispatch_them():
    runtime_step = SimpleNamespace(
        commands=(Command("BIND", "MOVEFORWARD"),), movement_lane=True,
        terminal_result=None, event_type="INTERACT_APPROACH_CONTROL_UPDATE",
        diagnostics={"movement": "running"}, stop_movement=False,
        set_segment_baseline=False)
    value = supervisor(SkillResult(SkillStatus.RUNNING), runtime_step)
    attempt, active, world = context(
        "INTERACT", skill_context={"interaction": {
            "approach_request": {"kind": "WORLD_ENTITY"}}})

    step = value.step(
        attempt, active, world, world_observation_id="obs:1",
        visual_observation_id="visual:1", now=1.)

    assert step.commands[0].binding == "MOVEFORWARD"
    assert step.movement_lane and step.dispatch_failure_terminal
    assert step.terminal_outcome is None


def test_combat_runtime_terminal_preserves_typed_reason_and_return_boundary():
    terminal = SkillResult(
        SkillStatus.FAILURE, FailureReason.TARGET_MOVED,
        metadata={"legacy_reason": "target_moved"})
    runtime_step = SimpleNamespace(
        commands=(), movement_lane=False, terminal_result=terminal,
        event_type=None, diagnostics={}, set_segment_baseline=False)
    value = supervisor(SkillResult(SkillStatus.RUNNING), runtime_step)
    attempt, active, world = context(
        "COMBAT", skill_context={"combat": {
            "approach_request": {"kind": "WORLD_ENTITY"}}})

    step = value.step(
        attempt, active, world, world_observation_id="obs:1",
        visual_observation_id="visual:1", now=1.)

    assert step.terminal_outcome is Outcome.FAILURE
    assert step.reason == "target_moved"
    assert step.typed_reason is FailureReason.TARGET_MOVED
    assert step.return_after_terminal


def test_movement_runtime_is_routed_without_dispatching_commands():
    assessment = SimpleNamespace(terminal=False, success=False, reason="moving")
    value = supervisor(SkillResult(SkillStatus.RUNNING))
    value.movement_runtime = MovementRuntime(
        assessment, (Command("BIND", "MOVEFORWARD"),))
    attempt, active, world = context("MOVE")
    world.latest = SimpleNamespace(source="ADDON", payload={})

    step = value.step(
        attempt, active, world, world_observation_id="obs:1",
        visual_observation_id="visual:1", now=1., segment_baseline={})

    assert step.commands[0].binding == "MOVEFORWARD"
    assert step.movement_lane
    assert step.movement_assessment is assessment
    assert step.next_segment_baseline["position"]["x"] == 1


def test_movement_visual_handoff_is_cancellation_not_false_arrival():
    value = supervisor(SkillResult(SkillStatus.RUNNING))
    attempt, active, world = context("MOVE")
    world.latest = SimpleNamespace(source="WORLD3D", payload={})
    handoff = {"reason": "quest_route_visual_cue_observed",
               "kind": "QUEST_ROUTE_VISUAL_CUE", "track_id": "mob-7"}

    step = value.step(
        attempt, active, world, world_observation_id="obs:1",
        visual_observation_id="visual:1", now=1.,
        reference_reach_interrupt=handoff)

    assert step.terminal_outcome is Outcome.CANCELLED
    assert step.stop_movement
    assert step.diagnostics["movement_visual_handoff"]["track_id"] == "mob-7"


def test_reference_reach_frame_yields_without_becoming_no_progress():
    value = supervisor(SkillResult(SkillStatus.RUNNING))
    attempt, active, world = context("REACH_LOCATION")
    world.latest = SimpleNamespace(
        source="WORLD3D", payload={"provenance": {
            "control_lane": "REFERENCE_REACH_SEARCH"}})

    step = value.step(
        attempt, active, world, world_observation_id="obs:1",
        visual_observation_id="visual:1", now=1.)

    assert step.yield_tick
    assert step.commands == ()
