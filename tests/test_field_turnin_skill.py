from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.runtime import ActiveSkillRuntime, FailureReason, Intent, SkillStatus
from wowbot.skills import FieldTurnInPhase, FieldTurnInSkill, QuestDialogSkill


def _world(mode="FIELD_TURN_IN"):
    return {"quest_completion_mode": mode, "quest_ui": {
        "open": True, "action": "TURN_IN", "quest_id": 42,
        "x": .55, "y": .81}}


def _active(mode="FIELD_TURN_IN"):
    params = {"completion_mode": mode, "action": "TURN_IN",
              "quest_id": 42, "x": .55, "y": .81}
    before = _world(mode)
    attempt = Attempt(
        "field", Proposal.make("FIELD_TURN_IN", "test", params),
        before, "obs", 1., 10., (),
        Prediction("prediction", "field", "state", 1., 10., "obs"))
    return ActiveSkillRuntime().start(
        intent=Intent("FIELD_TURN_IN", params), attempt=attempt,
        now=1., before_snapshot=before)


def test_field_turnin_is_mode_guarded_and_uses_dialog_verification():
    skill = FieldTurnInSkill(QuestDialogSkill())
    active = _active()
    begun = skill.begin(active, _world())
    assert begun.status is SkillStatus.RUNNING
    assert begun.commands[0].kind == "CLICK"
    assert skill.verify(active, _world(), 2.).status is SkillStatus.RUNNING
    completed = {**_world(), "events": [{
        "event_type": "QUEST_TURNED_IN", "payload": {"quest_id": 42}}]}
    result = skill.verify(active, completed, 3.)
    assert result.status is SkillStatus.SUCCESS
    assert active.phase == FieldTurnInPhase.VERIFY_COMPLETED.value


def test_field_turnin_refuses_unconfirmed_completion_mode():
    result = FieldTurnInSkill(QuestDialogSkill()).begin(
        _active("NPC_TURN_IN"), _world("NPC_TURN_IN"))
    assert result.status is SkillStatus.BLOCKED
    assert result.reason is FailureReason.UNSUPPORTED_MECHANIC


def test_planner_routes_only_confirmed_field_completion_to_field_skill():
    field = QuestDialogPlanningPolicy().propose(_world(), None)
    assert any(item.skill == "FIELD_TURN_IN" for item in field)
    npc = QuestDialogPlanningPolicy().propose(_world("NPC_TURN_IN"), None)
    assert any(item.skill == "QUEST_DIALOG" for item in npc)
    assert not any(item.skill == "FIELD_TURN_IN" for item in npc)
