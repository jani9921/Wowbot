from wowbot.navigation import ProgressPhase, StuckResolutionState, StuckResolver


def test_stuck_resolver_observes_before_any_recovery_step():
    resolver = StuckResolver()
    started = resolver.begin("reach:alpha", 1.)
    assert started.state is StuckResolutionState.STOP_AND_OBSERVE
    assert started.action == "STOP_AND_OBSERVE"
    next_step = resolver.observe_progress(ProgressPhase.HARD_STUCK, 2.)
    assert next_step.state is StuckResolutionState.BACKWARD
    assert next_step.action == "BACKWARD"


def test_stuck_resolver_only_advances_after_previous_failure_and_stops_on_progress():
    resolver = StuckResolver()
    resolver.begin("reach:alpha", 1.)
    resolver.observe_progress(ProgressPhase.HARD_STUCK, 2.)
    # Live 2026-10-03: a back-off that did not move (wedged) is followed by
    # the next physical escape; MARK_DANGER follows a back-off that worked
    # and a repeated stuck (test_stuck_wedged_20261003).
    assert resolver.report_step_result(success=False, now=3.).state is StuckResolutionState.JUMP_FORWARD
    verified = resolver.observe_progress(ProgressPhase.RECOVERED, 4.)
    assert verified.terminal
    assert verified.reason == "STUCK_RECOVERED"
    assert resolver.snapshot()["state"] == StuckResolutionState.IDLE.value


def test_stuck_resolver_escalates_replan_scope_without_input_commands():
    resolver = StuckResolver()
    resolver.begin("reach:alpha", 1.)
    directive = resolver.observe_progress(ProgressPhase.HARD_STUCK, 2.)
    while directive.state is not StuckResolutionState.LOCAL_REPLAN:
        directive = resolver.report_step_result(success=False, now=3. + resolver.step_index)
    assert directive.replan_scope == "LOCAL"
    assert directive.action == "LOCAL_REPLAN"


def test_every_recovery_step_requires_one_prior_failed_result_and_verify_gate():
    resolver = StuckResolver()
    resolver.begin("reach:full", 1.)
    premature = resolver.report_step_result(success=False, now=1.1)
    assert premature.action is None
    assert premature.reason == "no_recovery_step_awaiting_result"
    directive = resolver.observe_progress(ProgressPhase.HARD_STUCK, 2.)
    actions = [directive.action]
    # Re-observing the same hard-stuck state is not permission to skip ahead.
    repeated = resolver.observe_progress(ProgressPhase.HARD_STUCK, 2.1)
    assert repeated.state is StuckResolutionState.BACKWARD
    assert repeated.action is None
    while not directive.terminal:
        directive = resolver.report_step_result(success=False, now=3.+len(actions))
        if directive.action:
            actions.append(directive.action)
    assert actions == [
        # Every failure: physical escapes first (live 2026-10-03, wedged),
        # then the learning/replanning steps; each step exactly once.
        "BACKWARD", "JUMP_FORWARD", "STRAFE", "TURN", "MARK_DANGER",
        "REBUILD_CORRIDOR", "NEW_LOCAL_WAYPOINT", "LOCAL_REPLAN",
        "GLOBAL_REPLAN", "BLACKLIST_TEMP",
    ]
    assert directive.state is StuckResolutionState.FAILED
    transitions = resolver.snapshot()["recent_transitions"]
    assert any(item["to"] == "VERIFY_RECOVERY" for item in transitions)
    assert resolver.snapshot()["awaiting_step_result"] is False
