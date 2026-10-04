from wowbot.agent.credit_failure_escalation import CreditFailureAction, CreditFailureEscalation


def test_first_no_credit_asks_for_a_recheck():
    escalation = CreditFailureEscalation()
    action = escalation.record_no_credit("q1", "o1", candidate="Creature-1", strategy="COMBAT")
    assert action is CreditFailureAction.RECHECK_QUEST_STATE_AND_IDENTITY


def test_second_similar_no_credit_reduces_confidence_and_asks_to_change_candidate():
    escalation = CreditFailureEscalation()
    escalation.record_no_credit("q1", "o1", candidate="Creature-1", strategy="COMBAT")
    action = escalation.record_no_credit("q1", "o1", candidate="Creature-1", strategy="COMBAT")
    assert action is CreditFailureAction.REDUCE_CONFIDENCE_CHANGE_CANDIDATE


def test_repeated_no_credit_escalates_to_classifier_or_locator():
    escalation = CreditFailureEscalation(escalate_after=3, block_after=5)
    escalation.record_no_credit("q1", "o1", candidate="Creature-1", strategy="COMBAT")
    escalation.record_no_credit("q1", "o1", candidate="Creature-1", strategy="COMBAT")
    action = escalation.record_no_credit("q1", "o1", candidate="Creature-2", strategy="COMBAT")
    assert action is CreditFailureAction.ESCALATE_TO_CLASSIFIER_OR_LOCATOR


def test_does_not_repeat_indefinitely_it_eventually_blocks():
    escalation = CreditFailureEscalation(escalate_after=3, block_after=5)
    action = None
    for i in range(5):
        action = escalation.record_no_credit("q1", "o1", candidate=f"C{i}", strategy="COMBAT")
    assert action is CreditFailureAction.BLOCKED_UNSUPPORTED


def test_maintains_the_two_named_failure_lists():
    escalation = CreditFailureEscalation()
    escalation.record_no_credit("q1", "o1", candidate="Creature-1", strategy="COMBAT")
    escalation.record_no_credit("q1", "o1", candidate="Creature-2", strategy="LOOT")
    snapshot = escalation.snapshot("q1", "o1")
    assert snapshot["failed_credit_candidates"] == ("Creature-1", "Creature-2")
    assert snapshot["failed_strategy_attempts"] == ("COMBAT", "LOOT")


def test_different_objectives_are_tracked_independently():
    escalation = CreditFailureEscalation()
    escalation.record_no_credit("q1", "o1", candidate="Creature-1", strategy="COMBAT")
    escalation.record_no_credit("q1", "o1", candidate="Creature-1", strategy="COMBAT")
    fresh = escalation.record_no_credit("q1", "o2", candidate="Creature-1", strategy="COMBAT")
    assert fresh is CreditFailureAction.RECHECK_QUEST_STATE_AND_IDENTITY


def test_real_credit_clears_the_ladder_back_to_first_tier():
    escalation = CreditFailureEscalation()
    escalation.record_no_credit("q1", "o1", candidate="Creature-1", strategy="COMBAT")
    escalation.record_no_credit("q1", "o1", candidate="Creature-1", strategy="COMBAT")
    escalation.clear("q1", "o1")
    action = escalation.record_no_credit("q1", "o1", candidate="Creature-3", strategy="COMBAT")
    assert action is CreditFailureAction.RECHECK_QUEST_STATE_AND_IDENTITY
    assert escalation.snapshot("q1", "o1")["failed_credit_candidates"] == ("Creature-3",)
