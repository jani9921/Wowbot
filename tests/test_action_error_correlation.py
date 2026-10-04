from wowbot.skills.action_error_correlation import ActionErrorCorrelator


def test_new_error_text_in_the_cast_window_is_correlated():
    correlator = ActionErrorCorrelator()
    attempt = correlator.start({"ui_error": ""}, 10.0)

    assert correlator.matches(attempt, {"ui_error": "Need to be closer"}, 10.4)


def test_retained_error_is_not_reassigned_to_a_new_cast_without_fresh_evidence():
    correlator = ActionErrorCorrelator()
    attempt = correlator.start({"ui_error": "Need to be closer"}, 10.0)

    assert not correlator.matches(attempt, {"ui_error": "Need to be closer"}, 10.4)
    assert not correlator.matches(attempt, {"ui_error": "Line of sight"}, 11.3)


def test_fresh_timestamp_can_confirm_same_text_again():
    correlator = ActionErrorCorrelator()
    attempt = correlator.start({"ui_error": "Need to be closer"}, 10.0)

    assert correlator.matches(attempt, {"ui_error": "Need to be closer", "ui_error_at": 10.2}, 10.3)


def test_addon_error_sequence_correlates_same_text_across_different_clock_epochs():
    correlator = ActionErrorCorrelator()
    attempt = correlator.start({
        "ui_error": "Out of range", "ui_error_at": 500.0,
        "ui_error_sequence": 41,
    }, 10.0)
    assert not correlator.matches(attempt, {
        "ui_error": "Out of range", "ui_error_at": 500.0,
        "ui_error_sequence": 41,
    }, 10.2)
    assert correlator.matches(attempt, {
        "ui_error": "Out of range", "ui_error_at": 500.2,
        "ui_error_sequence": 42,
    }, 10.3)


def test_attempt_correlates_addon_cast_and_effect_evidence_inside_1200ms():
    correlator = ActionErrorCorrelator()
    before = {"event_sequence": 4, "cast_sequence": 2, "power": 100,
              "target": {"guid": "mob-1", "health": 80}}
    attempt = correlator.start(before, 10., ability_id=42, binding="ACTIONBUTTON1")
    after = {"event_sequence": 5, "cast_sequence": 3, "power": 80,
             "target": {"guid": "mob-1", "health": 60},
             "events": [{"event_type": "SPELL_CAST_FAILED", "at": 10.4,
                         "payload": {"spell_id": 42}}]}
    result = correlator.correlate(attempt, after, 10.5)
    assert result.within_window is True
    assert result.addon_failures == ("SPELL_CAST_FAILED",)
    assert result.cast_changed and result.resource_changed and result.target_damage
    assert result.no_effect_evidence == ()


def test_attempt_reports_bounded_no_effect_and_ignores_unrelated_late_error():
    correlator = ActionErrorCorrelator()
    before = {"ui_error": "", "cast_sequence": 2, "power": 100,
              "target": {"guid": "mob-1", "health": 80}}
    attempt = correlator.start(before, 10., ability_id=42)
    unchanged = correlator.correlate(attempt, before, 11.2)
    assert unchanged.no_effect_evidence == (
        "no_cast_change", "no_resource_change", "no_target_damage")
    late = correlator.correlate(
        attempt, {**before, "ui_error": "Need to be closer"}, 11.21)
    assert late.within_window is False
    assert late.failure_evidence == ()


def test_failure_event_for_another_ability_is_not_misattributed():
    correlator = ActionErrorCorrelator()
    attempt = correlator.start({"target": {"guid": "mob-1"}}, 10., ability_id=42)
    result = correlator.correlate(attempt, {
        "target": {"guid": "mob-1"},
        "events": [{"event_type": "SPELL_CAST_FAILED", "at": 10.2,
                    "payload": {"spell_id": 99}}],
    }, 10.3)
    assert result.addon_failures == ()
