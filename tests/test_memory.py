from wowbot.navigation.memory import NavigationMemory


def test_route_experience_records_outcome(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation.db")
    memory.record_route("r1", zone="Test", start_key="A", destination_key="B", node_ids_json='["A","B"]')
    memory.record_outcome("r1", success=True, elapsed_seconds=12.0)
    memory.record_outcome("r1", success=False, stuck_count=1, replan_count=2)

    exp = memory.get_experience("r1")
    assert exp is not None
    assert exp.attempts == 2
    assert exp.successes == 1
    assert exp.failures == 1
    assert exp.avg_time == 12.0
    assert exp.stuck_count == 1
    assert exp.replan_count == 2
