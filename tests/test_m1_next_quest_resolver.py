from types import SimpleNamespace

from wowbot.agent.next_quest_resolver import NextQuestResolver
from wowbot.agent.quest_model import QuestModel
from wowbot.agent.quest_runtime import QuestExecutionRuntime


def record(quest_id, *, state="ACTIVE", campaign=False):
    return SimpleNamespace(quest_id=quest_id, current_state=state,
                           raw={"is_campaign": campaign})


def test_next_campaign_requires_explicit_mode_and_one_addon_confirmed_candidate():
    resolver = NextQuestResolver()
    records = [record(10, campaign=True), record(20, campaign=False)]
    assert resolver.resolve(records, main_campaign=False).quest_id is None
    assert resolver.resolve(records, main_campaign=True).quest_id == "10"
    ambiguous = resolver.resolve([record(10, campaign=True), record(20, campaign=True)], main_campaign=True)
    assert ambiguous.quest_id is None and ambiguous.reason == "ambiguous_active_campaign"


def test_runtime_continues_only_main_campaign_goal_after_prior_quest_has_left_state():
    current = QuestModel()
    current.ingest([{"quest_id": 10, "objectives": []}], "a", 1.)
    runtime = QuestExecutionRuntime()
    goal = SimpleNamespace(domain="QUEST", parameters={"mode": "MAIN_CAMPAIGN"})
    assert runtime.observe(goal, current, {}, 1.).quest_id == "10"

    next_state = QuestModel()
    next_state.ingest([{"quest_id": 20, "is_campaign": True, "objectives": []}], "b", 2.)
    continued = runtime.observe(goal, next_state, {}, 2.)
    assert continued.quest_id == "20"
    assert continued.source == "MAIN_CAMPAIGN_CONTINUATION"


def test_runtime_never_replaces_an_explicit_quest_with_a_campaign_candidate():
    current = QuestModel()
    current.ingest([{"quest_id": 10, "objectives": []}], "a", 1.)
    runtime = QuestExecutionRuntime()
    goal = SimpleNamespace(domain="QUEST", parameters={"mode": "MAIN_CAMPAIGN", "quest_id": 10})
    runtime.observe(goal, current, {}, 1.)
    next_state = QuestModel()
    next_state.ingest([{"quest_id": 20, "is_campaign": True, "objectives": []}], "b", 2.)
    stopped = runtime.observe(goal, next_state, {}, 2.)
    assert stopped.quest_id == "10" and stopped.status == "NOT_ACTIVE_REASSESS"
