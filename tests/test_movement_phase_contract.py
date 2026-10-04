from wowbot.skills.movement_phase_contract import (
    MovementPhase,
    MovementPhaseObservation,
    classify_movement_phase,
)


def test_all_eight_spec_phases_are_named():
    assert {p.value for p in MovementPhase} == {
        "INIT", "RESOLVE_DESTINATION", "PLAN", "MOVE", "MONITOR_PROGRESS",
        "LOCAL_CORRECTION", "ARRIVAL_VERIFY", "RECOVER_STUCK",
    }


def test_just_started_attempt_is_init():
    result = classify_movement_phase(MovementPhaseObservation(attempt_just_started=True))
    assert result is MovementPhase.INIT


def test_no_destination_yet_resolves_destination():
    result = classify_movement_phase(MovementPhaseObservation(has_destination=False))
    assert result is MovementPhase.RESOLVE_DESTINATION


def test_destination_but_no_plan_is_plan_phase():
    result = classify_movement_phase(MovementPhaseObservation(has_destination=True, has_plan=False))
    assert result is MovementPhase.PLAN


def test_planned_and_stationary_is_move():
    result = classify_movement_phase(
        MovementPhaseObservation(has_destination=True, has_plan=True, is_moving=False))
    assert result is MovementPhase.MOVE


def test_planned_and_moving_is_monitor_progress():
    result = classify_movement_phase(
        MovementPhaseObservation(has_destination=True, has_plan=True, is_moving=True))
    assert result is MovementPhase.MONITOR_PROGRESS


def test_needing_local_correction_takes_priority_over_monitoring():
    result = classify_movement_phase(MovementPhaseObservation(
        has_destination=True, has_plan=True, is_moving=True, needs_local_correction=True))
    assert result is MovementPhase.LOCAL_CORRECTION


def test_stuck_takes_priority_over_local_correction():
    result = classify_movement_phase(MovementPhaseObservation(
        has_destination=True, has_plan=True, is_stuck=True, needs_local_correction=True))
    assert result is MovementPhase.RECOVER_STUCK


def test_recovering_from_stuck_is_also_recover_stuck():
    result = classify_movement_phase(MovementPhaseObservation(is_recovering_from_stuck=True))
    assert result is MovementPhase.RECOVER_STUCK


def test_arrival_claimed_or_verified_is_arrival_verify_and_outranks_stuck():
    claimed = classify_movement_phase(MovementPhaseObservation(arrival_claimed=True, is_stuck=True))
    verified = classify_movement_phase(MovementPhaseObservation(arrival_verified=True))
    assert claimed is MovementPhase.ARRIVAL_VERIFY
    assert verified is MovementPhase.ARRIVAL_VERIFY
