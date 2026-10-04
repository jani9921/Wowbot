from wowbot.agent.planner import Planner
from wowbot.agent.quest_attempt_memory import QuestAttemptMemory
from wowbot.agent.quest_runtime import QuestExecutionRuntime
from wowbot.agent.skills import SkillRegistry


def test_one_owner_unifies_execution_failure_and_credit_strategy_evidence():
    memory = QuestAttemptMemory(cooldown_seconds=5.)
    memory.record_execution_failure(
        quest_id=7, objective_id="7:0", target_ref="Creature-1",
        skill="COMBAT", reason="NO_CREDIT", now=1.)
    memory.record_strategy(
        7, "7:0", candidate="Creature-1", strategy="COMBAT",
        action_success=True, quest_credit=False)

    view = memory.query(7, "7:0", now=2.)
    assert len(view["failures"]) == 1 and len(view["strategies"]) == 1
    assert view["strategies"][0]["no_credit_attempts"] == 1
    assert memory.reliability(7, "7:0", "COMBAT") == 0.
    assert memory.consolidate() == {"failure_records": 1, "strategy_records": 1}
    assert memory.expire(7.) == 1


def test_planner_domain_and_quest_runtime_share_exact_attempt_memory_instance():
    memory = QuestAttemptMemory()
    planner = Planner(SkillRegistry(), quest_attempt_memory=memory)
    runtime = QuestExecutionRuntime(memory)

    assert planner.quest_attempt_memory is memory
    assert planner.quest.attempt_memory is memory
    assert runtime.attempt_memory is memory
    assert planner.quest.strategy_history is memory.strategy_history
    assert runtime.failure_memory is memory.failure_memory


def test_session_reset_clears_attempt_memory_without_replacing_owner():
    memory = QuestAttemptMemory()
    planner = Planner(SkillRegistry(), quest_attempt_memory=memory)
    memory.record_strategy(7, "7:0", strategy="COMBAT",
                           action_success=True, quest_credit=True)
    memory.record_execution_failure(
        quest_id=7, objective_id="7:0", target_ref="Creature-1",
        skill="COMBAT", reason="FAILED", now=1.)

    planner.reset_session()

    assert planner.quest_attempt_memory is memory
    assert planner.quest.attempt_memory is memory
    assert memory.query(7, "7:0", now=1.)["failures"] == []
    assert memory.query(7, "7:0", now=1.)["strategies"] == []


def test_production_agent_keeps_one_owner_across_goal_runtime_replacement():
    from test_agent_core import agent

    value, _executor = agent()
    owner = value.quest_attempt_memory
    assert value.planner.quest.attempt_memory is owner
    assert value.quest_runtime.attempt_memory is owner

    value.set_goal("Questelj", 2.)

    assert value.quest_attempt_memory is owner
    assert value.planner.quest.attempt_memory is owner
    assert value.quest_runtime.attempt_memory is owner
