from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Mode
from wowbot.agent.skills import SkillRegistry
from test_agent_core import state


def test_goal_plan_action_prediction_have_distinct_linked_ids():
    agent = AutonomousAgent(RecordingExecutor())
    agent.set_goal("Menj oda", 1, {"destination": {"map_id": 1609, "x": .5, "y": .4}})
    agent.set_mode(Mode.FULL_AI)
    result = agent.tick(state(), 1)
    assert result["plan"]["goal_id"] == result["goal"]["goal_id"]
    assert result["decision"]["plan_id"] == result["plan"]["plan_id"]
    assert result["pending"]["plan_id"] == result["plan"]["plan_id"]
    assert len({result["goal"]["goal_id"], result["plan"]["plan_id"],
                result["pending"]["action_id"], result["pending"]["prediction"]["prediction_id"]}) == 4
    assert result["plan"]["expected_outcome"] == "reach_destination"


def test_skill_contract_exposes_operational_contract_and_cost():
    move = SkillRegistry().contracts["MOVE"]
    assert move.capability == "MOVE"
    assert move.preconditions == ("known_destination",)
    assert move.required_world_state == ("position", "orientation", "map_id")
    assert move.success_condition == move.expected
    assert move.failure_condition and move.recovery and move.cost > 0
