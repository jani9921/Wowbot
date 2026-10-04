from wowbot.agent.models import Observation
from wowbot.agent.world import Belief, Evidence, WorldModel


def test_evidence_exposes_freshness_age_and_effective_confidence_contract():
    evidence = Evidence(
        observation_id="obs", correlation_id="corr", source="WORLD3D",
        at=10., expires=12., value_json='{"track_id":"t"}', confidence=.8,
        reliability=.5, context_json="{}", independence_group="frame:1",
        sensor_tier="PERCEPTION", tier_rank=2)
    assert evidence.evidence_id.startswith("obs:WORLD3D:")
    assert evidence.observed_at == 10. and evidence.expires_at == 12.
    assert evidence.value == {"track_id": "t"}
    assert evidence.is_fresh(11.) and evidence.age_ms(11.) == 1000
    assert 0. < evidence.effective_confidence(11.) < .4
    assert evidence.effective_confidence(13.) == 0.


def test_world_evidence_records_kind_and_related_domain_references():
    world = WorldModel()
    observation = Observation.create({
        "session_id": "related", "timestamp": 1., "frame_id": "one",
        "quest_id": 7, "objective_id": "7:0", "entity_id": "npc:42",
        "custom_claim": {"value": True}}, 1., source="WORLD3D")
    world.session_id = "related"
    assert world.ingest(observation)
    evidence = world.evidence["custom_claim"][-1]
    assert evidence.kind == "custom_claim"
    assert evidence.related_entity == "npc:42"
    assert evidence.related_quest == "7"
    assert evidence.related_objective == "7:0"


def test_world_model_has_typed_belief_without_breaking_legacy_dict_projection():
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "typed", "timestamp": 1., "frame_id": "one",
        "position": {"x": .2, "y": .3}}, 1.))
    legacy = world.belief("position", 1.)
    typed = world.query.typed_belief("position", 1.)
    assert isinstance(typed, Belief) and typed.supported
    assert typed.value == legacy["value"]
    assert typed.evidence_refs == tuple(legacy["evidence"])
    assert typed.contradictions == tuple(legacy["contradictions"])
    unknown = world.typed_belief("missing", 1.)
    assert unknown.status == "UNKNOWN" and not unknown.supported


def test_observation_projects_sensor_type_and_explicit_coordinate_contract():
    observation = Observation.create({
        "session_id": "vision", "timestamp": 1., "frame_id": "f",
        "observation_type": "TRACK_BATCH", "track_id": "t"},
        1., source="WORLD3D")
    assert observation.sensor == "WORLD3D"
    assert observation.observation_type == "TRACK_BATCH"
    assert observation.coordinate_space == "SCREEN_NORMALIZED"
