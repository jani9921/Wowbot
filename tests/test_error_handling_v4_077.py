"""V4-077: close()-time exception swallowing must be logged, not silent."""
import logging
import sqlite3

import pytest

from wowbot.agent.memory import AgentMemory
from wowbot.vision.entity_memory import EntityMemory
from wowbot.vision.world_point_memory import WorldPointMemory


def test_agent_memory_close_failure_is_logged_not_silent(tmp_path, caplog):
    memory = AgentMemory(tmp_path / "agent_memory.sqlite3")

    class _FailingConn:
        def close(self):
            raise sqlite3.OperationalError("boom")

    memory._conn = _FailingConn()
    with caplog.at_level(logging.WARNING, logger="wowbot.agent.memory"):
        memory.close()  # must not raise
    assert any("close" in record.message.lower() for record in caplog.records)


def test_entity_memory_close_failure_is_logged_not_silent(tmp_path, caplog):
    memory = EntityMemory(tmp_path / "entity_memory.sqlite3")

    class _FailingConn:
        def close(self):
            raise sqlite3.OperationalError("boom")

    memory._conn = _FailingConn()
    with caplog.at_level(logging.WARNING, logger="wowbot.vision.entity_memory"):
        memory.close()  # must not raise
    assert any("close" in record.message.lower() for record in caplog.records)


def test_world_point_memory_close_failure_is_logged_not_silent(tmp_path, caplog):
    memory = WorldPointMemory(tmp_path / "world_point_memory.sqlite3")

    class _FailingConn:
        def close(self):
            raise sqlite3.OperationalError("boom")

    memory._conn = _FailingConn()
    with caplog.at_level(logging.WARNING, logger="wowbot.vision.world_point_memory"):
        memory.close()  # must not raise
    assert any("close" in record.message.lower() for record in caplog.records)
