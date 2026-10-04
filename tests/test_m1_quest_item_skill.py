from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, FailureReason, Intent, SkillStatus
from wowbot.skills import QuestItemSkill, UseItemPhase, UseItemSkill


class _Bindings:
    def __init__(self, actions=("ACTIONBUTTON7",)):
        self.actions = set(actions)

    def contains(self, action):
        return action in self.actions


def _state(item_id=44, binding="ACTIONBUTTON7"):
    return {
        "target": {"guid": "Creature-quest", "dead": False},
        "actionbar": [{"kind": "item", "id": item_id, "action": binding,
                       "is_usable": True, "cooldown_remaining": 0}],
    }


def _active(**extra):
    params = {"guid": "Creature-quest", "item_id": 44, "binding": "ACTIONBUTTON7",
              "quest_ids": [7], "objective_ids": ["7:heal"], **extra}
    before = {**_state(), "active_quests": [{"quest_id": 7, "objectives": [
        {"objective_id": "heal", "current": 0, "required": 1, "is_complete": False}]}]}
    attempt = Attempt("action", Proposal.make("USE_ON_TARGET", "test", params), before, "obs", 1., 5., (),
                      Prediction("prediction", "action", "state", 1., 5., "obs"))
    runtime = ActiveSkillRuntime()
    return runtime.start(intent=Intent("USE_ON_TARGET", params, "Creature-quest", "7:heal"),
                         attempt=attempt, now=1., before_snapshot=before)


def test_targeted_quest_item_rechecks_target_item_and_selected_binding_then_needs_credit():
    skill = QuestItemSkill(_Bindings())
    state = _active()
    started = skill.begin(state, _state())
    assert started.status is SkillStatus.RUNNING
    assert started.commands[0].binding == "ACTIONBUTTON7"
    assert skill.verify(state, _state(), 2.).status is SkillStatus.RUNNING
    credited = {**_state(), "active_quests": [{"quest_id": 7, "objectives": [
        {"objective_id": "heal", "current": 1, "required": 1, "is_complete": True}]}]}
    result = skill.verify(state, credited, 3.)
    assert result.status is SkillStatus.SUCCESS
    assert result.evidence == ("objective_changed:7:heal",)


def test_targeted_quest_item_fails_closed_for_retarget_or_untrusted_actionbar_binding():
    assert QuestItemSkill(_Bindings()).begin(_active(), {**_state(), "target": {"guid": "other"}}).status is SkillStatus.FAILURE
    assert QuestItemSkill(_Bindings(())).begin(_active(), _state()).status is SkillStatus.FAILURE


def test_use_item_design_contract_and_range_gate_are_canonical():
    assert QuestItemSkill is UseItemSkill
    skill = UseItemSkill(_Bindings())
    active = _active()
    world = _state()
    world["actionbar"][0]["in_range"] = False
    result = skill.begin(active, world)
    assert result.reason is FailureReason.OUT_OF_RANGE
    assert active.phase == UseItemPhase.APPROACH.value


def test_targeted_quest_item_can_use_revalidated_visible_bag_coordinate():
    params = {"guid": "Creature-quest", "item_id": 44,
              "activation_source": "INVENTORY_COORDINATE",
              "bag": 0, "slot": 9, "x": .81, "y": .22,
              "coordinate_space": "CLIENT_BOTTOM_LEFT",
              "quest_ids": [7], "objective_ids": ["7:heal"]}
    before = {
        "target": {"guid": "Creature-quest", "dead": False},
        "bags_open": True,
        "active_quests": [{"quest_id": 7, "special_item": {"item_id": 44},
                           "objectives": [{"objective_id": "heal", "current": 0,
                                           "required": 1, "is_complete": False}]}],
        "inventory": {"items": [{"bag": 0, "slot": 9, "item_id": 44,
                                    "is_locked": False, "x": .81, "y": .22,
                                    "coordinate_space": "CLIENT_BOTTOM_LEFT"}]},
        "actionbar": [],
    }
    attempt = Attempt("action", Proposal.make("USE_ON_TARGET", "test", params), before,
                      "obs", 1., 5., (), Prediction("prediction", "action", "state", 1., 5., "obs"))
    active = ActiveSkillRuntime().start(
        intent=Intent("USE_ON_TARGET", params, "Creature-quest", "7:heal"),
        attempt=attempt, now=1., before_snapshot=before)
    result = UseItemSkill().begin(active, before)
    assert result.status is SkillStatus.RUNNING
    assert (result.commands[0].kind, result.commands[0].button,
            result.commands[0].x, result.commands[0].y) == ("CLICK", "RIGHT", .81, .22)


def test_targeted_quest_item_rejects_stale_or_unauthorized_bag_coordinate():
    params = {"guid": "Creature-quest", "item_id": 44,
              "activation_source": "INVENTORY_COORDINATE", "bag": 0, "slot": 9,
              "x": .81, "y": .22, "coordinate_space": "CLIENT_BOTTOM_LEFT",
              "quest_ids": [7], "objective_ids": ["7:heal"]}
    before = {"target": {"guid": "Creature-quest", "dead": False}, "bags_open": True,
              "active_quests": [{"quest_id": 7, "special_item": {"item_id": 999}}],
              "inventory": {"items": [{"bag": 0, "slot": 9, "item_id": 44,
                                          "is_locked": False, "x": .7, "y": .22,
                                          "coordinate_space": "CLIENT_BOTTOM_LEFT"}]},
              "actionbar": []}
    attempt = Attempt("action", Proposal.make("USE_ON_TARGET", "test", params), before,
                      "obs", 1., 5., (), Prediction("prediction", "action", "state", 1., 5., "obs"))
    active = ActiveSkillRuntime().start(
        intent=Intent("USE_ON_TARGET", params, "Creature-quest", "7:heal"),
        attempt=attempt, now=1., before_snapshot=before)
    result = UseItemSkill().begin(active, before)
    assert result.status is SkillStatus.BLOCKED
    assert result.reason is FailureReason.UNSUPPORTED_MECHANIC
