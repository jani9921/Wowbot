from wowbot.navigation.memory import NavigationMemory


def test_segment_experience_records_blocked_event(tmp_path):
    m = NavigationMemory(tmp_path / 'nav.db')
    m.record_segment_outcome('A->B', success=False, blocked=True)
    m.record_segment_outcome('A->B', success=True, elapsed_seconds=4)
    exp = m.get_segment_experience('A->B')
    assert exp is not None
    assert exp.attempts == 2
    assert exp.blocked_count == 1
    assert exp.success_rate == 0.5


def test_navigation_memory_keeps_one_connection_and_closes_it(tmp_path):
    """Issue #33: a new, never-closed sqlite connection per call (no WAL)."""
    import sqlite3
    import pytest
    from wowbot.navigation.memory import NavigationMemory
    memory = NavigationMemory(tmp_path / "nav.sqlite3")
    connection = memory._conn
    memory.record_route("r", zone="z", start_key="a", destination_key="b", node_ids=["a", "b"])
    memory.record_outcome("r", success=True, elapsed_seconds=2.)
    assert memory._conn is connection
    assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert memory.get_experience("r").successes == 1
    memory.close()
    memory.close()
    with pytest.raises(sqlite3.ProgrammingError):
        memory.get_experience("r")
