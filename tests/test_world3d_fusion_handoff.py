from wowbot.vision.fusion import PerceptionFusion
from wowbot.vision.models import WorldObservation
from wowbot.vision.world3d import PixelRect, WorldCandidate, WorldFrameObservation, WorldSceneROI, world_frame_to_observation


def _frame() -> WorldFrameObservation:
    scene = WorldSceneROI(rect=PixelRect(0, 0, 700, 400))
    candidates = (
        WorldCandidate(
            kind="mob_candidate",
            rect=PixelRect(100, 120, 140, 180),
            confidence=0.91,
            evidence="neutral nameplate",
            relation="neutral",
            track_id=7,
            previous_relation="neutral",
        ),
        WorldCandidate(
            kind="player_candidate",
            rect=PixelRect(200, 80, 260, 150),
            confidence=0.88,
            evidence="class-colored player nameplate",
            relation="friendly",
            class_name="mage",
            class_color="#69CCF0",
            track_id=9,
        ),
        WorldCandidate(
            kind="obstacle_candidate",
            rect=PixelRect(300, 200, 360, 280),
            confidence=0.66,
            evidence="low-saturation world mass",
        ),
    )
    return WorldFrameObservation(
        width=953,
        height=657,
        scene=scene,
        frame_id="test:world3d:1",
        client_id="test-client",
        candidates=candidates,
        observed_at=123.0,
    )


def test_world3d_normalizes_entities_without_promoting_visual_obstacles():
    world = world_frame_to_observation(_frame())
    assert isinstance(world, WorldObservation)
    assert len(world.visible_entities) == 3
    assert world.visible_entities[0]["entity_type"] == "UNKNOWN"
    assert world.visible_entities[0]["track_id"] == 7
    assert world.visible_entities[1]["entity_type"] == "UNKNOWN"
    assert world.visible_entities[1]["class_name"] == "mage"
    assert world.visible_entities[1]["class_color"] == "#69CCF0"
    assert world.visible_entities[2]["entity_type"] == "UNKNOWN"
    assert world.obstacles == ()
    assert world.observed_at == 123.0


def test_perception_fusion_uses_same_world_path():
    fused = PerceptionFusion().build_from_world3d(_frame(), addon_facts={"is_in_combat": False})
    assert fused.world is not None
    assert len(fused.world.visible_entities) == 3
    assert fused.world.visible_entities[0]["relation"] == "neutral"
    assert fused.world.visible_entities[2]["candidate_kind"] == "obstacle_candidate"
    assert fused.addon_facts["is_in_combat"] is False
    assert fused.observed_at == 123.0
