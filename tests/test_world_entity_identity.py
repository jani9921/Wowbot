from wowbot.agent.target_manager import TargetManager
from wowbot.runtime import ActiveSkillRuntime, Intent, WorldEntityId, world_entity_id


def test_world_entity_id_is_a_normalized_live_guid_not_a_guessed_identity():
    assert world_entity_id("  Creature-0-0-0-1-99-0001  ") == "Creature-0-0-0-1-99-0001"
    assert isinstance(world_entity_id("Creature-1"), WorldEntityId)
    assert world_entity_id("") is None
    assert world_entity_id(None) is None


def test_active_skill_normalizes_one_shared_entity_reference_at_action_boundary():
    runtime = ActiveSkillRuntime()
    state = runtime.start(intent=Intent("COMBAT", {"guid": "  Creature-42 "}),
                          attempt=object(), now=1.0)
    assert state.target_ref == "Creature-42"
    assert isinstance(state.target_ref, WorldEntityId)


def test_target_manager_never_promotes_an_npc_template_to_an_action_target():
    manager = TargetManager()
    assert manager.select([{"entity_id": "npc:156626", "quest_relevance": 1.0}]) is None
    selected = manager.select([{"guid": "Creature-42", "quest_relevance": 1.0}])
    assert selected is not None
    assert selected.entity_id == "Creature-42"
