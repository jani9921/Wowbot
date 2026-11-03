"""Unknown/zero UI quest IDs are pending; other positive IDs remain wrong."""
import pytest

from wowbot.runtime import FailureReason, SkillStatus
from wowbot.skills.quest_dialog import QuestDialogSkill
from wowbot.verification.quest_dialog import QuestDialogVerifier
from test_m0_combat_loot_skills import active


@pytest.mark.parametrize("unknown", [None, 0, "0", "", False])
def test_unknown_ui_quest_identity_does_not_fail_or_prove_selection(unknown):
    result = QuestDialogVerifier().evaluate({}, {"quest_ui": {
        "open": True, "action": "", "quest_id": unknown}}, quest_id=69912, action="GOSSIP_SELECT")
    assert not result.success and result.reason is None


def test_real_wrong_quest_still_fails_and_exact_named_action_confirms_selection():
    verifier = QuestDialogVerifier()
    wrong = verifier.evaluate({}, {"quest_ui": {"open": True, "action": "ACCEPT", "quest_id": 69911}},
        quest_id=69912, action="GOSSIP_SELECT")
    assert not wrong.success and wrong.reason is FailureReason.WRONG_QUEST_UI
    exact = verifier.evaluate({}, {"quest_ui": {"open": True, "action": "ACCEPT", "quest_id": 69912}},
        quest_id=69912, action="GOSSIP_SELECT")
    assert exact.success


def test_one_row_click_then_zero_identity_waits_without_reclick_and_still_times_out():
    initial = {"quest_ui": {"open": True, "action": "", "quest_id": 0, "entries": [
        {"quest_id": 69912, "kind": "AVAILABLE", "x": .1, "y": .6}]}, "state_age": .1}
    params = {"action": "GOSSIP_SELECT", "quest_id": 69912, "gossip_kind": "AVAILABLE", "x": .1, "y": .6}
    skill = QuestDialogSkill()
    context = active("QUEST_DIALOG", params, initial)
    begun = skill.begin(context, initial)
    assert begun.status is SkillStatus.RUNNING and len(begun.commands) == 1
    waiting = skill.verify(context, initial, 2.)
    assert waiting.status is SkillStatus.RUNNING and not waiting.commands
    expired = skill.verify(context, initial, 8.)
    assert expired.status is SkillStatus.FAILURE and not expired.commands
    assert expired.reason is FailureReason.EXPECTED_STATE_NOT_REACHED
