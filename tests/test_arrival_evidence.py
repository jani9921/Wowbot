from wowbot.agent.movement_controller import ReachMovementController
from wowbot.navigation.arrival_evidence import ArrivalEvidence
import pytest


def frame(at, height=.10):
    return {"camera_state": {"yaw_estimate": 0.},
            "confirmed_mouseover_anchors": {"npc": {"track_id": "t", "sample_time": at}},
            "visual_candidates": [{"source": "WORLD3D", "track_id": "t", "observed_at": at,
                                   "bbox_height_fraction": height, "lifecycle": "ACTIVE"}]}


def test_fresh_target_growth_is_weak_arrival_evidence_in_production_controller():
    controller = ReachMovementController()
    destination = {"target_guid": "npc", "coordinate_space": "WORLD_YARDS",
                   "x": 20., "y": 0.}
    def state(at, x, height):
        return frame(at, height) | {"player_world_position": {"x": x, "y": 0.},
                                   "target": {"guid": "npc", "world_position": {"x": 20., "y": 0.}},
                                   "orientation": 0.}
    controller.start(destination, state(1., 0., .10), "one", 1.)
    result = controller.observe(state(1.1, 1., .11), "two", 1.1)
    assert not result.terminal
    assert controller.snapshot()["arrival"]["status"] == "CANDIDATE"
    assert "bbox_growth" in controller.snapshot()["arrival"]["evidence"]


@pytest.mark.parametrize("condition", ["stale", "camera", "occluded", "wrong_target", "repeated", "receding"])
def test_invalid_growth_cannot_support_arrival(condition):
    producer = ArrivalEvidence()
    destination = {"target_guid": "npc"}
    producer.observe(destination, frame(1.), 1., 20.)
    current = frame(1.1, .12)
    now, distance = 1.1, 19.
    if condition == "stale":
        now = 3.
    elif condition == "camera":
        current["camera_state"]["yaw_estimate"] = 30.
    elif condition == "occluded":
        current["visual_candidates"][0]["lifecycle"] = "OCCLUDED"
    elif condition == "wrong_target":
        destination = {"target_guid": "other"}
    elif condition == "repeated":
        current["visual_candidates"][0]["observed_at"] = 1.
    elif condition == "receding":
        distance = 21.
    assert producer.observe(destination, current, now, distance) == {}


def minimap_state(at, distance, marker="quest-7"):
    return {"map_id": 1, "map_marker_observations": [{
        "surface": "MINIMAP", "marker_id": marker, "track_id": marker,
        "observed_at": at, "lifecycle": "STABLE",
        "local_position": {"dx": distance, "dy": 0., "distance": distance},
    }]}


def test_exact_fresh_minimap_marker_trend_emits_weak_convergence_only():
    evidence = ArrivalEvidence()
    destination = {"marker_id": "quest-7"}
    assert evidence.observe(destination, minimap_state(1., .4), 1., 20.) == {}
    assert evidence.observe(destination, minimap_state(1.2, .3), 1.2, 19.) == {
        "minimap_convergence": True}


def test_wrong_stale_or_receding_minimap_marker_cannot_converge():
    for next_state, now in (
        (minimap_state(1.2, .2, marker="other"), 1.2),
        (minimap_state(1.2, .2), 3.),
        (minimap_state(1.2, .5), 1.2),
    ):
        evidence = ArrivalEvidence()
        evidence.observe({"marker_id": "quest-7"}, minimap_state(1., .4), 1., 20.)
        assert evidence.observe({"marker_id": "quest-7"}, next_state, now, 19.) == {}


def test_only_explicit_expected_map_transition_emits_strong_evidence():
    evidence = ArrivalEvidence()
    destination = {"expected_map_id": 2}
    assert evidence.observe(destination, {"map_id": 1}, 1., 20.) == {}
    assert evidence.observe(destination, {"map_id": 2}, 2., 20.) == {
        "map_transition": True}
    uncontrolled = ArrivalEvidence()
    uncontrolled.observe({}, {"map_id": 1}, 1., 20.)
    assert uncontrolled.observe({}, {"map_id": 2}, 2., 20.) == {}


def test_expected_map_transition_finishes_the_persistent_reach_request():
    controller = ReachMovementController()
    destination = {"map_id": 1, "x": .8, "y": .5,
                   "expected_map_id": 2, "purpose": "ENTER_BUILDING"}
    initial = {"map_id": 1, "position": {"x": .2, "y": .5}, "orientation": 0.}
    controller.start(destination, initial, "before", 1.)

    result = controller.observe(
        {"map_id": 2, "position": {"x": .1, "y": .1}, "orientation": 0.},
        "after", 2.)

    assert result.terminal and result.success
    assert result.reason == "reach_arrival_map_transition_verified"
