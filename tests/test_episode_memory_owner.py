from contextlib import contextmanager
import sqlite3
from types import SimpleNamespace

from wowbot.agent.episode_memory import EpisodeMemory


def test_episode_memory_owns_lifecycle_and_promotes_only_first_success_write():
    database = sqlite3.connect(":memory:")
    database.executescript("""
        CREATE TABLE episodes (
            id TEXT PRIMARY KEY, goal_id TEXT, session TEXT, domain TEXT,
            started_at REAL, ended_at REAL, status TEXT,
            initial_state TEXT, final_state TEXT, result TEXT);
        CREATE TABLE episode_steps (
            episode_id TEXT, sequence INTEGER, at REAL, kind TEXT, payload TEXT,
            PRIMARY KEY(episode_id,sequence));
    """)

    @contextmanager
    def transaction():
        try:
            yield database
            database.commit()
        except BaseException:
            database.rollback()
            raise

    promoted = []
    memory = EpisodeMemory(transaction, promote=promoted.append)
    goal = SimpleNamespace(goal_id="goal", domain="QUEST")
    episode_id = memory.start(goal, "session", {"map_id": 1}, 1.)
    memory.record_step(episode_id, 1.1, "ACTION_INTENT", {"skill": "MOVE"})
    memory.finish(episode_id, {"map_id": 2}, 2., "SUCCESS", {"verified": True})
    memory.finish(episode_id, {"map_id": 3}, 3., "FAILURE", {})

    episode = memory.get(episode_id)
    assert episode["status"] == "SUCCESS" and episode["final_state"] == {"map_id": 2}
    assert episode["steps"][0]["kind"] == "ACTION_INTENT"
    assert promoted == [episode_id]
