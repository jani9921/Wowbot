"""DESIGN-041: classify_combat_error() covers the spec's 11-value taxonomy."""
from wowbot.runtime import FailureReason
from wowbot.verification import classify_combat_error


def _target(**overrides):
    value = {"guid": "Creature-1", "dead": False, "attackable": True}
    value.update(overrides)
    return value


def test_player_dead_takes_priority_over_everything_else():
    assert classify_combat_error({"is_dead": True, "target": _target()}) is FailureReason.PLAYER_DEAD


def test_missing_target_guid_is_target_lost():
    assert classify_combat_error({"target": {}}) is FailureReason.TARGET_LOST


def test_unattackable_target_is_invalid_target():
    obs = {"target": _target(attackable=False)}
    assert classify_combat_error(obs) is FailureReason.INVALID_TARGET


def test_invalid_target_ui_error_is_invalid_target():
    obs = {"target": _target(), "ui_error": "Invalid target."}
    assert classify_combat_error(obs) is FailureReason.INVALID_TARGET


def test_dead_target_flag_classifies_as_target_dead():
    obs = {"target": _target(dead=True)}
    assert classify_combat_error(obs) is FailureReason.TARGET_DEAD


def test_out_of_range_ui_error_delegates_to_combat_verifier():
    obs = {"target": _target(), "ui_error": "You are too far away!"}
    assert classify_combat_error(obs) is FailureReason.OUT_OF_RANGE


def test_facing_wrong_way_ui_error_delegates_to_combat_verifier():
    obs = {"target": _target(), "ui_error": "You are facing the wrong way!"}
    assert classify_combat_error(obs) is FailureReason.FACING_WRONG_WAY


def test_line_of_sight_ui_error_delegates_to_combat_verifier():
    obs = {"target": _target(), "ui_error": "No line of sight."}
    assert classify_combat_error(obs) is FailureReason.LINE_OF_SIGHT


def test_spell_not_ready_ui_error_delegates_to_combat_verifier():
    obs = {"target": _target(), "ui_error": "Ability is not ready yet."}
    assert classify_combat_error(obs) is FailureReason.SPELL_NOT_READY


def test_resource_exhausted_classifies_as_not_enough_resource():
    obs = {"target": _target(), "power": 0, "max_power": 100}
    assert classify_combat_error(obs) is FailureReason.NOT_ENOUGH_RESOURCE


def test_cast_interrupted_by_movement_uses_combat_history_transition():
    history = [{"is_casting": True}]
    obs = {"target": _target(), "is_moving": True, "is_casting": False}
    assert classify_combat_error(obs, history) is FailureReason.CAST_INTERRUPTED


def test_moving_without_a_prior_cast_in_history_is_not_cast_interrupted():
    history = [{"is_casting": False}]
    obs = {"target": _target(), "is_moving": True, "is_casting": False}
    assert classify_combat_error(obs, history) is FailureReason.UI_UNKNOWN


def test_no_matching_signal_falls_back_to_unknown():
    assert classify_combat_error({"target": _target()}) is FailureReason.UI_UNKNOWN
