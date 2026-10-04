from wowbot.agent.movement_controller import ReachMovementController
from wowbot.navigation.arrival import ArrivalStatus, ArrivalVerifier
import pytest


def test_distance_requires_an_explicit_reliable_coordinate_contract():
    verifier = ArrivalVerifier()
    result = verifier.observe(distance=.5, tolerance=1., facts={})
    assert result.status is ArrivalStatus.UNKNOWN
    assert not result.arrived


def test_reliable_absolute_distance_confirms_arrival_with_evidence():
    verifier = ArrivalVerifier()
    result = verifier.observe(
        distance=.5,
        tolerance=1.,
        facts={"absolute_distance_reliable": True},
    )
    assert result.arrived
    assert result.confidence == .95
    assert "reliable_absolute_distance" in result.evidence


def test_arrival_hysteresis_retains_inside_exit_envelope_then_clears():
    verifier = ArrivalVerifier()
    verifier.observe(
        distance=.9,
        tolerance=1.,
        facts={"absolute_distance_reliable": True},
    )
    retained = verifier.observe(
        distance=1.1,
        tolerance=1.,
        facts={"absolute_distance_reliable": True},
    )
    assert retained.arrived
    assert "arrival_hysteresis" in retained.evidence
    cleared = verifier.observe(
        distance=1.3,
        tolerance=1.,
        facts={"absolute_distance_reliable": True},
    )
    assert cleared.status is ArrivalStatus.UNKNOWN
    assert not cleared.arrived


def test_semantic_arrival_can_confirm_without_absolute_distance():
    verifier = ArrivalVerifier()
    result = verifier.observe(
        distance=None,
        tolerance=None,
        facts={"quest_area_state_change": True},
    )
    assert result.arrived
    assert result.evidence == ("quest_area_state_change",)


def test_weak_correlated_signals_remain_candidate_not_fact():
    verifier = ArrivalVerifier()
    result = verifier.observe(
        distance=None,
        tolerance=None,
        facts={"minimap_convergence": True, "bbox_growth": True},
    )
    assert result.status is ArrivalStatus.CANDIDATE
    assert not result.arrived


def test_reach_controller_uses_canonical_arrival_verifier_and_exports_snapshot():
    controller = ReachMovementController()
    destination = {"map_id": 1609, "x": .5, "y": .4}
    initial = {"map_id": 1609, "position": {"x": .5, "y": .5}, "orientation": 0.}
    controller.start(destination, initial, "o1", 1.)
    result = controller.observe(
        {"map_id": 1609, "position": {"x": .5, "y": .402}, "orientation": 0.},
        "o2",
        2.,
    )
    assert result.success
    assert controller.snapshot()["arrival"]["status"] == "ARRIVED"
    assert "reliable_absolute_distance" in controller.snapshot()["arrival"]["evidence"]


def test_explicit_route_radius_is_used_instead_of_default_distance():
    controller = ReachMovementController()
    destination = {"coordinate_space": "WORLD_YARDS", "x": 10., "y": 0.,
                   "arrival_radius": 1.}
    state = {"player_world_position": {"x": 6., "y": 0.}, "orientation": 0.}
    controller.start(destination, state, "o1", 1.)
    assert controller.snapshot()["arrival"]["status"] != "ARRIVED"
    state["player_world_position"]["x"] = 9.5
    assert controller.observe(state, "o2", 2.).success


def test_missing_evidence_does_not_keep_arrival_latched_forever():
    verifier = ArrivalVerifier()
    assert verifier.observe(distance=None, tolerance=None,
                            facts={"interaction_ready": True}).arrived
    assert verifier.observe(distance=None, tolerance=None).status is ArrivalStatus.UNKNOWN


@pytest.mark.parametrize("distance,tolerance", [
    (-1., 1.), (float("nan"), 1.), (0., float("inf")), (True, 1.)])
def test_invalid_distance_contract_never_confirms_arrival(distance, tolerance):
    result = ArrivalVerifier().observe(distance=distance, tolerance=tolerance,
                                       facts={"absolute_distance_reliable": True})
    assert not result.arrived


def test_nonfinite_semantic_score_is_not_positive_evidence():
    assert not ArrivalVerifier().observe(distance=None, tolerance=None,
                                        facts={"interaction_ready": float("nan")}).arrived
