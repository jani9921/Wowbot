from wowbot.verification import QuestProgressStatus, QuestProgressVerifier
import pytest


def quest(current, *, complete=False):
    return {"quest_id": 7, "is_complete": complete,
            "objectives": [{"objective_id": "o", "current": current, "required": 3,
                            "is_complete": current >= 3}]}


def test_action_success_and_quest_credit_are_separate_claims():
    verifier = QuestProgressVerifier()
    no_credit = verifier.evaluate({"active_quests": [quest(0)]}, {"active_quests": [quest(0)]},
                                   quest_ids=[7], objective_ids=["7:o"])
    assert not no_credit.success
    credit = verifier.evaluate({"active_quests": [quest(0)]}, {"active_quests": [quest(1)]},
                               quest_ids=[7], objective_ids=["7:o"])
    assert credit.success and credit.evidence == ("objective_changed:7:o",)


def test_quest_acceptance_and_completion_are_credit_evidence():
    verifier = QuestProgressVerifier()
    accepted = verifier.evaluate({"active_quests": []}, {"active_quests": [quest(0)]}, quest_ids=[7])
    assert accepted.success and accepted.evidence == ("quest_active:7",)
    completed = verifier.evaluate({"active_quests": [quest(2)]}, {"active_quests": [quest(3, complete=True)]},
                                  quest_ids=[7], objective_ids=["7:o"])
    assert completed.success


def test_typed_progress_status_distinguishes_progress_objective_and_turnin():
    verifier = QuestProgressVerifier()
    progressed = verifier.assess(
        {"active_quests": [quest(0)]},
        {"active_quests": [quest(1)]},
        quest_ids=[7], objective_ids=["7:o"],
    )
    assert progressed.status is QuestProgressStatus.QUEST_PROGRESSING
    objective_complete = verifier.assess(
        {"active_quests": [quest(2)]},
        {"active_quests": [quest(3)]},
        quest_ids=[7], objective_ids=["7:o"],
    )
    assert objective_complete.status is QuestProgressStatus.OBJECTIVE_COMPLETE
    turned_in = verifier.assess(
        {"active_quests": [quest(3, complete=True)]},
        {"active_quests": [], "events": [{
            "event_type": "QUEST_TURNED_IN", "payload": {"quest_id": 7},
        }]},
        quest_ids=[7],
    )
    assert turned_in.status is QuestProgressStatus.QUEST_COMPLETE


def test_capture_compare_and_named_queries_follow_latest_assessment():
    verifier = QuestProgressVerifier()
    verifier.capture_baseline(
        {"active_quests": [quest(2)]},
        quest_ids=[7], objective_ids=["7:o"],
    )
    assessment = verifier.compare({"active_quests": [quest(3)]})
    assert assessment.status is QuestProgressStatus.OBJECTIVE_COMPLETE
    assert verifier.credit_increased()
    assert verifier.objective_completed()
    assert not verifier.stage_changed()
    assert not verifier.ready_for_turnin()
    assert not verifier.quest_completed()


def test_stage_change_and_ready_turnin_have_explicit_outputs():
    verifier = QuestProgressVerifier()
    before = quest(1) | {"stage": 1}
    after = quest(1) | {"stage": 2}
    assert verifier.assess(
        {"active_quests": [before]}, {"active_quests": [after]}, quest_ids=[7]
    ).status is QuestProgressStatus.STAGE_CHANGED
    ready = verifier.assess(
        {"active_quests": [quest(2)]},
        {"active_quests": [quest(2, complete=True)]},
        quest_ids=[7],
    )
    assert ready.status is QuestProgressStatus.READY_TURNIN


def test_quest_start_is_distinct_from_ongoing_progress():
    verifier = QuestProgressVerifier()
    started = verifier.assess(
        {"active_quests": []},
        {"active_quests": [quest(0)], "accepted_quest_ids": [7]},
        quest_ids=[7],
    )
    assert started.status is QuestProgressStatus.QUEST_STARTED
    verifier.evaluate(
        {"active_quests": []},
        {"active_quests": [quest(0)], "accepted_quest_ids": [7]},
        quest_ids=[7],
    )
    assert verifier.quest_started()
    assert not verifier.quest_progressing()


@pytest.mark.parametrize("previous,current", [
    (quest(2), quest(1)),
    (quest(1), quest(1) | {"objectives": [
        {"objective_id": "o", "current": 1, "required": 10, "is_complete": False}]}),
    (quest(0) | {"objectives": []}, quest(1)),
    (quest(1) | {"stage": 1}, quest(1)),
    (quest(1), quest(1) | {"stage": 1}),
])
def test_missing_fields_and_regressions_do_not_confirm_credit(previous, current):
    result = QuestProgressVerifier().evaluate(
        {"active_quests": [previous]}, {"active_quests": [current]},
        quest_ids=[7], objective_ids=["7:o"])
    assert not result.success


def test_retained_turnin_event_cannot_credit_another_attempt():
    event = {"event_type": "QUEST_TURNED_IN", "payload": {"quest_id": 7}}
    snapshot = {"events": [event]}
    assert not QuestProgressVerifier().evaluate(snapshot, snapshot, quest_ids=[7]).success


def test_baseline_return_value_does_not_mutate_internal_baseline():
    verifier = QuestProgressVerifier()
    returned = verifier.capture_baseline(
        {"active_quests": [quest(1)]}, quest_ids=[7], objective_ids=["7:o"])
    returned["active_quests"][0]["objectives"][0]["current"] = 2
    assert verifier.compare({"active_quests": [quest(2)]}).status is QuestProgressStatus.QUEST_PROGRESSING
