from wowbot.navigation.learning import LearningPolicy
from wowbot.navigation.memory import NavigationMemory


def test_learning_prefers_reliable_route(tmp_path):
    m = NavigationMemory(tmp_path / 'n.db')
    m.record_route('good', zone='x', start_key='A', destination_key='B', node_ids=['A','B'])
    for _ in range(8):
        m.record_outcome('good', success=True, elapsed_seconds=1)
    score = LearningPolicy(m).score_route('good')
    assert score.score > 0.7
    assert score.confidence > 0.3


def test_learning_changes_segment_cost(tmp_path):
    m = NavigationMemory(tmp_path / 'n2.db')
    for _ in range(10):
        m.record_segment_outcome('bad-segment', success=False, blocked=True)
    policy = LearningPolicy(m)
    assert policy.segment_cost_multiplier('bad-segment') > 1.5
