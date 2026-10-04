from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills.vehicle import VehicleSkill, is_vehicle_override_active, rotation_allowed


def _state(**overrides):
    value = {"in_vehicle": True, "vehicle_id": "42"}
    value.update(overrides)
    return value


def _active(vehicle_actions=("VEHICLE_ACTION_1",), quest_ids=(10,), objective_ids=("10:0",)):
    params = {"vehicle_actions": list(vehicle_actions), "quest_ids": list(quest_ids),
              "objective_ids": list(objective_ids)}
    before = {**_state(), "active_quests": [{"quest_id": 10, "objectives": [
        {"objective_id": "0", "current": 0, "required": 1, "is_complete": False},
    ]}]}
    attempt = Attempt("action", Proposal.make("VEHICLE", "test", params), before,
                      "obs", 1., 5., (), Prediction("prediction", "action", "state", 1., 5., "obs"))
    return ActiveSkillRuntime().start(intent=Intent("VEHICLE", params, None, "10:0"),
                                       attempt=attempt, now=1., before_snapshot=before)


def test_is_vehicle_override_active_recognizes_in_vehicle_flag():
    assert is_vehicle_override_active({"in_vehicle": True})
    assert is_vehicle_override_active({"vehicle_ui": True})
    assert is_vehicle_override_active({"vehicle_camera": True})
    assert not is_vehicle_override_active({})


def test_rotation_allowed_is_false_during_vehicle_override():
    # This is the literal "do not let normal rotation fire into a vehicle
    # override state" guard.
    assert not rotation_allowed({"in_vehicle": True})
    assert rotation_allowed({"in_vehicle": False})
    assert rotation_allowed({})


def test_vehicle_skill_requires_an_active_override_to_begin():
    skill = VehicleSkill()
    result = skill.begin(_active(), {"in_vehicle": False})
    assert result.status is SkillStatus.BLOCKED


def test_vehicle_skill_requires_configured_vehicle_actions():
    skill = VehicleSkill()
    result = skill.begin(_active(vehicle_actions=()), _state())
    assert result.status is SkillStatus.BLOCKED


def test_vehicle_skill_issues_bind_commands_for_each_configured_action():
    skill = VehicleSkill()
    result = skill.begin(_active(vehicle_actions=("VEHICLE_ACTION_1", "VEHICLE_ACTION_2")), _state())
    assert result.status is SkillStatus.RUNNING
    kinds_and_bindings = [(c.kind, c.binding) for c in result.commands]
    assert kinds_and_bindings == [("BIND", "VEHICLE_ACTION_1"), ("BIND", "VEHICLE_ACTION_2")]


def test_vehicle_skill_verifies_quest_progress_and_succeeds_on_credit():
    skill, state = VehicleSkill(), _active()
    skill.begin(state, _state())
    credited = {**_state(), "active_quests": [{"quest_id": 10, "objectives": [
        {"objective_id": "0", "current": 1, "required": 1, "is_complete": True},
    ]}]}
    result = skill.verify(state, credited, 2.)
    assert result.status is SkillStatus.SUCCESS


def test_vehicle_skill_fails_without_faking_success_when_vehicle_exits_mid_attempt():
    skill, state = VehicleSkill(), _active()
    skill.begin(state, _state())
    result = skill.verify(state, {"in_vehicle": False}, 2.)
    assert result.status is SkillStatus.FAILURE
