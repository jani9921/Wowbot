import sqlite3

import pytest

from wowbot.agent.memory import AgentMemory


def _count(path):
    with sqlite3.connect(path) as other:
        return other.execute("SELECT COUNT(*) FROM goal_tasks").fetchone()[0]


def _task(task_id):
    return {"task_id": task_id, "goal_id": "g", "status": "OPEN", "score": 1.0, "updated_at": 0.0}


def test_deferred_commit_batches_scopes_and_close_makes_them_durable(tmp_path):
    path = tmp_path / "agent_memory.sqlite3"
    memory = AgentMemory(path, commit_interval_seconds=3600)
    with memory.batch():
        memory.save_goal_task(_task("a"))
    with memory.batch():
        memory.save_goal_task(_task("b"))
    assert _count(path) == 0                       # not yet committed for other readers
    assert len(memory.goal_tasks("g")) == 2        # the owning connection sees its writes
    memory.close()
    assert _count(path) == 2


def test_failed_scope_rolls_back_only_its_own_writes(tmp_path):
    path = tmp_path / "agent_memory.sqlite3"
    memory = AgentMemory(path, commit_interval_seconds=3600)
    with memory.batch():
        memory.save_goal_task(_task("kept"))
    with pytest.raises(RuntimeError):
        with memory.batch():
            memory.save_goal_task(_task("discarded"))
            raise RuntimeError("tick failed")
    memory.commit_pending()
    assert [task["task_id"] for task in memory.goal_tasks("g")] == ["kept"]
    assert _count(path) == 1
    memory.close()


def test_zero_interval_keeps_commit_per_scope(tmp_path):
    path = tmp_path / "agent_memory.sqlite3"
    memory = AgentMemory(path)
    with memory.batch():
        memory.save_goal_task(_task("a"))
    assert _count(path) == 1
    memory.close()
