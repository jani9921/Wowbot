from wowbot.runtime import FailureEscalationStage, FailureManager, FailureReason


def test_failure_manager_enforces_per_domain_retry_budget_and_correlation_chain():
    manager = FailureManager()
    decisions = [manager.record_failure(correlation_id="move:one", skill="MOVE",
                                        reason=FailureReason.NO_PROGRESS, at=float(index))
                 for index in range(1, 5)]

    assert [item.retry_allowed for item in decisions] == [True, True, True, False]
    assert decisions[-1].domain_recovery_required is True
    assert decisions[-1].replan_required is False
    assert decisions[-1].escalation_stage is FailureEscalationStage.DOMAIN_RECOVERY
    assert decisions[-1].record.attempt_number == 4
    assert decisions[-1].record.domain == "movement"


def test_failure_manager_success_clears_only_its_own_chain():
    manager = FailureManager()
    manager.record_failure(correlation_id="a", skill="INTERACT", reason=FailureReason.NO_RESPONSE, at=1.)
    manager.record_failure(correlation_id="b", skill="COMBAT", reason=FailureReason.OUT_OF_RANGE, at=1.)
    manager.record_success("a")

    snapshot = manager.snapshot()
    assert "a" not in snapshot["active_chains"]
    assert snapshot["active_chains"]["b"] == 1


def test_failure_manager_terminal_reason_never_retries():
    decision = FailureManager().record_failure(
        correlation_id="dead", skill="MOVE", reason=FailureReason.PLAYER_DEAD, at=1.)
    assert decision.retry_allowed is False
    assert decision.domain_recovery_required is True
    assert decision.recovery_action == "DEATH_RECOVERY"
    assert decision.backoff_seconds == 0


def test_failure_manager_normalizes_and_maps_typed_recovery():
    manager = FailureManager()
    decision = manager.record_failure(
        correlation_id="los", skill="COMBAT", reason="line of sight", at=1.)
    assert decision.record.reason is FailureReason.LINE_OF_SIGHT
    assert decision.recovery_action == "LOS_REPOSITION"


def test_failure_escalation_is_finite_and_reaches_goal_failed():
    manager = FailureManager()
    decisions = [manager.record_failure(
        correlation_id="combat:one", skill="COMBAT",
        reason=FailureReason.OUT_OF_RANGE, at=float(index))
        for index in range(1, 8)]
    assert [item.escalation_stage for item in decisions] == [
        FailureEscalationStage.SKILL_RETRY,
        FailureEscalationStage.SKILL_RETRY,
        FailureEscalationStage.DOMAIN_RECOVERY,
        FailureEscalationStage.PLANNER_REPLAN,
        FailureEscalationStage.GOAL_ALTERNATIVE,
        FailureEscalationStage.GOAL_FAILED,
        FailureEscalationStage.GOAL_FAILED,
    ]
    assert decisions[-1].goal_failed is True
    assert decisions[-2].retry_allowed is False


def test_failure_storage_is_bounded_without_resetting_attempt_count():
    manager = FailureManager()
    for index in range(40):
        decision = manager.record_failure(
            correlation_id="same", skill="MOVE",
            reason=FailureReason.NO_PROGRESS, at=float(index))
    assert decision.record.attempt_number == 40
    assert manager.snapshot()["active_chains"]["same"] == 40
    assert len(manager.recent(correlation_id="same", limit=100)) == 16
