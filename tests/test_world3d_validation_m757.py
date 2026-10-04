from wowbot.vision.fusion.pipeline import PerceptionFusion
from wowbot.vision.models import WorldObservation
from wowbot.vision.world3d.validation import validate_fusion_observation


def test_validation_accepts_clean_world_observation():
    world = WorldObservation(
        visible_entities=(
            {"entity_type": "PLAYER", "class_name": "mage", "class_color": "#69CCF0", "relation": "friendly", "track_id": 1},
            {"entity_type": "MOB", "class_name": None, "class_color": None, "relation": "neutral", "track_id": 2},
        ),
        obstacles=(),
        observed_at=1.0,
    )
    fusion = PerceptionFusion().build(world=world, observed_at=1.0)
    result = validate_fusion_observation(fusion, candidate_count=2)
    assert result.class_palette_valid is True
    assert result.invalid_metadata_count == 0
    assert result.ready_for_navigation is True


def test_validation_rejects_wrong_class_color():
    world = WorldObservation(
        visible_entities=({"entity_type": "PLAYER", "class_name": "mage", "class_color": "#C79C6E", "relation": "friendly", "track_id": 1},),
        obstacles=(),
        observed_at=1.0,
    )
    fusion = PerceptionFusion().build(world=world, observed_at=1.0)
    result = validate_fusion_observation(fusion, candidate_count=1)
    assert result.class_palette_valid is False
    assert result.ready_for_navigation is False
