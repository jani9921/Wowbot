"""V4-055 wiring: CombatSkill must not fire normal rotation during a vehicle override."""
from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills.combat import CombatSkill


def _active():
    params = {"guid": "Creature-1"}
    before = {"target": {"guid": "Creature-1", "attackable": True}}
    attempt = Attempt("action", Proposal.make("COMBAT", "test", params), before,
                      "obs", 1., 30., (), Prediction("prediction", "action", "state", 1., 30., "obs"))
    return ActiveSkillRuntime().start(intent=Intent("COMBAT", params, "Creature-1"),
                                       attempt=attempt, now=1., before_snapshot=before)


def _world(**overrides):
    value = {"target": {"guid": "Creature-1", "attackable": True, "dead": False},
             "actionbar": [{"kind": "spell", "action": "1", "id": 100, "is_harmful": True, "in_range": True}]}
    value.update(overrides)
    return value


def test_combat_does_not_report_vehicle_override_when_none_is_active():
    skill = CombatSkill()
    state = _active()
    result = skill.begin(state, _world(), 1.0)
    assert result.metadata.get("reason") != "vehicle_override_active"


def test_combat_refuses_to_fire_rotation_during_vehicle_override():
    skill = CombatSkill()
    state = _active()
    result = skill.begin(state, _world(in_vehicle=True), 1.0)
    assert result.status is SkillStatus.FAILURE
    assert result.replan_required
    assert result.metadata.get("reason") == "vehicle_override_active"
