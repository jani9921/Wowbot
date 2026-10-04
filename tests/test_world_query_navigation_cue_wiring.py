"""V4-019 wiring: WorldQuery.navigation_cue() fallback chain."""
from wowbot.agent.models import Observation
from wowbot.agent.supertrack_navigation_cue import NavigationCueSource
from wowbot.agent.world import WorldModel


def _state(frame):
    return {"session_id": "nav-cue-session", "frame_id": frame, "timestamp": float(frame),
            "map_id": 1, "phase": "p1", "instance_id": 10, "zone_name": "Test Zone",
            "quest_state_revision": 1, "level": 2, "is_in_combat": False,
            "player_present": True, "position": {"x": .1, "y": .1},
            "active_quests": [], "actionbar": []}


def _minimap_marker():
    return {"marker_id": "mini:1", "track_id": "mini:1", "kind": "unknown_minimap_marker",
            "source": "MINIMAP_CV", "semantic_type": "UNKNOWN", "belief": "SUPPORTED",
            "local_position": {"dx": 4., "dy": -3., "coordinate_space": "MINIMAP_LOCAL"},
            "candidate_labels": ["salient_marker_like"], "lifecycle": "STABLE", "confidence": .8}


def _worldmap_marker():
    return {"marker_id": "map:1", "track_id": "map:1", "kind": "unknown_map_marker",
            "source": "WORLD_MAP_CV", "semantic_type": "UNKNOWN", "belief": "CANDIDATE",
            "position": {"x": .4, "y": .5, "coordinate_space": "WORLD_MAP_SCREEN_NORMALIZED"},
            "candidate_labels": ["gold_shape_like"], "lifecycle": "TENTATIVE", "confidence": .7}


def test_no_sources_available_returns_none():
    world = WorldModel()
    world.ingest(Observation.create(_state(1), 1))
    assert world.query.navigation_cue() is None


def test_falls_back_to_minimap_when_supertrack_absent():
    world = WorldModel()
    world.ingest(Observation.create(_state(1), 1))
    common = {"session_id": world.session_id, "confidence": .8}
    world.ingest(Observation.create(
        {**common, "frame_id": "mini", "visual_candidates": [_minimap_marker()]}, 1.1, "MINIMAP_CV"))
    result = world.query.navigation_cue()
    assert result is not None
    source, value = result
    assert source is NavigationCueSource.MINIMAP_BELIEF


def test_falls_back_to_world_map_when_minimap_absent():
    world = WorldModel()
    world.ingest(Observation.create(_state(1), 1))
    common = {"session_id": world.session_id, "confidence": .8}
    world.ingest(Observation.create(
        {**common, "frame_id": "map", "visual_candidates": [_worldmap_marker()]}, 1.1, "WORLD_MAP_CV"))
    result = world.query.navigation_cue()
    assert result is not None
    source, value = result
    assert source is NavigationCueSource.WORLD_MAP_BELIEF


def test_minimap_wins_over_world_map_when_both_present():
    world = WorldModel()
    world.ingest(Observation.create(_state(1), 1))
    common = {"session_id": world.session_id, "confidence": .8}
    world.ingest(Observation.create(
        {**common, "frame_id": "mini", "visual_candidates": [_minimap_marker()]}, 1.1, "MINIMAP_CV"))
    world.ingest(Observation.create(
        {**common, "frame_id": "map", "visual_candidates": [_worldmap_marker()]}, 1.2, "WORLD_MAP_CV"))
    source, _ = world.query.navigation_cue()
    assert source is NavigationCueSource.MINIMAP_BELIEF
