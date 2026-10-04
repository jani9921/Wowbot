from types import SimpleNamespace

from wowbot.agent.models import Proposal
from wowbot.skills import MovementSkillRunner


class Navigation:
    def __init__(self, assessment, commands=()):
        self.assessment = assessment
        self.commands = commands
        self.last_command_observation_id = "old"
        self.verified = []

    def observe(self, state, observation_id, now, commanded):
        assert commanded is True
        return self.assessment

    def observe_verified_move(self, before, after, destination):
        self.verified.append((before, after, destination))

    def command(self, state, observation_id, now):
        return self.commands


def test_movement_runner_reports_progress_and_returns_commands_without_dispatching():
    nav = Navigation(SimpleNamespace(terminal=False, reason="reach_progress_observed"), ("forward",))
    runner = MovementSkillRunner(nav)
    attempt = SimpleNamespace(proposal=Proposal.make("MOVE", "test", {"x": .2, "y": .3}))
    baseline = {"position": {"x": .1, "y": .1}}
    current = {"position": {"x": .11, "y": .1}}

    step = runner.step(attempt, current, "new", 2., baseline)

    assert step.commands == ("forward",)
    assert nav.verified == [(baseline, current, attempt.proposal.parameters)]
    assert step.next_segment_baseline == current
    assert step.next_segment_baseline is not current


def test_terminal_movement_step_emits_no_more_commands():
    nav = Navigation(SimpleNamespace(terminal=True, reason="arrived"), ("must-not-run",))
    attempt = SimpleNamespace(proposal=Proposal.make("REACH_LOCATION", "test", {"x": .2, "y": .3}))

    step = MovementSkillRunner(nav).step(attempt, {}, "new", 2., None)

    assert step.commands == ()
