from dataclasses import dataclass

from wowbot.vision.mouseover_association import associate_mouseover


@dataclass(frozen=True)
class Entity:
    track_id: int
    screen_center: tuple[float, float]
    entity_type: str


def test_mouseover_associates_nearest_entity_track():
    entities = (
        Entity(11, (300.0, 200.0), "MOB"),
        Entity(12, (520.0, 400.0), "NPC"),
    )
    result = associate_mouseover(
        {"unit_type": "NPC", "npc_id": 123},
        {"nx": 0.52, "ny": 0.50},
        entities,
        screen_width=1000,
        screen_height=800,
    )
    assert result.matched is True
    assert result.track_id == 12
    assert result.confidence > 0.5


def test_mouseover_never_associates_to_object_or_obstacle():
    entities = (
        Entity(20, (500.0, 400.0), "OBJECT"),
        Entity(21, (510.0, 405.0), "OBSTACLE_CANDIDATE"),
    )
    result = associate_mouseover(
        {"unit_type": "NPC", "npc_id": 456},
        {"nx": 0.5, "ny": 0.5},
        entities,
        screen_width=1000,
        screen_height=800,
    )
    assert result.matched is False
    assert result.track_id is None


def test_mouseover_keeps_identity_ground_truth_separate_from_vision_confidence():
    entity = Entity(30, (500.0, 400.0), "MOB")
    result = associate_mouseover(
        {"unit_type": "NPC", "npc_id": 789, "name": "Test Mob"},
        {"nx": 0.5, "ny": 0.5},
        (entity,),
        screen_width=1000,
        screen_height=800,
    )
    assert result.matched is True
    assert result.confidence <= 0.95
