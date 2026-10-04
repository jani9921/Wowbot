"""V4-032 wiring: MovementSkillRunner.step() annotates MovementStep.phase."""
from wowbot.agent.models import Proposal
from wowbot.agent.movement_controller import MovementAssessment
from wowbot.agent.movement_controller import MovementPhase as LegacyMovementPhase
from wowbot.skills import MovementSkillRunner
from wowbot.skills.movement_phase_contract import MovementPhase


class Navigation:
    def __init__(self, assessment, commands=()):
        self.assessment = assessment
        self.commands = commands
        self.last_command_observation_id = "old"
        self.verified = []

    def observe(self, state, observation_id, now, commanded):
        return self.assessment

    def observe_verified_move(self, before, after, destination):
        self.verified.append((before, after, destination))

    def command(self, state, observation_id, now):
        return self.commands


def _attempt(skill="MOVE"):
    return type("Attempt", (), {"proposal": Proposal.make(skill, "test", {"x": .2, "y": .3})})()


def test_just_started_attempt_reports_init_phase():
    nav = Navigation(MovementAssessment(LegacyMovementPhase.IDLE, False, False, "starting"))
    step = MovementSkillRunner(nav).step(_attempt(), {}, "new", 1.0, None)
    assert step.phase is MovementPhase.INIT


def test_moving_assessment_reports_monitor_progress_phase():
    nav = Navigation(MovementAssessment(LegacyMovementPhase.MOVING, False, False, "reach_progress_observed"))
    step = MovementSkillRunner(nav).step(_attempt(), {}, "new", 1.0, {"position": {"x": 0., "y": 0.}})
    assert step.phase is MovementPhase.MONITOR_PROGRESS


def test_stuck_assessment_reports_recover_stuck_phase():
    nav = Navigation(MovementAssessment(LegacyMovementPhase.SUPPORTED_STUCK, False, False, "stuck"))
    step = MovementSkillRunner(nav).step(_attempt(), {}, "new", 1.0, {"position": {"x": 0., "y": 0.}})
    assert step.phase is MovementPhase.RECOVER_STUCK


def test_successful_terminal_assessment_reports_arrival_verify_phase():
    nav = Navigation(MovementAssessment(LegacyMovementPhase.ARRIVED, True, True, "arrived"))
    step = MovementSkillRunner(nav).step(_attempt(), {}, "new", 1.0, {"position": {"x": 0., "y": 0.}})
    assert step.phase is MovementPhase.ARRIVAL_VERIFY
