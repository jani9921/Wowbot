"""Recovery/cancellation must not carry an old airborne timer into a new MOVE."""
import pytest

from test_fall_off_spiral_replan_20261006 import _navigation, _falling, _state


@pytest.mark.parametrize('boundary', ['cancel', 'reset', 'new_request'])
def test_a_grounded_new_move_cannot_inherit_the_previous_fall_timer(boundary):
    nav, _ = _navigation()
    original = dict(nav._active_request.destination)
    assert nav.observe(_falling(2.), 'old-airborne', 2.).reason == 'fall_pending'
    if boundary == 'cancel':
        nav.cancel_movement()
    elif boundary == 'reset':
        nav.reset(keep_floor=True)
    grounded = _state(5.)
    grounded['movement']['falling'] = False
    nav.start_skill_request('MOVE', original, grounded, 'new-grounded-reach', 5.)
    # The prior attempt's landing was observed during RECOVER, not nav.observe.
    # A single fresh airborne sample cannot become a three-second fall.
    result = nav.observe(_falling(5.1), 'new-brief-step', 5.1)
    assert not result.terminal and result.reason == 'fall_pending'
    assert not nav._fall_hazards
    assert nav.command(_falling(5.1), 'new-brief-step', 5.1) == ()


def test_cancel_removes_only_episode_timer_not_confirmed_route_hazards():
    nav, _ = _navigation()
    nav.observe(_falling(2.), 'first', 2.)
    assert nav.observe(_falling(4.1), 'sustained', 4.1).reason == 'fall_in_progress'
    hazards = list(nav._fall_hazards)
    nav.cancel_movement()
    assert nav._falling_since is None
    assert nav._fall_hazards == hazards and hazards


def test_replacing_a_route_during_the_same_sustained_fall_does_not_restart_its_clock():
    nav, _ = _navigation()
    original = dict(nav._active_request.destination)
    nav.observe(_falling(2.), 'first', 2.)
    nav.start_skill_request('MOVE', original, _falling(3.5), 'same-fall-replan', 3.5)
    result = nav.observe(_falling(4.1), 'later', 4.1)
    assert result.terminal and result.reason == 'fall_in_progress'
