from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.runtime import LogLevel, StructuredLogger


def test_structured_logger_preserves_correlation_and_bounds_history():
    logger = StructuredLogger(capacity=2)
    logger.log(1., "ACTION_INTENT", {"action_id": "a", "guid": "npc"})
    logger.log(2., "EXECUTOR_FAILURE", {"action_id": "b"})
    logger.log(3., "LOOP_CONFIRMED", {"action_id": "c"})
    entries = logger.snapshot()
    assert len(entries) == 2
    assert entries[-1]["level"] == LogLevel.CRITICAL
    assert entries[0]["correlation_id"] == "b"


def test_engine_record_path_publishes_structured_entry_without_changing_executor():
    agent = AutonomousAgent(RecordingExecutor())
    agent._record(1., "ACTION_INTENT", {"action_id": "a", "guid": "npc"})
    entry = agent.structured_logger.snapshot()[-1]
    assert entry["event_type"] == "ACTION_INTENT"
    assert entry["entity_id"] == "npc"
