"""V4-063 wiring: WorldQuery.next_quest_source() inspection order."""
from wowbot.agent.models import Observation
from wowbot.agent.next_quest_source_hierarchy import NextQuestSource
from wowbot.agent.world import WorldModel


def _state(frame, *, target=None, visual_candidates=None):
    return {"session_id": "next-quest-session", "frame_id": frame, "timestamp": float(frame),
            "map_id": 1, "phase": "p1", "instance_id": 10, "zone_name": "Test Zone",
            "quest_state_revision": 1, "level": 2, "is_in_combat": False,
            "player_present": True, "position": {"x": .1, "y": .1}, "target": target,
            "active_quests": [], "visual_candidates": visual_candidates or [], "actionbar": []}


def _quest_giver_target():
    return {"guid": "Creature-42", "npc_id": 42, "name": "Guide", "unit_type": "NPC",
            "world_position": {"x": .2, "y": .3, "z": 3, "coordinate_space": "NORMALIZED_MAP"},
            "quest_role": "QUEST_GIVER", "quest_role_source": "TOOLTIP", "quest_id": 9}


def _local_marker():
    return {"track_id": "w3d:1", "kind": "quest_object", "source": "WORLD3D",
            "candidate_labels": ["quest_marker_like"], "confidence": .7}


def test_no_source_available_returns_none():
    world = WorldModel()
    world.ingest(Observation.create(_state(1), 1))
    assert world.query.next_quest_source() is None


def test_resulting_ui_wins_when_gossip_open():
    world = WorldModel()
    world.ingest(Observation.create(_state(1), 1))
    world.state["gossip_open"] = True
    source, _ = world.query.next_quest_source()
    assert source is NextQuestSource.RESULTING_UI


def test_same_npc_wins_over_local_markers_when_no_ui():
    world = WorldModel()
    world.ingest(Observation.create(
        _state(1, target=_quest_giver_target(), visual_candidates=[_local_marker()]), 1))
    source, value = world.query.next_quest_source(same_npc_entity_id="npc:42")
    assert source is NextQuestSource.SAME_NPC
    assert value.role == "QUEST_GIVER"


def test_local_markers_win_when_no_ui_or_same_npc():
    world = WorldModel()
    world.ingest(Observation.create(_state(1, visual_candidates=[_local_marker()]), 1))
    source, _ = world.query.next_quest_source()
    assert source is NextQuestSource.LOCAL_MARKERS


def test_world_map_wins_when_only_map_marker_present():
    world = WorldModel()
    world.ingest(Observation.create(_state(1), 1))
    common = {"session_id": world.session_id, "confidence": .8}
    worldmap = {"marker_id": "map:1", "track_id": "map:1", "kind": "unknown_map_marker",
                "source": "WORLD_MAP_CV", "semantic_type": "UNKNOWN", "belief": "CANDIDATE",
                "position": {"x": .4, "y": .5, "coordinate_space": "WORLD_MAP_SCREEN_NORMALIZED"},
                "candidate_labels": ["gold_shape_like"], "lifecycle": "TENTATIVE", "confidence": .7}
    world.ingest(Observation.create(
        {**common, "frame_id": "map", "visual_candidates": [worldmap]}, 1.1, "WORLD_MAP_CV"))
    source, _ = world.query.next_quest_source()
    assert source is NextQuestSource.WORLD_MAP


def test_campaign_classification_only_wins_when_caller_supplies_it():
    world = WorldModel()
    world.ingest(Observation.create(_state(1), 1))
    assert world.query.next_quest_source(campaign_resolution="quest-77") == (
        NextQuestSource.CAMPAIGN_CLASSIFICATION, "quest-77")
