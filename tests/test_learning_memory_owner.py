from wowbot.agent.learning_memory import LearningMemory
from wowbot.agent.memory import AgentMemory


def context():
    return {"domain": "QUEST", "game_build": "12.1.0", "ui_scale": .7,
            "width": 1600, "height": 900}


def test_agent_memory_delegates_trials_to_learning_owner(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    try:
        assert isinstance(memory.learning_memory, LearningMemory)
        for at in range(5):
            memory.learn_procedure(context(), "MOVE", True, cost=1., at=float(at),
                                   reason="ok", provenance={"test": True})
        assert memory.procedure_profile(context(), "MOVE")["stage"] == "SUPPORTED"
        memory.record_sensor_outcome("WORLD3D", "NPC", context(), correct=True, at=1.,
                                     latency=.01, error="", provenance={},
                                     predicted_label="NPC", actual_label="NPC")
        assert memory.sensor_profile("WORLD3D", "NPC", context())["samples"] == 1
    finally:
        memory.close()


def test_learning_owner_expire_consolidate_and_reliability(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    try:
        owner = memory.learning_memory
        owner.record_sensor("MINIMAP", "*", context(), correct=True, at=1., latency=None,
                            error="", provenance={})
        assert owner.reliability("MINIMAP", "*", context()) is not None
        assert owner.expire(2., max_trials=0) == 1
        assert owner.consolidate(3.) == 0
    finally:
        memory.close()
