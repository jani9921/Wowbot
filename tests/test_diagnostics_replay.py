from dataclasses import dataclass

import pytest

from wowbot.diagnostics import ReplayPlayer, ReplayRecordKind, ReplayRecorder


@dataclass(frozen=True)
class ExampleCommand:
    binding: str
    duration_ms: int


def _record_session(path, *, command="INTERACT"):
    times = iter((1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8))
    recorder = ReplayRecorder(path, clock=lambda: next(times))
    recorder.start_session(session_id="test", metadata={"pid": 123})
    recorder.record_observation({"observation_id": "o1"}, correlation_id="attempt-1")
    recorder.record_event({"event_type": "QUEST_DETAIL"})
    recorder.record_world_delta({"quest_ui": {"open": True}})
    recorder.record_skill_transition("INTERACT", "RUNNING", "SUCCESS")
    recorder.record_command(ExampleCommand(command, 50))
    recorder.record_verification({"success": True, "confidence": .95})
    recorder.checkpoint({"active_skill": None})
    recorder.close()


def test_recorder_covers_all_runtime_record_kinds_and_round_trips(tmp_path):
    path = tmp_path / "trace.jsonl"
    _record_session(path)

    player = ReplayPlayer()
    records = player.load(path)
    assert tuple(record.kind for record in records) == (
        ReplayRecordKind.SESSION_START,
        ReplayRecordKind.OBSERVATION,
        ReplayRecordKind.EVENT,
        ReplayRecordKind.WORLD_DELTA,
        ReplayRecordKind.SKILL_TRANSITION,
        ReplayRecordKind.COMMAND,
        ReplayRecordKind.VERIFICATION,
        ReplayRecordKind.CHECKPOINT,
        ReplayRecordKind.SESSION_END,
    )
    assert records[5].payload["command"] == {"binding": "INTERACT", "duration_ms": 50}


def test_player_supports_seek_step_run_and_offline_injection(tmp_path):
    path = tmp_path / "trace.jsonl"
    _record_session(path)
    player = ReplayPlayer()
    player.load(path)
    player.seek(5)
    assert player.step().kind is ReplayRecordKind.COMMAND
    seen = []
    player.seek(6)
    emitted = player.inject_into_runtime(seen.append)
    assert [record.kind for record in emitted] == [
        ReplayRecordKind.VERIFICATION,
        ReplayRecordKind.CHECKPOINT,
        ReplayRecordKind.SESSION_END,
    ]
    assert seen == list(emitted)


def test_replay_refuses_a_consumer_marked_as_real_input_executor(tmp_path):
    path = tmp_path / "trace.jsonl"
    _record_session(path)
    player = ReplayPlayer()
    player.load(path)

    class RealExecutor:
        is_real_input_executor = True

        def __call__(self, record):
            raise AssertionError("must never be called")

    with pytest.raises(ValueError, match="forbidden"):
        player.inject_into_runtime(RealExecutor())


def test_golden_trace_ignores_wall_clock_but_reports_first_behaviour_mismatch(tmp_path):
    golden = tmp_path / "golden.jsonl"
    actual = tmp_path / "actual.jsonl"
    changed = tmp_path / "changed.jsonl"
    _record_session(golden)
    _record_session(actual)
    _record_session(changed, command="JUMP")

    player = ReplayPlayer()
    player.load(actual)
    assert player.compare_golden_trace(golden).equal

    player.load(changed)
    mismatch = player.compare_golden_trace(golden)
    assert not mismatch.equal
    assert mismatch.first_mismatch == 5
    assert mismatch.expected["payload"]["command"]["binding"] == "INTERACT"
    assert mismatch.actual["payload"]["command"]["binding"] == "JUMP"


def test_recording_requires_an_open_session_and_close_is_idempotent(tmp_path):
    recorder = ReplayRecorder(tmp_path / "trace.jsonl")
    with pytest.raises(RuntimeError, match="start_session"):
        recorder.record_event({"event": "x"})
    recorder.start_session(session_id="one")
    with pytest.raises(RuntimeError, match="already open"):
        recorder.start_session(session_id="two")
    recorder.close()
    recorder.close()
