"""Executable M2.16 invariant gate."""
from pathlib import Path

from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, FailureReason, Intent, SkillStatus
from wowbot.skills.combat import CombatSkill
from wowbot.skills.interact import InteractSkill
from wowbot.skills.target_recovery import InvalidTargetRecoveryPolicy
from wowbot.verification.combat import CombatVerifier


def active(skill, guid, before):
    proposal = Proposal.make(skill, "M2 assertion", {"guid": guid})
    attempt = Attempt("a", proposal, before, "o", 1., 10., (),
                      Prediction("p", "a", "expected", 1., 10., "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent(skill, proposal.parameters, guid), attempt=attempt,
                  now=1., before_snapshot=before)
    return runtime.state


def hostile(guid="mob-1"):
    return {"guid": guid, "attackable": True, "dead": False, "health": 10}


def test_m2_no_cast_without_required_target_and_no_kill_below_threshold():
    skill = CombatSkill()
    state = active("COMBAT", "mob-1", {"target": hostile()})
    missing = skill.begin(state, {"target": {}, "actionbar": [{
        "kind": "spell", "action": "ACTIONBUTTON1", "is_harmful": True,
        "is_usable": True}]}, 1.)
    assert missing.status is SkillStatus.FAILURE and missing.commands == ()

    weak = CombatVerifier().evaluate(
        {"is_in_combat": True, "target": hostile()},
        {"is_in_combat": False, "target": hostile()}, expected_guid="mob-1")
    assert not weak.success and weak.confidence < CombatVerifier.DEAD_THRESHOLD


def test_m2_los_recovery_budget_terminates_and_preserves_intended_identity():
    skill = CombatSkill()
    before = {"target": hostile(), "actionbar": []}
    state = active("COMBAT", "mob-1", before)
    skill.begin(state, before, 1.)
    context = state.skill_context["combat"]
    context["local_recovery_attempts"]["LINE_OF_SIGHT"] = 3
    result = skill._local_recovery_request(
        state, {"target": hostile()}, FailureReason.LINE_OF_SIGHT, 2.)
    assert result.status is SkillStatus.FAILURE
    assert result.metadata["los_recovery_attempts"] == 3

    candidate = hostile()
    candidate["screen_position"] = {"x": .6, "y": .5, "sample_time": 2.}
    decision = InvalidTargetRecoveryPolicy().assess(
        {"monotonic_time": 2., "entities": [candidate]}, "mob-1")
    assert decision.kind == "REACQUIRE_INTENDED"
    assert decision.intended_guid == "mob-1"


def test_m2_range_recovery_cannot_exceed_its_finite_budget():
    skill = CombatSkill()
    before = {"target": hostile(), "actionbar": []}
    state = active("COMBAT", "mob-1", before)
    skill.begin(state, before, 1.)
    context = state.skill_context["combat"]
    context["world_approach_attempts"] = skill.RANGE_DIRECT_APPROACH_BUDGET
    context["local_recovery_attempts"]["OUT_OF_RANGE"] = 2
    current = {"monotonic_time": 2.,
               "target": {**hostile(),
                           "screen_position": {"x": .6, "y": .5, "sample_time": 2.}}}
    result = skill._local_recovery_request(
        state, current, FailureReason.OUT_OF_RANGE, 2.)
    assert result.status is SkillStatus.FAILURE
    assert result.metadata["target_unreachable"] is True


def test_m2_interaction_click_is_never_success_without_observed_effect():
    before = {"target": {"guid": "npc-1"}, "quest_ui": {"open": False}}
    state = active("INTERACT", "npc-1", before)
    skill = InteractSkill()
    launched = skill.begin(state, before)
    assert launched.commands
    verified = skill.verify(state, before, 1.1)
    assert verified.status is SkillStatus.RUNNING


def test_m2_combat_modules_have_no_direct_input_or_movement_authority():
    root = Path("src/wowbot")
    combat = (root / "skills" / "combat.py").read_text(encoding="utf-8")
    runtime = (root / "skills" / "combat_runtime.py").read_text(encoding="utf-8")
    forbidden = ("windows_input", "InputExecutor", "SendInput", "keybd_event")
    assert not any(token in combat for token in forbidden)
    assert not any(token in runtime for token in forbidden)
    assert "self.navigation." in runtime
    assert "local_combat_reposition" in runtime
