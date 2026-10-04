from wowbot.runtime import (
    CinematicSkipPolicy,
    FailureReason,
    InvalidationEvent,
    StateInvalidationPolicy,
    Supervisor,
    SupervisorDirectiveKind,
    SupervisorState,
)


def test_supervisor_blocks_and_enters_critical_recovery_while_cinematic_plays():
    supervisor = Supervisor()
    directive = supervisor.evaluate({"cinematic_playing": True}, None, 1.0)
    assert directive.kind is SupervisorDirectiveKind.BLOCK
    assert directive.reason is FailureReason.CINEMATIC_PLAYING
    assert directive.event.event_type == "CINEMATIC_STARTED"
    assert supervisor.snapshot()["state"] == SupervisorState.CRITICAL_RECOVERY.value


def test_supervisor_cannot_exit_critical_recovery_while_cinematic_still_playing():
    supervisor = Supervisor()
    supervisor.evaluate({"cinematic_playing": True}, None, 1.0)
    assert not supervisor.can_exit({"cinematic_playing": True})
    assert supervisor.can_exit({"cinematic_playing": False})


def test_supervisor_death_still_preempts_a_playing_cinematic():
    supervisor = Supervisor()
    supervisor.evaluate({"cinematic_playing": True}, None, 1.0)
    directive = supervisor.evaluate({"cinematic_playing": True, "is_dead": True}, None, 2.0)
    assert directive.reason is FailureReason.PLAYER_DEAD
    assert supervisor.snapshot()["state"] == SupervisorState.DEATH_RECOVERY.value


def test_normal_operation_resumes_once_cinematic_flag_clears():
    supervisor = Supervisor()
    supervisor.evaluate({"cinematic_playing": True}, None, 1.0)
    directive = supervisor.evaluate({"cinematic_playing": False}, None, 2.0)
    assert directive.kind is SupervisorDirectiveKind.CONTINUE
    assert supervisor.snapshot()["state"] == SupervisorState.IDLE.value


def _inv_state(**updates):
    value = {
        "active_quests": [], "loading": False, "map_id": 1, "is_dead": False,
        "phase_id": 1, "floor_id": 1, "in_vehicle": False,
        "player_world_position": {"x": 0., "y": 0., "z": 0.},
        "cinematic_playing": False,
    }
    value.update(updates)
    return value


def test_cinematic_invalidation_event_fires_on_the_falling_edge_not_the_start():
    policy = StateInvalidationPolicy()
    before = policy.context(_inv_state())
    during = policy.context(_inv_state(cinematic_playing=True))
    after = policy.context(_inv_state(cinematic_playing=False))

    assert InvalidationEvent.CINEMATIC not in policy.detect(before, during)
    assert InvalidationEvent.CINEMATIC in policy.detect(during, after)


def test_cinematic_invalidation_forces_objective_refresh_unlike_plain_teleport():
    policy = StateInvalidationPolicy()
    decision = policy.decision(InvalidationEvent.CINEMATIC)
    assert decision.invalidate_objective is True
    assert decision.clear_visual_context is True
    assert decision.reset_navigation is True


def test_skip_policy_disabled_by_default_never_proposes_a_skip():
    policy = CinematicSkipPolicy()
    decision = policy.evaluate(cinematic_playing=True, now=1.0)
    assert decision.should_skip is False
    assert decision.reason == "skip_policy_disabled"


def test_enabled_skip_policy_is_bounded_and_does_not_spam():
    policy = CinematicSkipPolicy(enabled=True, min_interval_seconds=3.0, max_attempts=1)
    first = policy.evaluate(cinematic_playing=True, now=1.0)
    assert first.should_skip is True
    second = policy.evaluate(cinematic_playing=True, now=1.5)
    assert second.should_skip is False
    assert second.reason == "attempt_budget_exhausted"


def test_enabled_skip_policy_respects_minimum_interval_across_cinematics():
    policy = CinematicSkipPolicy(enabled=True, min_interval_seconds=5.0, max_attempts=2)
    policy.evaluate(cinematic_playing=True, now=1.0)
    too_soon = policy.evaluate(cinematic_playing=True, now=2.0)
    assert too_soon.should_skip is False
    assert too_soon.reason == "min_interval_not_elapsed"
    later = policy.evaluate(cinematic_playing=True, now=6.0)
    assert later.should_skip is True


def test_skip_policy_never_proposes_when_no_cinematic_is_playing():
    policy = CinematicSkipPolicy(enabled=True)
    decision = policy.evaluate(cinematic_playing=False, now=1.0)
    assert decision.should_skip is False
    assert decision.reason == "no_cinematic_playing"


def test_reset_refills_attempt_budget_for_the_next_cinematic():
    policy = CinematicSkipPolicy(enabled=True, min_interval_seconds=0.0, max_attempts=1)
    policy.evaluate(cinematic_playing=True, now=1.0)
    exhausted = policy.evaluate(cinematic_playing=True, now=1.1)
    assert exhausted.should_skip is False
    policy.reset()
    refreshed = policy.evaluate(cinematic_playing=True, now=10.0)
    assert refreshed.should_skip is True


# V4-067 wiring: CinematicSkipPolicy consumed as a live Supervisor attribute.

def test_supervisor_owns_a_disabled_skip_policy_by_default():
    supervisor = Supervisor()
    decision = supervisor.cinematic_skip_decision(cinematic_playing=True, now=1.0)
    assert decision.should_skip is False
    assert decision.reason == "skip_policy_disabled"


def test_supervisor_constructed_with_skip_enabled_authorizes_one_attempt():
    supervisor = Supervisor(cinematic_skip_enabled=True)
    supervisor.evaluate({"cinematic_playing": True}, None, 1.0)
    decision = supervisor.cinematic_skip_decision(cinematic_playing=True, now=1.0)
    assert decision.should_skip is True
    assert decision.reason == "skip_attempt_authorized"


def test_supervisor_skip_budget_refills_on_a_fresh_cinematic_rising_edge():
    supervisor = Supervisor(cinematic_skip_enabled=True)
    supervisor.evaluate({"cinematic_playing": True}, None, 1.0)
    exhausted = supervisor.cinematic_skip_decision(cinematic_playing=True, now=1.0)
    assert exhausted.should_skip is True
    again = supervisor.cinematic_skip_decision(cinematic_playing=True, now=1.0)
    assert again.should_skip is False
    assert again.reason == "attempt_budget_exhausted"

    # Cinematic ends, then a new one starts -- state falls back to IDLE and
    # re-enters CRITICAL_RECOVERY, which is the rising edge that refills
    # the budget.
    supervisor.evaluate({"cinematic_playing": False}, None, 2.0)
    supervisor.evaluate({"cinematic_playing": True}, None, 3.0)
    refreshed = supervisor.cinematic_skip_decision(cinematic_playing=True, now=3.0)
    assert refreshed.should_skip is True


def test_supervisor_skip_budget_does_not_refill_while_still_in_the_same_cinematic():
    supervisor = Supervisor(cinematic_skip_enabled=True)
    supervisor.evaluate({"cinematic_playing": True}, None, 1.0)
    supervisor.cinematic_skip_decision(cinematic_playing=True, now=1.0)
    # Still the same cinematic -- re-evaluating BLOCK must not reset the
    # attempt budget mid-cinematic.
    supervisor.evaluate({"cinematic_playing": True}, None, 1.2)
    still_exhausted = supervisor.cinematic_skip_decision(cinematic_playing=True, now=1.2)
    assert still_exhausted.should_skip is False
    assert still_exhausted.reason == "attempt_budget_exhausted"
