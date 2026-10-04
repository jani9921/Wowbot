from wowbot.agent.models import Goal
from wowbot.agent.quest_accept_flow import QuestAcceptFlow, QuestAcceptPhase
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy


def _state(quest_id=42):
    return {"quest_ui": {"open": True, "action": "ACCEPT",
                         "quest_id": quest_id, "x": .5, "y": .6}}


def test_accept_flow_contract_reads_matches_commands_and_verifies():
    flow = QuestAcceptFlow()
    offer = flow.read_offer(_state())
    assert [phase.value for phase in QuestAcceptPhase] == [
        "LOCATE_QUEST_SOURCE", "INTERACT", "READ_QUEST_OFFER",
        "VALIDATE_QUEST", "ACCEPT", "WAIT_STATE", "VERIFY_ACTIVE"]
    assert flow.matches_goal(offer, Goal.parse("Quest", 1., {"quest_id": 42}))
    assert flow.accept_command(offer)["action"] == "ACCEPT"
    after = {"active_quests": [{"quest_id": 42}], "events": []}
    assert flow.verify_accepted({"active_quests": []}, after, 42).success


def test_explicit_goal_mismatch_blocks_instead_of_accepting_wrong_quest():
    goal = Goal.parse("Quest", 1., {"quest_id": 99})
    proposals = QuestDialogPlanningPolicy().propose(_state(42), goal)
    assert not any(item.skill == "QUEST_DIALOG" for item in proposals)
    wait = next(item for item in proposals if item.skill == "WAIT")
    assert wait.parameters["reason"] == "quest_offer_goal_mismatch"
