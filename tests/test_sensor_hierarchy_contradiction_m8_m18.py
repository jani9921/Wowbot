from wowbot.agent.models import Observation
from wowbot.agent.world import SENSOR_TIERS, WorldModel


def _world():
    world = WorldModel()
    world.ingest(Observation.create({"session_id": "hierarchy", "active_quests": []}, 1.0))
    return world


def _observation(world, source, value, at, frame):
    return Observation.create({"session_id": world.session_id, "frame_id": frame,
                               "claim": value, "confidence": 1.0}, at, source)


def test_sensor_hierarchy_is_explicit_and_queryable():
    hierarchy = WorldModel().query.sensor_hierarchy()
    assert hierarchy["MOUSEOVER"] == {"tier": "GROUND_TRUTH", "rank": SENSOR_TIERS["GROUND_TRUTH"]}
    assert hierarchy["ENTITY_MEMORY"]["tier"] == "STRONG"
    assert hierarchy["WORLD3D"]["tier"] == "PERCEPTION"
    assert hierarchy["AI"]["tier"] == "REASONING"


def test_reasoning_and_cv_cannot_override_ground_truth_even_with_more_votes():
    world = _world()
    world.ingest(_observation(world, "MOUSEOVER", "VENDOR", 1.1, "truth"))
    for index, source in enumerate(("AI", "WORLD3D", "MINIMAP_CV"), start=1):
        world.ingest(_observation(world, source, "QUEST_TURN_IN", 1.1+index*.1, f"weak-{index}"))
    belief = world.query.belief("claim", 1.6)
    assert belief["status"] == "CONFIRMED"
    assert belief["value"] == "VENDOR"
    assert belief["sensor_tier"] == "GROUND_TRUTH"
    assert belief["resolution"]["method"] == "HIGHER_SENSOR_TIER"
    assert len(belief["contradictions"]) == 3


def test_equal_tier_conflict_is_ambiguous_and_history_is_not_deleted():
    world = _world()
    first = _observation(world, "MOUSEOVER", "QUEST_TURN_IN", 1.1, "mouse-1")
    second = _observation(world, "TOOLTIP", "VENDOR", 1.2, "tooltip-1")
    world.ingest(first)
    world.ingest(second)
    belief = world.query.belief("claim", 1.3)
    assert belief["status"] == "AMBIGUOUS"
    assert belief["resolution"] == {"status": "UNRESOLVED", "method": "EQUAL_TIER_CONFLICT"}
    history = world.query.contradiction_history("claim")
    assert history[-1].status == "AMBIGUOUS"
    assert history[-1].supporting_observations
    assert history[-1].contradicting_observations
    assert any(event.event_type == "CONTRADICTION_DETECTED" for event in world.event_records)


def test_new_independent_ground_truth_can_resolve_but_retains_conflict_history():
    world = _world()
    world.ingest(_observation(world, "MOUSEOVER", "QUEST_TURN_IN", 1.1, "mouse-1"))
    world.ingest(_observation(world, "TOOLTIP", "VENDOR", 1.2, "tooltip-1"))
    world.ingest(_observation(world, "MOUSEOVER", "VENDOR", 1.3, "mouse-2"))
    belief = world.query.belief("claim", 1.4)
    assert belief["status"] == "CONFIRMED" and belief["value"] == "VENDOR"
    assert belief["resolution"]["method"] == "WEIGHTED_SUPPORT"
    history = world.query.contradiction_history("claim")
    assert [item.status for item in history][-2:] == ["AMBIGUOUS", "RESOLVED"]
    assert history[-1].resolution == "WEIGHTED_SUPPORT"
    assert any(event.event_type == "CONTRADICTION_RESOLVED" for event in world.event_records)


def test_three_independent_visual_observations_promote_evidence_strength_not_semantics():
    world = _world()
    for index in range(3):
        world.ingest(_observation(world, "WORLD3D", {"semantic_type": "UNKNOWN"},
                                  1.1+index*.1, f"frame-{index}"))
    belief = world.query.belief("claim", 1.5)
    assert belief["status"] == "SUPPORTED"
    assert belief["sensor_tier"] == "STRONG"
    assert belief["value"]["semantic_type"] == "UNKNOWN"
    assert len(belief["supporting_evidence"]) == 3
