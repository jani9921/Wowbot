from wowbot.runtime import (ActiveSkillRuntime, FailureReason, Intent, Supervisor,
                            SupervisorDirectiveKind, SupervisorState)


def active(skill="INTERACT"):
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent(skill), attempt=object(), now=1)
    return runtime.state


def test_supervisor_preserves_running_skill_without_explicit_interrupt():
    directive = Supervisor().evaluate({"is_in_combat": False}, active(), 2)
    assert directive.kind is SupervisorDirectiveKind.CONTINUE


def test_supervisor_interrupts_interaction_for_survival_combat():
    directive = Supervisor().evaluate({"is_in_combat": True}, active("INTERACT"), 2)
    assert directive.kind is SupervisorDirectiveKind.REPLAN
    assert directive.cancel_active and directive.suspend_active
    assert directive.reason is FailureReason.INTERRUPTED


def test_supervisor_resumes_one_still_safe_interrupted_intent_only_after_combat():
    supervisor = Supervisor()
    running = active("INTERACT")
    event = supervisor.suspend(running, 2., FailureReason.INTERRUPTED)
    assert event and event.event_type == "SKILL_SUSPENDED"
    assert supervisor.resume_candidate({"is_in_combat": True}, 3.) is None
    candidate = supervisor.resume_candidate({"is_in_combat": False}, 3.)
    assert candidate and candidate.intent.skill_type == "INTERACT"
    resumed = supervisor.consume_resume(candidate.token, 3.)
    assert resumed and resumed.event_type == "SKILL_RESUMED"
    assert supervisor.resume_candidate({}, 4.) is None


def test_supervisor_does_not_interrupt_combat_with_combat():
    directive = Supervisor().evaluate({"is_in_combat": True}, active("COMBAT"), 2)
    assert directive.kind is SupervisorDirectiveKind.CONTINUE


def test_supervisor_death_and_loading_are_blocking_before_planning():
    death = Supervisor().evaluate({"is_dead": True, "loading": True}, active("MOVE"), 2)
    assert death.kind is SupervisorDirectiveKind.BLOCK
    assert death.reason is FailureReason.PLAYER_DEAD
    loading = Supervisor().evaluate({"loading": True}, None, 2)
    assert loading.kind is SupervisorDirectiveKind.BLOCK


def test_supervisor_safety_checkpoint_requires_external_stabilization_not_input():
    supervisor = Supervisor()
    checkpoint = supervisor.mark_safety_pause(FailureReason.PLAYER_DEAD, 2., goal_id="quest")
    assert checkpoint.required_condition == "PLAYER_ALIVE_AND_LOADING_STABLE"
    assert supervisor.snapshot()["recovery"]["goal_id"] == "quest"
    # The supervisor merely gates/reports. It has no command or executor path.
    assert supervisor.evaluate({"is_dead": False, "loading": False}, None, 3.).kind is SupervisorDirectiveKind.CONTINUE
    assert supervisor.snapshot()["recovery"] is None


def test_supervisor_publishes_diagnostic_ownership_without_creating_a_second_controller():
    supervisor = Supervisor()
    assert supervisor.evaluate({}, active("MOVE"), 2).kind is SupervisorDirectiveKind.CONTINUE
    snapshot = supervisor.snapshot()
    assert snapshot["state"] == SupervisorState.NAVIGATION.value
    assert snapshot["recent_transitions"][-1]["to"] == SupervisorState.NAVIGATION.value

    directive = supervisor.evaluate({"connection_lost": True}, active("MOVE"), 3)
    assert directive.kind is SupervisorDirectiveKind.BLOCK
    assert directive.reason is FailureReason.TELEMETRY_STALE
    assert supervisor.snapshot()["state"] == SupervisorState.DISCONNECT_RECOVERY.value


def test_every_required_supervisor_state_has_a_complete_immutable_contract():
    specs = Supervisor.state_specs()
    assert {spec.state_id for spec in specs} == set(SupervisorState)
    assert [spec.priority for spec in specs] == sorted(spec.priority for spec in specs)
    for spec in specs:
        assert isinstance(spec.priority, int)
        assert isinstance(spec.interruptible, bool)
        assert spec.timeout is None or spec.timeout > 0
        assert spec.retry_policy.max_attempts >= 0
        assert spec.retry_policy.backoff_seconds >= 0


def test_minimum_preemption_matrix_is_explicit_and_priority_safe():
    normal = {
        SupervisorState.IDLE, SupervisorState.EXPLORATION,
        SupervisorState.NAVIGATION, SupervisorState.QUEST_OBJECTIVE,
        SupervisorState.INTERACTION, SupervisorState.LOOT,
    }
    assert all(Supervisor.can_preempt(state, SupervisorState.DEATH_RECOVERY)
               for state in SupervisorState if state is not SupervisorState.DEATH_RECOVERY)
    assert all(Supervisor.can_preempt(state, SupervisorState.DISCONNECT_RECOVERY)
               for state in SupervisorState
               if state not in {SupervisorState.DEATH_RECOVERY,
                                SupervisorState.DISCONNECT_RECOVERY})
    assert all(Supervisor.can_preempt(state, SupervisorState.CRITICAL_RECOVERY)
               for state in normal)
    assert all(Supervisor.can_preempt(state, SupervisorState.COMBAT)
               for state in normal)
    assert Supervisor.can_preempt(SupervisorState.NAVIGATION,
                                  SupervisorState.STUCK_RECOVERY)
    assert not Supervisor.can_preempt(SupervisorState.COMBAT,
                                      SupervisorState.STUCK_RECOVERY)
    assert not Supervisor.can_preempt(SupervisorState.DEATH_RECOVERY,
                                      SupervisorState.DISCONNECT_RECOVERY)


def test_supervisor_state_lifecycle_requires_evidence_and_cleared_exit_gate():
    supervisor = Supervisor()
    assert not supervisor.enter(SupervisorState.DEATH_RECOVERY, 1., "invalid", {})
    assert supervisor.enter(SupervisorState.DEATH_RECOVERY, 2., "player_dead",
                            {"is_dead": True})
    assert not supervisor.can_exit({"is_dead": True})
    assert not supervisor.exit({"is_dead": True}, 3., "still_dead")
    assert supervisor.exit({"is_dead": False, "loading": False}, 4., "revived")
    assert supervisor.snapshot()["state"] == SupervisorState.IDLE.value


def test_supervisor_tick_is_same_single_gate_and_snapshot_exposes_state_contract():
    supervisor = Supervisor()
    directive = supervisor.tick({"is_in_combat": True}, active("INTERACT"), 2.)
    assert directive.kind is SupervisorDirectiveKind.REPLAN
    snapshot = supervisor.snapshot()
    assert snapshot["state"] == SupervisorState.COMBAT.value
    assert snapshot["state_contract"]["state_id"] == SupervisorState.COMBAT.value
    assert snapshot["state_contract"]["priority"] > Supervisor().state_spec(
        SupervisorState.NAVIGATION).priority
