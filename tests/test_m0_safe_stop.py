"""M0 safe-stop regression: execution errors cannot leave a live action."""

from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Mode
from test_agent_core import state


class FailingExecutor(RecordingExecutor):
    def execute(self, commands):
        raise RuntimeError("synthetic executor failure")

    def execute_movement(self, commands):
        raise RuntimeError("synthetic executor failure")


def test_executor_exception_forces_manual_safe_stop_and_finalizes_active_skill():
    executor = FailingExecutor()
    agent = AutonomousAgent(executor)
    agent.set_goal("Questelj", 1.)
    agent.set_mode(Mode.FULL_AI)

    result = agent.tick(state(1., world_map_open=False, visual_candidates=[]), 1.)

    assert result["mode"] == "MANUAL"
    assert executor.stops >= 1
    assert agent.active_skill.state is None
    assert agent.pending is None
