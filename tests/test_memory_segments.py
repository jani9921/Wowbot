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
