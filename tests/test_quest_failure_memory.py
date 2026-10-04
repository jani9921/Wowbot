from wowbot.agent.quest_failure_memory import QuestFailureMemory


def test_quest_failure_memory_suppresses_only_the_same_bounded_action_key():
    memory = QuestFailureMemory(cooldown_seconds=10.)
    memory.record(quest_id=1, objective_id="1:kill", target_ref="mob-a",
                  skill="COMBAT", reason="quest_credit_not_received", now=5.)

    assert not memory.permits(quest_id=1, objective_id="1:kill", target_ref="mob-a", skill="COMBAT", now=6.)
    assert memory.permits(quest_id=1, objective_id="1:kill", target_ref="mob-b", skill="COMBAT", now=6.)
    assert memory.permits(quest_id=1, objective_id="1:loot", target_ref="mob-a", skill="COMBAT", now=6.)
    assert memory.permits(quest_id=1, objective_id="1:kill", target_ref="mob-a", skill="COMBAT", now=15.)


def test_snapshot_filter_keeps_different_skill_available():
    memory = QuestFailureMemory()
    memory.record(quest_id=1, objective_id="1:talk", target_ref="npc", skill="INTERACT", reason="no_response", now=1.)
    snapshot = memory.snapshot(2.)
    params = {"quest_id": 1, "objective_id": "1:talk", "guid": "npc"}

    assert not QuestFailureMemory.permits_snapshot(snapshot, params, "INTERACT", 2.)
    assert QuestFailureMemory.permits_snapshot(snapshot, params, "TALK", 2.)
