from types import SimpleNamespace

from wowbot.runtime import ActiveSkillRuntime, FailureReason, Intent, SkillStatus
from wowbot.skills import CombatSkill


GUID = "Creature-0-1-2-3-42-1"


def state(**updates):
    value = {
        "target": {"guid": GUID, "attackable": True, "dead": False,
                   "health": 100, "max_health": 100},
        "health": 100, "max_health": 100,
        "power": 100, "max_power": 100,
        "actionbar": [], "events": [],
    }
    value.update(updates)
    return value


def active(before):
    runtime = ActiveSkillRuntime()
    attempt = SimpleNamespace(deadline=10.)
    return runtime.start(
        intent=Intent("COMBAT", {"guid": GUID}, GUID),
        attempt=attempt, now=1., before_snapshot=before)


def test_running_combat_skill_uses_canonical_resource_error_classification():
    before = state()
    skill = CombatSkill()
    active_state = active(before)
    skill.begin(active_state, before, 1.)
    result = skill.verify(active_state, state(power=0), 2.)
    assert result.status is SkillStatus.FAILURE
    assert result.reason is FailureReason.NOT_ENOUGH_RESOURCE
    assert active_state.skill_context["combat"]["last_error_classification"] == "NOT_ENOUGH_RESOURCE"


def test_combat_history_is_bounded_and_unknown_does_not_become_a_false_failure():
    before = state()
    skill = CombatSkill()
    active_state = active(before)
    skill.begin(active_state, before, 1.)
    for index in range(20):
        result = skill.verify(active_state, state(), 1.1 + index*.1)
        assert result.status is SkillStatus.RUNNING
    context = active_state.skill_context["combat"]
    assert len(context["observation_history"]) == 12
    assert context["last_error_classification"] == "UI_UNKNOWN"


def test_one_missing_target_frame_is_diagnostic_not_terminal_target_loss():
    before = state()
    skill = CombatSkill()
    active_state = active(before)
    skill.begin(active_state, before, 1.)
    result = skill.verify(active_state, state(target=None, is_in_combat=False), 2.)
    assert result.status is SkillStatus.RUNNING
    assert active_state.skill_context["combat"]["last_error_classification"] == "TARGET_LOST"
