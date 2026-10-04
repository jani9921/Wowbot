from wowbot.agent.quest_strategy_history import QuestStrategyHistory
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.collect_strategy import CollectStrategy


def test_history_records_reward_penalty_candidates_and_attempts():
    history = QuestStrategyHistory(reward_step=.4, penalty_step=.2)
    history.penalize_no_credit("q", "o", candidate="Creature-1", strategy="COMBAT")
    history.reward_credit("q", "o", candidate="Creature-2", strategy="LOOT")
    rows = history.snapshot()
    assert sum(row["attempts"] for row in rows) == 2
    assert history.failed_candidates("q", "o") == ("Creature-1",)
    assert history.strategy_confidence("q", "o", "LOOT") == .4


def test_quest_domain_specialized_views_share_one_history():
    domain = QuestDomain()
    assert domain.credit_escalation.history is domain.strategy_history
    assert domain.collect_strategy.history is domain.strategy_history
    domain.credit_escalation.record_no_credit(
        "q", "o", candidate="Creature-1", strategy="COMBAT")
    domain.collect_strategy.record_outcome(
        "q", "o", strategy=CollectStrategy.MOB_LOOT,
        objective_progressed=True)
    assert domain.strategy_history.failed_candidates("q", "o") == ("Creature-1",)
    assert domain.strategy_history.strategy_confidence("q", "o", "MOB_LOOT") > 0


def test_credit_clear_resets_failure_tier_without_erasing_rewarded_strategy():
    domain = QuestDomain()
    domain.credit_escalation.record_no_credit(
        "q", "o", candidate="Creature-1", strategy="COMBAT")
    domain.collect_strategy.record_outcome(
        "q", "o", strategy=CollectStrategy.MOB_LOOT,
        objective_progressed=True)
    domain.credit_escalation.clear("q", "o")
    assert domain.strategy_history.failed_candidates("q", "o") == ()
    assert domain.strategy_history.strategy_confidence("q", "o", "MOB_LOOT") > 0
