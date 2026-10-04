"""V4-070 wiring: QuestDomain.record_uncredited_target feeds the escalation ladder."""
from wowbot.agent.credit_failure_escalation import CreditFailureAction
from wowbot.agent.quest_planning import QuestDomain


def _state(quest_id=10, current=0):
    return {"active_quests": [{"quest_id": quest_id, "objectives": [
        {"objective_id": "0", "current_count": current, "required_count": 1, "is_complete": current >= 1},
    ]}]}


def test_first_no_credit_records_recheck_tier():
    domain = QuestDomain()
    domain.record_uncredited_target("Creature-1", (10,), ("0",), _state(), 1.0)
    assert domain.credit_escalation_action(10, "0") is CreditFailureAction.RECHECK_QUEST_STATE_AND_IDENTITY


def test_second_no_credit_same_state_escalates_to_reduce_confidence():
    domain = QuestDomain()
    state = _state()
    domain.record_uncredited_target("Creature-1", (10,), ("0",), state, 1.0)
    domain.record_uncredited_target("Creature-2", (10,), ("0",), state, 2.0)
    assert domain.credit_escalation_action(10, "0") is CreditFailureAction.REDUCE_CONFIDENCE_CHANGE_CANDIDATE


def test_query_does_not_mutate_the_ladder():
    domain = QuestDomain()
    domain.record_uncredited_target("Creature-1", (10,), ("0",), _state(), 1.0)
    before = domain.credit_escalation_action(10, "0")
    after = domain.credit_escalation_action(10, "0")
    assert before is after is CreditFailureAction.RECHECK_QUEST_STATE_AND_IDENTITY
