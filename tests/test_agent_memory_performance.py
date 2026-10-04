import sqlite3

from wowbot.agent.memory import AgentMemory
from wowbot.agent.models import Observation


def test_observation_batch_is_ordered_and_indexed(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    observations = tuple(Observation.create({"session_id": "s", "frame_id": f"f{i}",
                                              "timestamp": i}, i, f"SOURCE_{i}")
                         for i in range(12))
    memory.observe_many(observations)
    restored = memory.observations("s")
    assert [item.source for item in restored] == [f"SOURCE_{i}" for i in range(12)]
    with sqlite3.connect(memory.path) as db:
        indexes = {row[1] for row in db.execute("PRAGMA index_list(observations)")}
    assert "idx_observations_recorded_order" in indexes


def test_observation_batch_does_not_duplicate_events(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    observation = Observation.create({"session_id": "s", "frame_id": "f", "timestamp": 1,
        "events": [{"sequence": 1, "event_type": "QUEST_ACCEPTED",
                    "payload": {"quest_id": 7}}]}, 1, "ADDON_QUEST")
    memory.observe_many((observation, observation))
    assert len(memory.observations("s")) == 1
    assert len(memory.events("s")) == 1


def test_hydration_accepts_explicit_null_wallclock_timestamp(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    observation = Observation.create({
        "session_id": "s", "frame_id": "fast:1", "timestamp": None,
        "transport_kind": "FAST", "telemetry_lane": "FAST_STATE",
        "position": {"x": .5, "y": .5},
    }, 12.5)
    memory.observe(observation)

    restored = memory.observations("s")

    assert len(restored) == 1
    assert restored[0].timestamp == 12.5


def test_world_relations_are_buffered_and_flushed_as_one_batch(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    for index in range(50):
        memory.save_world_relation("s", {
            "relation_id": f"r{index}", "subject": "player",
            "predicate": "sees", "object": f"track:{index}", "at": 1.0,
        })
    with sqlite3.connect(memory.path) as db:
        assert db.execute("SELECT COUNT(*) FROM world_relations").fetchone()[0] == 0
    assert memory.flush_world_relations() == 50
    assert len(memory.world_relations("s")) == 50
    memory.close()
