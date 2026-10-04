import math

import pytest

from wowbot.navigation import ProgressMonitor, ProgressPhase, ProgressPolicy
from wowbot.navigation.stuck_classifier import StuckClassifier, StuckKind
from wowbot.navigation.stuck_resolver import StuckResolutionState, StuckResolver


def test_progress_score_renormalizes_only_available_evidence():
    result = ProgressMonitor().observe_signals(1., target_distance=1., movement_state=None)
    assert result.score == 1.
    assert result.sources == ("target_distance",)


def test_progress_monitor_requires_duration_before_stuck_and_hysteresis_before_recovery():
    monitor = ProgressMonitor()
    for at in (0., 1.4):
        result = monitor.observe_signals(at, optical_flow=0., minimap_displacement=0., movement_state=0.)
        assert result.phase is ProgressPhase.MAKING_PROGRESS
    assert monitor.observe_signals(1.5, optical_flow=0., minimap_displacement=0., movement_state=0.).phase is ProgressPhase.POSSIBLE_STUCK
    assert monitor.observe_signals(3.0, optical_flow=0., minimap_displacement=0., movement_state=0.).phase is ProgressPhase.HARD_STUCK
    assert monitor.observe_signals(3.2, target_distance=1.).phase is ProgressPhase.MAKING_PROGRESS
    assert monitor.observe_signals(3.7, target_distance=1.).phase is ProgressPhase.RECOVERED


def test_progress_monitor_never_invents_a_score_when_all_sensors_are_unavailable():
    result = ProgressMonitor().observe_signals(1., optical_flow=None, minimap_displacement=None)
    assert result.score is None
    assert result.phase is ProgressPhase.UNAVAILABLE


def test_sensor_dropout_clears_stuck_phase_and_requires_a_new_temporal_window():
    monitor = ProgressMonitor()
    monitor.observe_signals(0., optical_flow=0.)
    assert monitor.observe_signals(3., optical_flow=0.).phase is ProgressPhase.HARD_STUCK
    assert monitor.observe_signals(3.1, optical_flow=None).phase is ProgressPhase.UNAVAILABLE
    assert monitor.observe_signals(10., optical_flow=0.).phase is ProgressPhase.MAKING_PROGRESS


def test_nonfinite_or_nonnumeric_signals_are_unavailable_not_fake_progress():
    result = ProgressMonitor().observe_signals(
        1., optical_flow=math.nan, target_distance="unknown")
    assert result.score is None
    assert result.sources == ()


def test_progress_weights_are_configurable_normalized_and_validated():
    monitor = ProgressMonitor(policy=ProgressPolicy(
        weights={"optical_flow": 1., "target_distance": 3.}))
    result = monitor.observe_signals(1., optical_flow=1., target_distance=0.)
    assert result.score == .25
    assert result.contributions == {"optical_flow": .25, "target_distance": 0.}
    with pytest.raises(ValueError):
        ProgressPolicy(weights={"invented_sensor": 1.})
    with pytest.raises(ValueError):
        ProgressPolicy(weights={"optical_flow": 0.})


def test_progress_reports_direction_and_oscillation_as_separate_evidence():
    monitor = ProgressMonitor()
    monitor.record_command("TURNLEFT")
    monitor.record_command("TURNRIGHT")
    monitor.record_command("TURNLEFT")
    result = monitor.observe_signals(1., expected_vs_observed_bearing=.8, target_distance=.6)
    assert result.direction_consistency == .8
    assert result.oscillation_score == 1.
    assert result.stuck_probability is not None and result.stuck_probability > 0.


def test_stuck_type_is_evidence_gated_and_selects_a_typed_recovery_ladder():
    classifier = StuckClassifier()
    state = {"local_traversability": {"sectors": [{
        "sector": "CENTER", "state": "BLOCKED", "obstacle_lifecycle": "CONFIRMED",
        "obstacle_confidence": .9, "dynamic_probability": .0, "evidence": ["frame:99"],
    }]}}
    assessment = classifier.classify(state, {"latest": {"phase": "HARD_STUCK", "sources": ["POSITION"]}})
    assert assessment.kind is StuckKind.STATIC_BLOCK
    assert assessment.supported
    resolver = StuckResolver()
    resolver.begin("stuck:1", 1., stuck_kind=assessment.kind.value)
    directive = resolver.observe_progress(ProgressPhase.HARD_STUCK, 2.)
    assert directive.state is StuckResolutionState.BACKWARD
    assert directive.stuck_kind == "STATIC_BLOCK"


def test_stuck_classifier_does_not_classify_before_hard_stuck_confirmation():
    assessment = StuckClassifier().classify({}, {"latest": {"phase": "POSSIBLE_STUCK", "oscillation_score": 1.}})
    assert assessment.kind is StuckKind.UNKNOWN
    assert not assessment.supported
