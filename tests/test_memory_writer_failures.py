"""Issues #71/#73: the background SQLite writer must not drop batches
silently, grow without bound, or report a partial history as complete."""
import threading

from wowbot.agent.memory import AgentMemory
from wowbot.agent.models import Observation


def _obs(i):
    return Observation.create({"session_id": "s", "frame_id": f"f:{i}", "timestamp": float(i),
                               "position": {"x": .5, "y": .5}}, float(i))


def _memory(tmp_path, monkeypatch=None):
    memory = AgentMemory(tmp_path / "memory.sqlite3", async_writes=True)
    memory.WRITE_RETRY_BACKOFF_SECONDS = 0.
    return memory


def test_transient_failure_is_retried_and_lands(tmp_path):
    memory = _memory(tmp_path)
    real, calls = memory._insert_observations, []
    def flaky(db, rows):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("disk busy")
        real(db, rows)
    memory._insert_observations = flaky
    memory.observe(_obs(1))
    assert memory.drain_writes(timeout=5.)
    assert len(memory.observations("s")) == 1
    assert memory.write_failures == 1 and memory.lost_write_batches == 0
    memory.close()


def test_permanent_failure_is_counted_and_drain_is_not_complete(tmp_path):
    memory = _memory(tmp_path)
    def broken(db, rows):
        raise RuntimeError("disk full")
    memory._insert_observations = broken
    memory.observe(_obs(1))
    assert memory.drain_writes(timeout=5.) is False
    assert memory.lost_write_batches == 1
    assert "disk full" in memory.writer_error
    world = memory.hydrate_world("s")
    assert world.__dict__["memory_history_complete"] is False
    assert memory.metrics()["lost_write_batches"] == 1
    memory.close()


def test_full_queue_applies_backpressure_then_fails_closed(tmp_path):
    memory = _memory(tmp_path)
    memory.WRITE_QUEUE_LIMIT = 4
    memory.WRITE_BACKPRESSURE_SECONDS = .05
    gate = threading.Event()
    real = memory._insert_observations
    def blocked(db, rows):
        gate.wait(5.)
        real(db, rows)
    memory._insert_observations = blocked
    for i in range(20):
        memory.observe(_obs(i))
    assert len(memory._write_queue) <= 4
    assert memory.lost_write_batches > 0 and memory.writer_error.endswith("write_queue_full")
    assert memory.drain_writes(timeout=.01) is False
    gate.set()
    assert memory.drain_writes(timeout=5.) is False     # loss stays visible
    assert memory.write_queue_peak <= 4
    memory.close()


def test_close_does_not_close_connection_under_a_live_writer(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    gate = threading.Event()
    real = memory._insert_observations
    def blocked(db, rows):
        gate.wait(5.)
        real(db, rows)
    memory._insert_observations = blocked
    memory.observe(_obs(1))
    monkeypatch.setattr(memory, "drain_writes", lambda timeout=10.: False)
    joined = []
    original_join = memory._writer_thread.join
    monkeypatch.setattr(memory._writer_thread, "join", lambda timeout=None: joined.append(timeout))
    memory.close()
    assert joined and memory._conn.execute("SELECT 1").fetchone() == (1,)   # still open
    gate.set()
    original_join(5.)
