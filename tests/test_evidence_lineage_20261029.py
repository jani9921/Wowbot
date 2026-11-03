"""Common evidence must retain time and ancestry without creating authority."""
from wowbot.agent.models import Observation
from wowbot.agent.world import Evidence, WorldModel


def evidence(**changes):
    return Evidence(**{"observation_id": "obs", "correlation_id": "frame", "source": "WORLD3D",
        "at": 10., "expires": 12., "value_json": '"A"', "confidence": .6, "reliability": .5,
        "context_json": "{}", "independence_group": "frame", "sensor_tier": "PERCEPTION",
        "tier_rank": 2, **changes})


def claim(world, frame, value="A", *, at=1., source="WORLD3D", provenance=None):
    observation = Observation.create({"session_id": "lineage", "frame_id": frame,
        "timestamp": at, "provenance": provenance or {}}, at, source)
    world.add_evidence("claim", value, observation, confidence=.6, ttl=5.)
    return observation


def test_an_evidence_value_cannot_be_fresh_before_it_is_received():
    value = evidence()
    assert not value.is_fresh(9.)
    assert value.effective_confidence(9.) == 0.


def test_future_received_evidence_cannot_enter_a_current_belief_or_snapshot():
    world = WorldModel()
    claim(world, "future", at=10.)
    assert world.belief("claim", 1.)["value"] is None
    assert "claim" not in world.snapshot(1.)["beliefs"]


def test_rewrapped_copies_with_the_same_root_are_one_vote():
    world = WorldModel()
    for index in range(3):
        claim(world, f"copy:{index}", provenance={"independence_group": f"wrapper:{index}",
            "root_observation_ids": ["original-packet"]})
    belief = world.belief("claim", 1.1)
    assert len(belief["evidence"]) == 1
    assert belief["sensor_tier"] == "PERCEPTION"
    assert belief["confidence"] < .5


def test_partly_overlapping_ancestry_cannot_make_three_independent_observations():
    world = WorldModel()
    for frame, roots in (("A", ["root-A"]), ("AB", ["root-A", "root-B"]), ("B", ["root-B"])):
        claim(world, frame, provenance={"root_observation_ids": roots})
    belief = world.belief("claim", 1.1)
    assert len(belief["evidence"]) == 1
    assert belief["sensor_tier"] == "PERCEPTION"


def test_local_view_and_cross_view_of_the_same_capture_are_correlated():
    world = WorldModel()
    for source in ("WORLD3D", "WORLD3D_LOCAL_VIEW", "CROSS_VIEW"):
        claim(world, "one-capture", source=source)
    belief = world.belief("claim", 1.1)
    assert len(belief["evidence"]) == 1
    assert belief["sensor_tier"] == "PERCEPTION"


def test_equal_weight_copies_of_one_origin_keep_the_newer_sample():
    world = WorldModel()
    provenance = {"independence_group": "one-origin"}
    claim(world, "old", "old", at=1., provenance=provenance)
    claim(world, "new", "new", at=2., provenance=provenance)
    assert world.belief("claim", 2.)["value"] == "new"


def test_delayed_derived_observation_does_not_restart_the_original_ttl():
    world = WorldModel()
    claim(world, "late-copy", at=10., provenance={"observed_at_monotonic": 1.,
          "parent_observation_id": "old-parent", "root_observation_ids": ["old-parent"]})
    assert world.belief("claim", 10.)["value"] is None
