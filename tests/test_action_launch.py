from types import SimpleNamespace

from wowbot.agent.action_launch import ActionLaunchCoordinator
from wowbot.agent.models import Command, Outcome, Proposal
from wowbot.execution import DispatchLane
from wowbot.runtime import FailureReason, SkillResult, SkillStatus


class Executor:
    @staticmethod
    def allows_empty_start(skill):
        return skill == "LOOT"

    def prepare(self, proposal, world, observation_id, now):
        return (proposal.skill, observation_id, now)

    def install_attempt(self, proposal, commands, **kwargs):
        return SimpleNamespace(
            attempt=SimpleNamespace(action_id="a1"), commands=commands,
            start_result=kwargs.pop("start_result", None))


class M0:
    def handles(self, skill):
        return False


class Verification:
    def project(self, *args):
        return SimpleNamespace(success=True, reason="verified")


def coordinator():
    return ActionLaunchCoordinator(Executor(), M0(), Verification())


def test_empty_start_policy_is_delegated_to_canonical_skill_executor():
    value = coordinator()
    assert value.may_install(Proposal.make("LOOT", "corpse"), ()) is True
    assert value.may_install(Proposal.make("JUMP", "jump"), ()) is False
    assert value.may_install(Proposal.make("JUMP", "jump"), (Command("BIND", "JUMP"),)) is True


def test_dispatch_lane_preserves_visual_discrete_exception():
    proposal = Proposal.make("VISUAL_APPROACH", "approach")
    assert coordinator().dispatch_lane(
        proposal, (Command("BIND", "INTERACTTARGET"),)) is DispatchLane.DISCRETE
    assert coordinator().dispatch_lane(
        proposal, (Command("BIND", "MOVEFORWARD"),)) is DispatchLane.MOVEMENT
    # Live regression: SEEK_VISUAL_CUE can begin with a ready candidate and
    # issue HOVER as its very first command.  Routing that through the movement
    # scheduler raises "Érvénytelen movement lease" and demotes FULL_AI.
    assert coordinator().dispatch_lane(
        Proposal.make("SEEK_VISUAL_CUE", "identify"),
        (Command("HOVER", x=.5, y=.7, duration=.05),)) is DispatchLane.DISCRETE
    assert coordinator().dispatch_lane(
        Proposal.make("TARGET", "target"),
        (Command("BIND", "TARGETNEARESTENEMY"),)) is DispatchLane.DISCRETE


def test_follow_camera_player_turns_use_watchdog_owned_movement_lane():
    turn = (Command("BIND", "TURNLEFT", .1),)
    assert coordinator().dispatch_lane(
        Proposal.make("CAMERA_CONTROL", "scan"), turn) is DispatchLane.MOVEMENT
    assert coordinator().dispatch_lane(
        Proposal.make("REACQUIRE_TARGET", "find"), turn) is DispatchLane.MOVEMENT
    assert coordinator().dispatch_lane(
        Proposal.make("INSPECT", "scan", {"camera_pan": True}),
        turn) is DispatchLane.MOVEMENT


def test_non_m0_immediate_failure_projects_typed_terminal_without_dispatch():
    value = coordinator()
    started = SkillResult(
        SkillStatus.FAILURE, reason=FailureReason.IDENTITY_UNCERTAIN,
        metadata={"reason": "identity_lost"})
    terminal = value._immediate_terminal(
        Proposal.make("CUSTOM", "custom"), started, {})
    assert terminal.outcome is Outcome.FAILURE
    assert terminal.reason == "identity_lost"
    assert terminal.typed_reason is FailureReason.IDENTITY_UNCERTAIN


def test_non_m0_start_success_cannot_finish_before_postcondition_verifier():
    terminal = coordinator()._immediate_terminal(
        Proposal.make("CUSTOM", "custom"),
        SkillResult(SkillStatus.SUCCESS, evidence=("optimistic_start",)), {})
    assert terminal is None
