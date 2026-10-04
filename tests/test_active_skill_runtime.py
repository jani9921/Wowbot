import pytest

from types import SimpleNamespace

from wowbot.runtime import (ActiveSkillRuntime, FailureReason, Intent,
                            SkillLifecycleState, SkillResult, SkillStatus)


def test_active_skill_runtime_has_exactly_one_running_authority():
    runtime = ActiveSkillRuntime()
    first = object()
    runtime.start(intent=Intent("INTERACT", {"guid": "npc-1"}), attempt=first, now=1,
                  before_snapshot={"target": None})
    assert runtime.exists and runtime.attempt is first
    with pytest.raises(RuntimeError):
        runtime.start(intent=Intent("MOVE"), attempt=object(), now=2)


def test_active_skill_runtime_records_typed_terminal_result_once():
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("MOVE"), attempt=object(), now=1)
    finished = runtime.finish(SkillResult(SkillStatus.FAILURE, FailureReason.STUCK,
                                          retryable=True, replan_required=True), 2)
    assert finished.status is SkillStatus.FAILURE
    assert finished.failure_history == [FailureReason.STUCK]
    with pytest.raises(RuntimeError):
        runtime.finish(SkillResult(SkillStatus.SUCCESS), 3)
    assert runtime.finalize() is finished
    assert runtime.state is None


def test_active_skill_runtime_cancel_is_safe_and_idempotent():
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("COMBAT"), attempt=object(), now=1)
    cancelled = runtime.cancel(2)
    assert cancelled and cancelled.status is SkillStatus.CANCELLED
    assert runtime.cancel(3) is cancelled
    assert [event.event_type for event in runtime.drain_events()] == [
        "SKILL_STARTED", "SKILL_CANCELLED"]


def test_active_skill_exposes_complete_typed_context_and_lifecycle():
    runtime = ActiveSkillRuntime()
    attempt = SimpleNamespace(deadline=9.)
    state = runtime.start(
        intent=Intent("INTERACT", {"guid": "npc-1"}), attempt=attempt, now=1.,
        skill_context={"action_id": "action:1", "world_snapshot_version": 42})
    assert state.context.skill_id == state.runtime_id
    assert state.context.correlation_id == "action:1"
    assert state.context.parameters == {"guid": "npc-1"}
    assert state.context.started_at == 1.
    assert state.context.deadline == 9.
    assert state.context.attempt is attempt
    assert state.context.world_snapshot_version == 42
    assert state.lifecycle is SkillLifecycleState.RUNNING
    assert [transition.state for transition in state.lifecycle_history] == [
        SkillLifecycleState.CREATED,
        SkillLifecycleState.WAITING_PRECONDITIONS,
        SkillLifecycleState.RUNNING,
    ]


def test_active_skill_verification_retry_recovery_and_preemption_are_explicit():
    runtime = ActiveSkillRuntime()
    state = runtime.start(intent=Intent("MOVE"), attempt=object(), now=1.)
    runtime.begin_verification(2.)
    assert state.lifecycle is SkillLifecycleState.VERIFYING
    runtime.record_retry(FailureReason.NO_PROGRESS)
    assert state.lifecycle is SkillLifecycleState.RUNNING
    assert SkillLifecycleState.RETRYING in {
        transition.state for transition in state.lifecycle_history}
    runtime.begin_recovery(3., FailureReason.STUCK)
    assert state.lifecycle is SkillLifecycleState.RECOVERING
    runtime.resume_running(4., "recovery_verified")
    cancelled = runtime.cancel(5., FailureReason.INTERRUPTED)
    assert cancelled.lifecycle is SkillLifecycleState.PREEMPTED
    assert cancelled.context.cancellation_token.cancelled is True
    assert cancelled.context.cancellation_token.reason is FailureReason.INTERRUPTED


def test_skill_can_remain_waiting_until_preconditions_are_explicitly_satisfied():
    runtime = ActiveSkillRuntime()
    state = runtime.start(
        intent=Intent("INTERACT"), attempt=object(), now=1.,
        preconditions_satisfied=False)
    assert state.lifecycle is SkillLifecycleState.WAITING_PRECONDITIONS
    runtime.mark_preconditions_satisfied(2.)
    assert state.lifecycle is SkillLifecycleState.RUNNING
