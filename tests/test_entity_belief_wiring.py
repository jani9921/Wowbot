"""V4-010 wiring: real per-source identity evidence feeding fuse_identity()."""
from wowbot.agent.entity_belief import IdentityEvidence
from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel
from wowbot.agent.world_entity_reducer import _identity_source_tag


def _state(frame, *, target=None, mouseover=None, source_map_id=1):
    return {"session_id": "identity-session", "frame_id": frame, "timestamp": float(frame),
            "map_id": source_map_id, "phase": "p1", "instance_id": 10,
            "zone_name": "Test Zone", "quest_state_revision": 1,
            "level": 2, "is_in_combat": False, "player_present": True,
            "position": {"x": .1, "y": .1}, "target": target, "mouseover": mouseover,
            "active_quests": [], "actionbar": []}


def _unit(name, **extra):
    value = {"guid": "Creature-42", "npc_id": 42, "name": name, "unit_type": "NPC"}
    value.update(extra)
    return value


def test_identity_source_tag_mapping_is_grounded_in_real_sensor_sources():
    assert _identity_source_tag("target", "ADDON_TELEMETRY") == "target_frame_tooltip_name"
    assert _identity_source_tag("mouseover", "ADDON_TELEMETRY") == "stable_nameplate_text"
    assert _identity_source_tag("target", "MINIMAP_CV") == "quest_marker_and_context"
    assert _identity_source_tag("target", "WORLD3D") == "visual_appearance_classifier"
    assert _identity_source_tag("target", "SOMETHING_UNMAPPED") == "SOMETHING_UNMAPPED"


def test_ingest_records_identity_evidence_for_addon_target():
    world = WorldModel()
    world.ingest(Observation.create(_state(1, target=_unit("Guide")), 1))
    entries = world.entity_identity_evidence["npc:42"]
    assert len(entries) == 1
    assert entries[0] == IdentityEvidence("target_frame_tooltip_name", "Guide", 1.0, entries[0].at)


def test_world_query_entity_belief_fuses_recorded_evidence():
    world = WorldModel()
    world.ingest(Observation.create(_state(1, target=_unit("Guide")), 1))
    belief = world.query.entity_belief("npc:42", now=1.0)
    assert belief.identity_belief == "Guide"
    assert belief.confidence > 0.9


def test_world_query_entity_belief_with_no_evidence_is_zero_confidence():
    world = WorldModel()
    belief = world.query.entity_belief("npc:does-not-exist", now=1.0)
    assert belief.identity_belief is None
    assert belief.confidence == 0.0
