from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import TargetSkill


def active(params, *, deadline=5):
    proposal = Proposal.make("TARGET", "test", params)
    attempt = Attempt("a", proposal, {"target": {}}, "o", 1, deadline, (),
                      Prediction("p", "a", "target", 1, deadline, "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("TARGET", params, params.get("guid")), attempt=attempt, now=1)
    return runtime.state


def test_target_skill_requires_safe_explicit_target_input():
    skill = TargetSkill()
    result = skill.begin(active({"guid": "npc-1"}))
    assert result.status is SkillStatus.FAILURE


def test_target_skill_clicks_then_requires_exact_guid_confirmation():
    skill = TargetSkill()
    state = active({"guid": "npc-1", "x": .4, "y": .5})
    started = skill.begin(state)
    assert started.status is SkillStatus.RUNNING and started.commands[0].kind == "CLICK"
    wrong = skill.verify(state, {"target": {"guid": "npc-wrong"}}, 2)
    assert wrong.status is SkillStatus.FAILURE
    assert wrong.reason.value == "IDENTITY_UNCERTAIN"


def test_target_skill_waits_for_expected_guid_then_succeeds():
    skill = TargetSkill()
    state = active({"guid": "npc-1", "x": .4, "y": .5})
    skill.begin(state)
    assert skill.verify(state, {"target": {}}, 2).status is SkillStatus.RUNNING
    assert skill.verify(state, {"target": {"guid": "npc-1", "name": "Jaina"}}, 3).status is SkillStatus.SUCCESS


def test_ground_truth_handoff_clicks_current_cursor_without_repositioning_it():
    skill = TargetSkill()
    state = active({"guid": "npc-1", "x": .4, "y": .5,
                    "ground_truth_handoff": True, "click_current_cursor": True})
    started = skill.begin(state)
    assert started.status is SkillStatus.RUNNING
    assert started.commands[0].kind == "CLICK_CURRENT_CURSOR"
    assert started.commands[0].x is None and started.commands[0].y is None


def test_target_skill_times_out_with_typed_target_not_found():
    skill = TargetSkill()
    state = active({"guid": "npc-1", "x": .4, "y": .5}, deadline=3)
    skill.begin(state)
    result = skill.verify(state, {"target": {}}, 3)
    assert result.status is SkillStatus.FAILURE
    assert result.reason.value == "TARGET_NOT_FOUND"


def test_previous_target_still_reported_right_after_the_click_is_not_a_wrong_click():
    # Live 2026-10-04 (Giant Boar): verify ran ~0.1 s after the click while the
    # addon still reported the previously selected cadaver -> IDENTITY_UNCERTAIN.
    skill = TargetSkill()
    params = {"guid": "ClientActor-3-1-80", "x": .4, "y": .5}
    proposal = Proposal.make("TARGET", "test", params)
    attempt = Attempt("a", proposal, {"target": {"guid": "ClientActor-3-1-79"}}, "o", 1, 5, (),
                      Prediction("p", "a", "target", 1, 5, "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("TARGET", params, params["guid"]), attempt=attempt, now=1,
                  before_snapshot=attempt.baseline)
    state = runtime.state
    skill.begin(state)
    assert skill.verify(state, {"target": {"guid": "ClientActor-3-1-79"}}, 1.1).status is SkillStatus.RUNNING
    assert skill.verify(state, {"target": {"guid": "ClientActor-3-1-80"}}, 1.4).status is SkillStatus.SUCCESS
    late = skill.verify(state, {"target": {"guid": "ClientActor-3-1-79"}}, 5)
    assert late.status is SkillStatus.FAILURE
