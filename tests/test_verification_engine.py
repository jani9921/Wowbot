from wowbot.runtime import FailureReason, SkillResult, SkillStatus, VerificationEngine


def test_running_result_remains_pending_without_success_projection():
    decision = VerificationEngine().project("LOOT", SkillResult(SkillStatus.RUNNING))
    assert decision.pending is True
    assert decision.reason is None


def test_success_reason_requires_a_verifier_success_result():
    decision = VerificationEngine().confirm(
        "QUEST_DIALOG", SkillResult(SkillStatus.SUCCESS, evidence=("quest:42:active",)))
    assert decision.success is True
    assert decision.reason == "quest_dialog_verified"
    assert decision.verifier == "DOMAIN_POSTCONDITION_VERIFIER"
    assert decision.evidence == ("quest:42:active",)


def test_bare_skill_success_cannot_bypass_postcondition_verifier():
    decision = VerificationEngine().project(
        "QUEST_DIALOG", SkillResult(SkillStatus.SUCCESS))
    assert decision.pending is True
    assert decision.success is False
    assert decision.reason == "awaiting_postcondition_verifier"


def test_typed_failure_is_preserved():
    decision = VerificationEngine().project(
        "LOOT", SkillResult(SkillStatus.FAILURE, FailureReason.CORPSE_NOT_FOUND))
    assert decision.success is False
    assert decision.reason == "corpse_not_found"
    assert decision.typed_reason is FailureReason.CORPSE_NOT_FOUND


def test_combat_client_error_compatibility_does_not_erase_typed_reason():
    decision = VerificationEngine().project(
        "COMBAT", SkillResult(SkillStatus.FAILURE, FailureReason.PATH_BLOCKED),
        {"ui_error": "Target not in line of sight"})
    assert decision.reason == "client_error:Target not in line of sight"
    assert decision.typed_reason is FailureReason.PATH_BLOCKED


def test_legacy_reason_is_used_only_for_failed_result_projection():
    decision = VerificationEngine().project(
        "INTERACT", SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                                metadata={"legacy_reason": "hover_identity_missing"}))
    assert decision.reason == "hover_identity_missing"
