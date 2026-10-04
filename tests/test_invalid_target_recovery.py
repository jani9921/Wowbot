from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, FailureReason, Intent, SkillStatus
from wowbot.skills.combat import CombatPhase, CombatSkill
from wowbot.skills.target_recovery import InvalidTargetRecoveryPolicy


def active(before):
    proposal = Proposal.make("COMBAT", "test", {"guid": "mob-1", "quest_ids": [7]})
    attempt = Attempt("a", proposal, before, "o", 1., 8., (),
                      Prediction("p", "a", "expected", 1., 8., "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("COMBAT", proposal.parameters, "mob-1"),
                  attempt=attempt, now=1., before_snapshot=before)
    return runtime.state


def spell():
    return {"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
            "is_harmful": True, "is_usable": True, "in_range": True,
            "cooldown_remaining": 0}


def hostile(guid="mob-1"):
    return {"guid": guid, "attackable": True, "targetable": True,
            "dead": False, "quest_relevant": True, "quest_ids": [7]}


def test_policy_reacquires_only_exact_alive_hostile_with_fresh_anchor():
    policy = InvalidTargetRecoveryPolicy()
    intended = hostile()
    intended["screen_position"] = {"x": .68, "y": .44, "sample_time": 3.}
    state = {"monotonic_time": 3.2, "target": hostile("wrong"),
             "entities": [intended]}
    decision = policy.assess(state, "mob-1", quest_ids=[7])
    assert decision.kind == "REACQUIRE_INTENDED"
    assert decision.anchor["x"] == .68

    intended["dead"] = True
    unavailable = policy.assess(state, "mob-1", quest_ids=[7])
    assert unavailable.kind == "SEARCH_LOCAL_CANDIDATE"
    assert unavailable.alternate_guid == "wrong"


def test_policy_alternate_is_advisory_and_must_be_quest_relevant():
    policy = InvalidTargetRecoveryPolicy()
    unrelated = hostile("other")
    unrelated["quest_relevant"] = False
    unrelated["quest_ids"] = [99]
    state = {"monotonic_time": 2., "entities": [unrelated]}
    assert policy.assess(state, "mob-1", quest_ids=[7]).kind == "UNAVAILABLE"

    unrelated["quest_ids"] = [7]
    decision = policy.assess(state, "mob-1", quest_ids=[7])
    assert decision.kind == "SEARCH_LOCAL_CANDIDATE"
    assert decision.alternate_guid == "other"


def test_combat_reacquires_same_guid_inside_same_attempt_then_resumes_rotation():
    before = {"target": hostile(), "actionbar": [spell()]}
    skill = CombatSkill()
    state = active(before)
    skill.begin(state, before, 1.)
    intended = hostile()
    intended["screen_position"] = {"x": .65, "y": .5, "sample_time": 2.}
    wrong = {"monotonic_time": 2., "target": hostile("wrong"),
             "entities": [intended], "actionbar": [spell()]}

    recovery = skill.verify(state, wrong, 2.)
    assert recovery.status is SkillStatus.RUNNING
    assert recovery.commands[-1].kind == "CLICK"
    assert recovery.metadata["target_recovery"] == "REACQUIRE_INTENDED"
    assert state.phase == CombatPhase.RECOVER_TARGET.value

    restored = {"monotonic_time": 2.2, "target": hostile(), "actionbar": [spell()]}
    resumed = skill.verify(state, restored, 2.2)
    assert resumed.commands and resumed.commands[0].binding == "ACTIONBUTTON1"
    assert state.skill_context["combat"]["target_recovery_pending"] is False


def test_combat_clears_wrong_selection_only_when_verified_binding_exists():
    class Bindings:
        @staticmethod
        def contains(action):
            return action == "CLEARTARGET"

    before = {"target": hostile(), "actionbar": [spell()]}
    skill = CombatSkill(Bindings())
    state = active(before)
    skill.begin(state, before, 1.)
    intended = hostile()
    intended["screen_position"] = {"x": .65, "y": .5, "sample_time": 2.}
    wrong = {"monotonic_time": 2., "target": hostile("wrong"),
             "entities": [intended], "actionbar": [spell()]}

    recovery = skill.verify(state, wrong, 2.)
    assert [command.binding for command in recovery.commands] == ["CLEARTARGET", None]
    assert recovery.commands[1].kind == "CLICK"


def test_combat_does_not_switch_to_alternate_inside_active_attempt():
    before = {"target": hostile(), "actionbar": [spell()]}
    skill = CombatSkill()
    state = active(before)
    skill.begin(state, before, 1.)
    alternate = hostile("other")
    wrong = {"monotonic_time": 2., "target": {}, "is_in_combat": True,
             "entities": [alternate], "actionbar": [spell()]}

    result = skill._invalid_target_recovery(state, wrong)
    assert result.status is SkillStatus.FAILURE
    assert result.reason is FailureReason.INVALID_TARGET
    assert result.metadata["suggested_alternate_guid"] == "other"
    assert result.commands == ()
