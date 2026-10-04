"""Wedged character: physical escapes before replanning (live 2026-10-03 23:49)."""
from wowbot.navigation.stuck_resolver import StuckResolver
from wowbot.navigation.progress import ProgressPhase


def _start():
    resolver = StuckResolver()
    resolver.begin("c1", 1., position=(0., 0.))
    first = resolver.observe_progress(ProgressPhase.HARD_STUCK, 2.)
    assert first.action == "BACKWARD"
    return resolver


def test_a_back_off_that_did_not_move_is_followed_by_other_physical_escapes():
    resolver = _start()
    actions = []
    for now in (3., 4., 5.):
        actions.append(resolver.report_step_result(success=False, now=now).action)
    assert actions == ["JUMP_FORWARD", "STRAFE", "TURN"]
    # Only then the planning steps.
    assert resolver.report_step_result(success=False, now=6.).action == "MARK_DANGER"


def test_a_successful_back_off_and_repeated_stuck_still_learns_the_obstacle():
    resolver = _start()
    assert resolver.report_step_result(success=True, now=3.).terminal
    resolver.begin("c2", 10., position=(1., 0.))
    assert resolver.observe_progress(ProgressPhase.HARD_STUCK, 11.).action == "MARK_DANGER"
