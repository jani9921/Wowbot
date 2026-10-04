from wowbot.agent.memory import AgentMemory
from wowbot.vision.entity_memory import EntityMemory


def test_semantic_fact_requires_repetition_and_keeps_counterexamples(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    context = {"session_id": "s", "map_id": 1, "phase": None, "quest_state_revision": 2}
    for at in (1, 2, 3):
        memory.record_semantic_fact("npc:42", "QUEST_ROLE", "QUEST_GIVER", context,
                                    "ADDON_API", at, {"observation_id": f"o{at}"})
    supported = memory.semantic_facts(subject="npc:42", context=context, supported_only=True)
    assert len(supported) == 1 and supported[0]["stage"] == "SUPPORTED"
    memory.record_semantic_fact("npc:42", "QUEST_ROLE", "NONE", context,
                                "ADDON_API", 4, {"observation_id": "o4"})
    facts = memory.semantic_facts(subject="npc:42", context=context)
    giver = next(item for item in facts if item["value"] == "QUEST_GIVER")
    none = next(item for item in facts if item["value"] == "NONE")
    assert giver["failures"] == 1 and none["stage"] == "EPISODIC"


def test_dynamic_role_context_does_not_contradict_other_quest_revision(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    old = {"session_id": "s", "map_id": 1, "quest_state_revision": 1}
    new = {"session_id": "s", "map_id": 1, "quest_state_revision": 2}
    memory.record_semantic_fact("npc:42", "QUEST_ROLE", "QUEST_GIVER", old, "API", 1, {})
    memory.record_semantic_fact("npc:42", "QUEST_ROLE", "QUEST_TURN_IN", new, "API", 2, {})
    assert memory.semantic_facts(subject="npc:42", context=old)[0]["failures"] == 0
    assert memory.semantic_facts(subject="npc:42", context=new)[0]["failures"] == 0


def test_npc_behavior_needs_repeated_explicit_world_sightings(tmp_path):
    memory = EntityMemory(tmp_path / "entity.sqlite3")
    unit = {"npc_id": 42, "unit_type": "NPC", "guid": "g"}
    for at in (1, 2):
        memory.record_mouseover(unit, map_id=1, map_x=.2, map_y=.3, zone="Z",
                                observed_at=at, phase="p1", observation_id=f"o{at}")
    assert memory.behavior("npc:42")["status"] == "EPISODIC"
    memory.record_mouseover(unit, map_id=1, map_x=.201, map_y=.301, zone="Z",
                            observed_at=3, phase="p1", observation_id="o3")
    behavior = memory.behavior("npc:42")
    assert behavior["behavior"] == "STATIONARY" and behavior["status"] == "SUPPORTED"
    assert behavior["phases"] == ["p1"] and behavior["spawn_region"]["map_id"] == 1


def test_npc_patrol_stays_hypothesis_until_repeated_transitions(tmp_path):
    memory = EntityMemory(tmp_path / "entity.sqlite3")
    unit = {"npc_id": 7, "unit_type": "NPC"}
    for at, x in enumerate((.1, .2, .1, .2, .1), 1):
        memory.record_mouseover(unit, map_id=1, map_x=x, map_y=.3, zone="Z",
                                observed_at=at, instance_id="i1", observation_id=f"o{at}")
    behavior = memory.behavior("npc:7")
    assert behavior["behavior"] == "PATROL_HYPOTHESIS"
    assert behavior["status"] == "SUPPORTED" and behavior["transitions"] == 4
