from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import ObjectUseSkill


def _state(*, cursor=(.4, .6), object_id=77):
    return {"mouseover": {"object_id": object_id, "tooltip": "Campfire"},
            "cursor_position": {"nx": cursor[0], "ny": cursor[1]}}


def _active():
    params = {"x": .4, "y": .6, "object_id": 77, "mouseover_tooltip": "Campfire",
              "quest_ids": [10], "objective_ids": ["10:0"]}
    before = {**_state(), "active_quests": [{"quest_id": 10, "objectives": [
        {"objective_id": "0", "current": 0, "required": 1, "is_complete": False},
    ]}]}
    attempt = Attempt("action", Proposal.make("OBJECT_USE", "test", params), before,
                      "obs", 1., 5., (), Prediction("prediction", "action", "state", 1., 5., "obs"))
    return ActiveSkillRuntime().start(intent=Intent("OBJECT_USE", params, None, "10:0"),
                                       attempt=attempt, now=1., before_snapshot=before)


def test_object_use_requires_current_mouseover_identity_and_only_quest_credit_succeeds():
    skill, state = ObjectUseSkill(), _active()
    started = skill.begin(state, _state())
    assert started.status is SkillStatus.RUNNING
    assert started.commands[0].kind == "CLICK" and started.commands[0].button == "RIGHT"
    event_only = {**_state(), "events": [{"event_type": "OBJECT_USED", "payload": {"object_id": 77}}]}
    assert skill.verify(state, event_only, 2.).status is SkillStatus.RUNNING
    credited = {**_state(), "active_quests": [{"quest_id": 10, "objectives": [
        {"objective_id": "0", "current": 1, "required": 1, "is_complete": True},
    ]}]}
    assert skill.verify(state, credited, 3.).status is SkillStatus.SUCCESS


def test_object_use_rejects_stale_cursor_or_wrong_hovered_object():
    assert ObjectUseSkill().begin(_active(), _state(cursor=(.41, .6))).status is SkillStatus.FAILURE
    assert ObjectUseSkill().begin(_active(), _state(object_id=88)).status is SkillStatus.FAILURE
