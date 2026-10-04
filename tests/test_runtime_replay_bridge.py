from wowbot.diagnostics import ReplayPlayer, ReplayRecordKind, RuntimeReplayBridge
from wowbot.runtime import StructuredLogger


class Agent:
    def __init__(self):
        self.structured_logger = StructuredLogger()


class World:
    revision = 2
    section_updates = {"PLAYER": {"observation_id": "obs-1"}}
    latest = type("Latest", (), {
        "observation_id": "obs-1", "correlation_id": "frame-1"})()


def test_runtime_bridge_records_logs_commands_verification_and_world_delta(tmp_path):
    agent = Agent()
    bridge = RuntimeReplayBridge(tmp_path / "runtime.jsonl")
    bridge.start(agent=agent, metadata={"pid": 123})
    agent.structured_logger.log(1.0, "ACTION_EXECUTED", {
        "action_id": "a1", "skill": "MOVE",
        "commands": [{"kind": "BIND", "binding": "MOVEFORWARD"}],
    })
    agent.structured_logger.log(1.1, "VERIFICATION", {
        "verification_id": "v1", "outcome": "SUCCESS",
    })
    bridge.record_world_delta(World())
    bridge.record_world_delta(World())  # same revision is deduplicated
    bridge.close()

    records = ReplayPlayer().load(tmp_path / "runtime.jsonl")
    kinds = [record.kind for record in records]
    assert ReplayRecordKind.COMMAND in kinds
    assert ReplayRecordKind.VERIFICATION in kinds
    assert kinds.count(ReplayRecordKind.WORLD_DELTA) == 1
    assert ReplayRecordKind.SKILL_TRANSITION in kinds


def test_diagnostic_sink_failure_never_breaks_structured_logging():
    logger = StructuredLogger()
    logger.subscribe(lambda entry: (_ for _ in ()).throw(RuntimeError("diagnostic failure")))
    logger.log(1.0, "TEST_EVENT", {"value": 1})
    assert logger.snapshot()[0]["event_type"] == "TEST_EVENT"
