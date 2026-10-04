from types import SimpleNamespace

from wowbot.agent.models import Command
from wowbot.runtime import FailureReason, SkillResult, SkillStatus
from wowbot.skills.visual_runtime import VisualRuntimeRunner


class Skill:
    def __init__(self, result, *, phase="TRACKING"):
        self.result = result
        self.current_phase = phase

    def observe(self, active, state, observation_id, now):
        return self.result

    def snapshot(self, active):
        return {"phase": self.current_phase}

    def phase(self, active):
        return self.current_phase


def test_search_player_turn_uses_movement_lane_for_follow_camera_scan():
    command = Command(kind="BIND", binding="TURNLEFT", duration=.1)
    search = Skill(SkillResult(SkillStatus.RUNNING, commands=(command,)))
    step = VisualRuntimeRunner(search, Skill(SkillResult(SkillStatus.RUNNING))).step_search(
        SimpleNamespace(), {}, "obs", 1.)
    assert step.commands == (command,)
    assert step.movement_lane is True
    assert step.stop_movement is False
    assert step.camera_action is None


def test_approach_forward_step_stays_on_movement_lane():
    command = Command(kind="KEY", binding="MOVEFORWARD", duration=.1)
    approach = Skill(SkillResult(SkillStatus.RUNNING, commands=(command,)))
    step = VisualRuntimeRunner(Skill(SkillResult(SkillStatus.RUNNING)), approach).step_approach(
        SimpleNamespace(), {}, "obs", 1.)
    assert step.movement_lane is True
    assert step.stop_movement is False
    assert step.camera_action is None


def test_terminal_and_occluded_states_never_dispatch_from_runner():
    failed = Skill(SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_LOST))
    runner = VisualRuntimeRunner(failed, failed)
    terminal = runner.step_search(SimpleNamespace(), {}, "obs", 1.)
    assert terminal.terminal_result.status is SkillStatus.FAILURE
    assert terminal.commands == () and terminal.stop_movement is True

    occluded = Skill(SkillResult(SkillStatus.RUNNING), phase="OCCLUDED")
    held = VisualRuntimeRunner(failed, occluded).step_approach(
        SimpleNamespace(), {}, "obs", 1.)
    assert held.commands == () and held.stop_movement is True
