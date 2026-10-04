import pytest

from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel


EXPECTED_SECTIONS = {
    "PlayerState", "TargetState", "EntityMap", "CombatState",
    "NavigationState", "QuestState", "InteractionState", "UIState",
    "MapState", "EnvironmentState", "RecoveryState",
}


def test_normalized_world_state_has_every_named_m1_4_section_and_update_time():
    world = WorldModel()
    payload = {
        "session_id": "s1", "timestamp": 10., "map_id": 2175,
        "health": 95, "is_dead": False, "is_in_combat": False,
        "position": {"x": .5, "y": .4}, "orientation": 1.2,
        "target": {"guid": "Creature-1", "dead": False},
        "active_quests": [], "quest_ui": {"open": False},
    }
    world.ingest(Observation.create(payload, 1.))
    snapshot = world.planning_snapshot(2.)
    contract = snapshot.normalized_state

    assert contract["Version"] == world.revision
    assert contract["UpdatedAt"] == 1.
    assert EXPECTED_SECTIONS <= set(contract)
    assert contract["PlayerState"]["AliveBelief"]["Value"] is True
    assert contract["TargetState"]["CurrentTargetId"] == "Creature-1"
    with pytest.raises(TypeError):
        contract["PlayerState"]["HealthEstimate"] = 1


def test_raw_visual_candidate_remains_unknown_without_confirmed_semantics():
    world = WorldModel()
    world.session_id = "s1"
    observation = Observation.create({
        "session_id": "s1", "timestamp": 2.,
        "visual_candidates": [{
            "track_id": "WORLD3D:t1", "semantic_type": "HOSTILE_ENTITY",
            "belief": "CANDIDATE", "confidence": .8,
            "x": .5, "y": .4, "bbox": [1, 2, 3, 4],
        }],
    }, 2., "WORLD3D")
    world.ingest(observation)
    entity = world.planning_snapshot(2.).normalized_state["EntityMap"]["WORLD3D:t1"]
    assert entity["BestClass"] == "UNKNOWN"
    assert entity["ClassDistribution"] == {"UNKNOWN": 1.0}
    assert observation.observation_id in entity["EvidenceRefs"]


def test_confirmed_semantic_entity_can_be_projected_without_changing_raw_state():
    world = WorldModel()
    world.session_id = "s1"
    candidate = {
        "track_id": "WORLD3D:t2", "semantic_type": "NPC",
        "belief": "CONFIRMED", "confidence": .95, "x": .4, "y": .3,
    }
    world.ingest(Observation.create({
        "session_id": "s1", "timestamp": 3.,
        "visual_candidates": [candidate],
    }, 3., "WORLD3D"))
    entity = world.snapshot(3.)["world_state_contract"]["EntityMap"]["WORLD3D:t2"]
    assert entity["BestClass"] == "NPC"
    assert candidate["belief"] == "CONFIRMED"
