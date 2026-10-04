from wowbot.agent.memory import AgentMemory
from types import SimpleNamespace


def context(map_id=1, build="12.1.0"):
    return {"domain": "QUEST", "map_id": map_id, "game_build": build,
            "addon_version": "0.8.1", "ui_scale": 1, "width": 1600, "height": 900}


def test_procedure_requires_repetition_and_generalizes_across_contexts(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    for i in range(5):
        memory.learn_procedure(context(), "MOVE", True, cost=.2, at=i, reason="ok", provenance={"action_id": str(i)})
    assert memory.procedure_profile(context(), "MOVE")["stage"] == "SUPPORTED"
    for map_id in (2, 3):
        for i in range(5):
            memory.learn_procedure(context(map_id), "MOVE", True, cost=.3, at=10+i,
                                   reason="ok", provenance={"action_id": f"{map_id}:{i}"})
    profile = memory.procedure_profile(context(), "MOVE")
    assert profile["stage"] == "GENERALIZED" and profile["contexts"] == 3
    assert profile["provenance"]["action_id"] == "4"


def test_one_failure_does_not_destroy_supported_strategy(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    for i in range(8):
        memory.learn_procedure(context(), "COMBAT", True, cost=1, at=i, reason="ok", provenance={})
    memory.learn_procedure(context(), "COMBAT", False, cost=2, at=9, reason="miss", provenance={})
    profile = memory.procedure_profile(context(), "COMBAT")
    assert profile["stage"] == "SUPPORTED" and profile["historical_reliability"] > .75


def test_sensor_recent_precision_changes_weight_and_detects_drift(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    for i in range(30):
        memory.record_sensor_outcome("MINIMAP_CV", "quest_giver", context(), correct=i < 22,
                                     at=i, latency=.02, error="" if i < 22 else "false_positive", provenance={})
    profile = memory.sensor_profile("MINIMAP_CV", "quest_giver", context())
    assert profile["historical_precision"] > profile["recent_precision"]
    assert profile["drift"] and profile["health"] == "DEGRADED"
    assert .15 <= profile["weight"] < .7


def test_patch_change_has_separate_sensor_context(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    memory.record_sensor_outcome("WORLD3D", "unknown", context(), correct=True, at=1,
                                 latency=.1, error="", provenance={})
    changed = memory.sensor_profile("WORLD3D", "unknown", context(build="12.2.0"))
    assert changed["samples"] == 0 and changed["health"] == "LEARNING"


def test_world_evidence_uses_learned_sensor_weight(tmp_path):
    from wowbot.agent.models import Observation
    from wowbot.agent.world import WorldModel
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    sensor_context = memory.learning_context({"map_id": 1, "game_build": "12.1.0",
        "addon_version": "0.8.1", "ui_scale": 1,
        "client_dimensions": {"width": 1600, "height": 900}}, "SENSOR")
    for i in range(8):
        memory.record_sensor_outcome("MINIMAP_CV", "*", sensor_context, correct=False,
                                     at=i, latency=.1, error="false_positive", provenance={})
    world = WorldModel(memory.sensor_weight)
    addon = {"session_id": "s", "frame_id": "a", "timestamp": 1, "map_id": 1,
        "game_build": "12.1.0", "addon_version": "0.8.1", "ui_scale": 1,
        "client_dimensions": {"width": 1600, "height": 900}, "player_present": True}
    world.ingest(Observation.create(addon, 1))
    world.ingest(Observation.create({"session_id": "s", "frame_id": "v", "confidence": 1,
                                     "marker": "?"}, 1.1, "MINIMAP_CV"))
    assert world.belief("marker", 1.2)["confidence"] < .4


def test_episode_contains_lifecycle_and_pattern_needs_repetition(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    goal = SimpleNamespace(goal_id="g1", domain="QUEST")
    first_id = None
    for index in range(3):
        goal.goal_id = f"g{index}"
        episode_id = memory.start_episode(goal, f"s{index}", {"map_id": 1, "game_build": "12.1.0"}, index*10)
        first_id = first_id or episode_id
        memory.record_episode_step(episode_id, index*10+.5, "ACTION_INTENT", {"skill": "MOVE"})
        memory.record_episode_step(episode_id, index*10+1, "VERIFICATION",
                                   {"skill": "MOVE", "outcome": "SUCCESS", "expected": "progress"})
        memory.finish_episode(episode_id, {"map_id": 1, "game_build": "12.1.0"}, index*10+2,
                              "SUCCESS", {"done": True})
        memory.finish_episode(episode_id, {"map_id": 1, "game_build": "12.1.0"}, index*10+3,
                              "SUCCESS", {"done": True})
    episode = memory.episode(first_id)
    assert episode["status"] == "SUCCESS" and [step["kind"] for step in episode["steps"]] == ["ACTION_INTENT", "VERIFICATION"]
    patterns = memory.task_patterns("QUEST")
    assert len(patterns) == 1 and patterns[0]["steps"] == ["MOVE"]
    assert patterns[0]["successes"] == 3 and patterns[0]["stage"] == "SUPPORTED"
    match = memory.find_similar_task_patterns("QUEST", ["MOVE"], {"map_id": 1})
    assert match["mode"] == "REUSE_CANDIDATE" and match["matches"][0]["similarity"] == 1
    novel = memory.find_similar_task_patterns("QUEST", ["FISH"], {"map_id": 1})
    assert novel["mode"] == "EXPLORATION" and novel["novelty"] > .8


def test_task_pattern_generalization_requires_multiple_contexts(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    goal = SimpleNamespace(goal_id="g", domain="QUEST")
    for index, map_id in enumerate((1, 1, 2, 2, 3)):
        goal.goal_id = f"g{index}"
        initial = {"map_id": map_id, "game_build": "12.1.0"}
        episode_id = memory.start_episode(goal, f"s{index}", initial, index*10)
        memory.record_episode_step(episode_id, index*10+1, "VERIFICATION",
                                   {"skill": "MOVE", "outcome": "SUCCESS", "expected": "progress"})
        memory.finish_episode(episode_id, initial, index*10+2, "SUCCESS", {})
    pattern = memory.task_patterns("QUEST")[0]
    assert pattern["stage"] == "GENERALIZED"
    assert len(pattern["provenance"]["context_keys"]) == 3
