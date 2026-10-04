from wowbot.runtime import FailureReason, RetryPolicy, TimeoutPolicy


def test_timeout_policy_preserves_configured_domain_baseline_and_bounds_unavailable_input():
    policy = TimeoutPolicy()
    assert policy.domain_for("COMBAT") == "combat"
    assert policy.resolve("COMBAT", 8., {}) == 8.
    assert policy.resolve("COMBAT", 8., {"loading": True}) == 1.


def test_timeout_policy_maps_map_open_close_to_the_map_wait_domain():
    # V4-039 lists map_wait as one of the seven central domains; OPEN_MAP/
    # CLOSE_MAP are the skill types that actually wait on the world map UI.
    policy = TimeoutPolicy()
    assert policy.domain_for("OPEN_MAP") == "map_wait"
    assert policy.domain_for("CLOSE_MAP") == "map_wait"


def test_retry_policy_is_typed_bounded_and_does_not_backoff_cancel():
    policy = RetryPolicy()
    assert policy.backoff(1, FailureReason.OUT_OF_RANGE) == 8.
    assert policy.backoff(99, FailureReason.NO_RESPONSE) == 120.
    assert policy.backoff(4, FailureReason.CANCELLED) == 0.


# DESIGN-075: max_attempts/per_reason_limits/can_retry/next_backoff/reset_if.

def test_next_backoff_is_a_spec_named_alias_for_backoff():
    policy = RetryPolicy()
    assert policy.next_backoff(2, FailureReason.OUT_OF_RANGE) == policy.backoff(2, FailureReason.OUT_OF_RANGE)


def test_can_retry_uses_max_attempts_by_default():
    policy = RetryPolicy(max_attempts=2)
    assert policy.can_retry(1, FailureReason.OUT_OF_RANGE) is True
    assert policy.can_retry(2, FailureReason.OUT_OF_RANGE) is True
    assert policy.can_retry(3, FailureReason.OUT_OF_RANGE) is False


def test_can_retry_per_reason_limit_overrides_max_attempts():
    policy = RetryPolicy(max_attempts=5, per_reason_limits={FailureReason.LINE_OF_SIGHT: 1})
    assert policy.can_retry(1, FailureReason.LINE_OF_SIGHT) is True
    assert policy.can_retry(2, FailureReason.LINE_OF_SIGHT) is False
    assert policy.can_retry(2, FailureReason.OUT_OF_RANGE) is True


def test_can_retry_respects_non_backoff_reasons_and_retryable_flag():
    policy = RetryPolicy()
    assert policy.can_retry(1, FailureReason.CANCELLED) is False
    assert policy.can_retry(1, FailureReason.OUT_OF_RANGE, retryable=False) is False


def test_reset_if_matches_the_non_backoff_reason_set():
    policy = RetryPolicy()
    assert policy.reset_if(FailureReason.PLAYER_DEAD) is True
    assert policy.reset_if(FailureReason.INTERRUPTED) is True
    assert policy.reset_if(FailureReason.OUT_OF_RANGE) is False
    assert policy.reset_if(None) is False
