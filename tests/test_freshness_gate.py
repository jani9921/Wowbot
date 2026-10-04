from wowbot.runtime import FreshnessDecisionKind, FreshnessGate


def test_camera_detail_wait_preserves_full_ai_without_allowing_input():
    decision = FreshnessGate().evaluate(
        fresh=True, detail_stale=True, pending_skill="CAMERA_CONTROL", full_ai=True,
        player_present=True, latest_received=10., now=10.1)
    assert decision.kind is FreshnessDecisionKind.WAIT_CAMERA_DETAIL
    assert not decision.demote_to_manual


def test_camera_telemetry_wait_is_bounded_but_generic_stale_state_is_fail_safe():
    gate = FreshnessGate()
    wait = gate.evaluate(fresh=False, detail_stale=False, pending_skill="REACQUIRE_TARGET",
                         full_ai=True, player_present=True, latest_received=10., now=11.)
    stale = gate.evaluate(fresh=False, detail_stale=False, pending_skill="MOVE",
                          full_ai=True, player_present=True, latest_received=10., now=11.1)
    assert wait.kind is FreshnessDecisionKind.WAIT_CAMERA_TELEMETRY
    assert stale.kind is FreshnessDecisionKind.STALE_TELEMETRY
    assert not stale.demote_to_manual


def test_transient_non_transport_unfreshness_requires_confirmation_before_demote():
    gate = FreshnessGate(manual_demote_seconds=.6)
    first = gate.evaluate(fresh=False, detail_stale=False, pending_skill=None,
                          full_ai=True, player_present=False, latest_received=10., now=10.1)
    second = gate.evaluate(fresh=False, detail_stale=False, pending_skill=None,
                           full_ai=True, player_present=False, latest_received=10., now=10.8)
    assert not first.demote_to_manual
    assert second.demote_to_manual


def test_live_sized_telemetry_gap_suspends_input_without_discarding_full_ai():
    gate = FreshnessGate(manual_demote_seconds=90.)
    first = gate.evaluate(
        fresh=False, detail_stale=False, pending_skill="MOVE", full_ai=True,
        player_present=True, latest_received=10., now=16.1)
    sixty_seconds = gate.evaluate(
        fresh=False, detail_stale=False, pending_skill="MOVE", full_ai=True,
        player_present=True, latest_received=10., now=76.1)
    persistent = gate.evaluate(
        fresh=False, detail_stale=False, pending_skill="MOVE", full_ai=True,
        player_present=True, latest_received=10., now=106.2)
    assert first.kind is FreshnessDecisionKind.STALE_TELEMETRY
    assert not first.demote_to_manual
    assert not sixty_seconds.demote_to_manual
    assert persistent.demote_to_manual


def test_recovery_requires_two_consecutive_fresh_samples_before_input_resume():
    gate = FreshnessGate(recovery_confirmations=2)
    gate.evaluate(fresh=False, detail_stale=False, pending_skill="MOVE",
                  full_ai=True, player_present=True, latest_received=1., now=8.)
    first = gate.evaluate(fresh=True, detail_stale=False, pending_skill="MOVE",
                          full_ai=True, player_present=True, latest_received=8.1, now=8.1)
    second = gate.evaluate(fresh=True, detail_stale=False, pending_skill="MOVE",
                           full_ai=True, player_present=True, latest_received=8.2, now=8.2)
    assert first.kind is FreshnessDecisionKind.STALE_TELEMETRY
    assert second.kind is FreshnessDecisionKind.CONTINUE
    assert second.resume_input_authority
