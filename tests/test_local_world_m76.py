from wowbot.vision.fusion import LocalWorldProjector
from wowbot.vision.models import NavigationVisionObservation, WorldObservation


def test_projects_actionable_entities_without_promoting_obstacles():
    obs = NavigationVisionObservation(
        world=WorldObservation(
            visible_entities=(
                {"entity_type": "NPC", "confidence": 0.8, "relation": "friendly", "track_id": 1,
                 "screen_center": {"x": 100, "y": 200}},
                {"entity_type": "MOB", "confidence": 0.9, "relation": "neutral", "track_id": 2,
                 "screen_center": {"x": 120, "y": 210}},
                {"entity_type": "PLAYER", "confidence": 0.95, "relation": "friendly", "track_id": 3,
                 "class_name": "paladin", "class_color": "#F58CBA",
                 "screen_center": {"x": 140, "y": 220}},
                {"entity_type": "OBSTACLE_CANDIDATE", "confidence": 0.7, "screen_center": {"x": 200, "y": 220}},
            ),
            obstacles=(),
            observed_at=10.0,
        ),
        observed_at=10.0,
    )
    local = LocalWorldProjector().project(obs)
    assert [e.entity_type for e in local.entities] == ["NPC", "MOB", "PLAYER"]
    assert len(local.candidate_obstacles) == 1
    assert local.entities[2].class_name == "paladin"
    assert local.entities[2].class_color == "#F58CBA"
    assert local.counts() == {"NPC": 1, "MOB": 1, "PLAYER": 1}
    assert local.notes == ("obstacle_candidates_present_but_unproven",)


def test_projects_empty_observation_safely():
    local = LocalWorldProjector().project(NavigationVisionObservation(observed_at=1.0))
    assert local.entities == ()
    assert local.confidence == 0.0
    assert "no_world_observation" in local.notes
    assert local.has_actionable_world is False


def test_serialization_keeps_obstacle_candidate_separate():
    obs = NavigationVisionObservation(
        world=WorldObservation(
            visible_entities=({"entity_type": "OBSTACLE_CANDIDATE", "confidence": 0.7, "screen_center": {"x": 2, "y": 3}},),
            obstacles=(), observed_at=2.0,
        ), observed_at=2.0,
    )
    data = LocalWorldProjector().project(obs).to_dict()
    assert data["candidate_obstacle_count"] == 1
    assert data["entity_counts"] == {}
