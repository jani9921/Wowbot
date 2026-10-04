"""M5-I induced oscillation acceptance across monitor/classifier/resolver."""

from wowbot.navigation import ProgressMonitor, ProgressPhase, StuckResolutionState, StuckResolver
from wowbot.navigation.stuck_classifier import StuckClassifier, StuckKind


def test_induced_oscillation_is_evidence_gated_bounded_and_terminates_on_progress():
    monitor = ProgressMonitor()
    for command in ("TURNLEFT", "TURNRIGHT", "TURNLEFT", "TURNRIGHT"):
        monitor.record_command(command)

    # Oscillation alone is not stuck.  It becomes actionable only after the
    # ordinary multi-source, three-second no-progress window reaches HARD_STUCK.
    assert monitor.observe_signals(
        0., optical_flow=0., minimap_displacement=0., movement_state=0.).phase is ProgressPhase.MAKING_PROGRESS
    assert monitor.observe_signals(
        1.5, optical_flow=0., minimap_displacement=0., movement_state=0.).phase is ProgressPhase.POSSIBLE_STUCK
    hard = monitor.observe_signals(
        3.0, optical_flow=0., minimap_displacement=0., movement_state=0.)
    assert hard.phase is ProgressPhase.HARD_STUCK
    assert hard.oscillation_score >= .45

    assessment = StuckClassifier().classify({}, monitor.snapshot())
    assert assessment.supported
    assert assessment.kind is StuckKind.OSCILLATION

    resolver = StuckResolver()
    assert resolver.begin(
        "oscillation:1", 3., stuck_kind=assessment.kind.value,
    ).state is StuckResolutionState.STOP_AND_OBSERVE
    first = resolver.observe_progress(ProgressPhase.HARD_STUCK, 3.1)
    assert first.state is StuckResolutionState.NEW_LOCAL_WAYPOINT
    assert first.action == "NEW_LOCAL_WAYPOINT"
    second = resolver.report_step_result(success=False, now=3.2)
    assert second.state is StuckResolutionState.LOCAL_REPLAN
    assert second.replan_scope == "LOCAL"

    # Fresh positive evidence, not the recovery command itself, closes the
    # recovery lifecycle and prevents an infinite left/right loop.
    monitor.observe_signals(3.3, target_distance=1., movement_state=1.)
    recovered = monitor.observe_signals(3.9, target_distance=1., movement_state=1.)
    assert recovered.phase is ProgressPhase.RECOVERED
    terminal = resolver.observe_progress(recovered.phase, 3.9)
    assert terminal.terminal
    assert terminal.reason == "STUCK_RECOVERED"
    assert resolver.snapshot()["state"] == StuckResolutionState.IDLE.value

