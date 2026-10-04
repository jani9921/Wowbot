import pytest

from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel
from wowbot.vision.models import MapMarker


def _state(frame, *, map_id=1, phase="p1", instance_id=10, target=None, revision=1):
    return {"session_id": "entity-session", "frame_id": frame, "timestamp": float(frame),
            "map_id": map_id, "phase": phase, "instance_id": instance_id,
            "zone_name": "Test Zone", "quest_state_revision": revision,
            "level": 2, "is_in_combat": False, "player_present": True,
            "position": {"x": .1, "y": .1}, "target": target,
            "active_quests": [], "actionbar": []}


def _target(x, y, **extra):
    value = {"guid": "Creature-42", "npc_id": 42, "name": "Guide", "unit_type": "NPC",
             "world_position": {"x": x, "y": y, "z": 3,
                                "coordinate_space": "NORMALIZED_MAP"}}
    value.update(extra)
    return value


def test_locations_cluster_only_within_same_map_phase_instance_context():
    world = WorldModel()
    observations = [
        _state(1, target=_target(.200, .300)),
        _state(2, target=_target(.202, .301)),
        _state(3, target=_target(.800, .800)),
        _state(4, phase="p2", target=_target(.201, .300)),
        _state(5, map_id=2, target=_target(.201, .300)),
        _state(6, instance_id=11, target=_target(.201, .300)),
    ]
    for index, payload in enumerate(observations):
        assert world.ingest(Observation.create(payload, 1+index))
    identity = world.query.entity("npc:42")
    assert identity is not None and identity.name == "Guide"
    assert not any(key in world.entities["npc:42"] for key in ("x", "y", "location", "role", "appearance"))
    locations = world.query.entity_locations("npc:42")
    clusters = world.query.entity_location_clusters("npc:42")
    assert len(locations) == 6 and len(clusters) == 5
    assert sorted(cluster.seen_count for cluster in clusters) == [1, 1, 1, 1, 2]
    assert len(world.query.entity_locations("npc:42", map_id=1, phase="p1", instance=10)) == 3
    assert all(location.cluster_id and location.context for location in locations)


def test_dynamic_role_transition_retains_quest_and_player_context():
    world = WorldModel()
    giver = _target(.2, .3, quest_role="QUEST_GIVER", quest_role_source="TOOLTIP", quest_id=7)
    turnin = _target(.2, .3, quest_role="QUEST_TURN_IN", quest_role_source="QUEST_API", quest_id=7)
    world.ingest(Observation.create(_state(1, target=giver, revision=11), 1))
    world.ingest(Observation.create(_state(2, target=turnin, revision=12), 2))
    roles = world.query.entity_roles("npc:42", quest_id=7)
    assert [role.role for role in roles] == ["QUEST_GIVER", "QUEST_TURN_IN"]
    assert [role.quest_revision for role in roles] == [11, 12]
    assert len({role.role_id for role in roles}) == 2
    assert all(role.player_context and role.observation_id for role in roles)
    assert len(world.query.relation(subject="entity:npc:42", predicate="has_role_relation")) == 2


def test_appearance_and_state_do_not_leak_into_identity():
    world = WorldModel()
    target = _target(.2, .3, health=90, combat=True,
                     appearance={"representation_space": "WORLD3D", "signature_id": "sig-1"})
    world.ingest(Observation.create(_state(1, target=target), 1))
    assert "health" not in world.entities["npc:42"] and "appearance" not in world.entities["npc:42"]
    assert world.entity_states["npc:42"][0]["values"] == {"health": 90, "combat": True}
    assert world.entity_appearances["npc:42"][0]["representation_space"] == "WORLD3D"


def test_minimap_and_world_map_share_map_marker_model_without_coordinate_guessing():
    world = WorldModel()
    world.ingest(Observation.create(_state(1), 1))
    common = {"session_id": world.session_id, "confidence": .8}
    minimap = {"marker_id": "mini:1", "track_id": "mini:1", "kind": "unknown_minimap_marker",
               "source": "MINIMAP_CV", "semantic_type": "UNKNOWN", "belief": "SUPPORTED",
               "local_position": {"dx": 4., "dy": -3., "coordinate_space": "MINIMAP_LOCAL"},
               "candidate_labels": ["salient_marker_like"], "lifecycle": "STABLE", "confidence": .8}
    worldmap = {"marker_id": "map:1", "track_id": "map:1", "kind": "unknown_map_marker",
                "source": "WORLD_MAP_CV", "semantic_type": "UNKNOWN", "belief": "CANDIDATE",
                "position": {"x": .4, "y": .5, "coordinate_space": "WORLD_MAP_SCREEN_NORMALIZED"},
                "candidate_labels": ["gold_shape_like"], "lifecycle": "TENTATIVE", "confidence": .7}
    world.ingest(Observation.create({**common, "frame_id": "mini", "visual_candidates": [minimap]}, 1.1, "MINIMAP_CV"))
    world.ingest(Observation.create({**common, "frame_id": "map", "visual_candidates": [worldmap]}, 1.2, "WORLD_MAP_CV"))
    markers = world.query.map_markers()
    assert {type(marker) for marker in markers} == {MapMarker}
    assert {marker.surface for marker in markers} == {"MINIMAP", "WORLD_MAP"}
    mini = world.query.map_markers("MINIMAP")[0]
    assert mini.local_position["dx"] == 4 and mini.world_position_if_proven is None
    assert mini.semantic_type == "UNKNOWN"


def test_minimap_marker_rejects_unproven_world_position():
    with pytest.raises(ValueError, match="TRUSTED"):
        MapMarker("m", "t", "MINIMAP", "SUPPORTED", .8,
                  local_position={"dx": 1., "dy": 2.},
                  world_position_if_proven={"x": .4, "y": .5, "transform_status": "CANDIDATE"})
