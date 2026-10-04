"""Typed JSONL recording and deterministic, input-free replay.

Replay is deliberately a diagnostics boundary.  It can feed records to a
caller-supplied in-memory consumer, but it never imports or invokes the real
input executor.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum, StrEnum
import json
from pathlib import Path
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4


REPLAY_SCHEMA = "aipc.runtime-replay.v1"


class ReplayRecordKind(StrEnum):
    SESSION_START = "SESSION_START"
    OBSERVATION = "OBSERVATION"
    EVENT = "EVENT"
    WORLD_DELTA = "WORLD_DELTA"
    SKILL_TRANSITION = "SKILL_TRANSITION"
    COMMAND = "COMMAND"
    VERIFICATION = "VERIFICATION"
    CHECKPOINT = "CHECKPOINT"
    SESSION_END = "SESSION_END"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {str(key): _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


@dataclass(frozen=True)
class ReplayRecord:
    sequence: int
    kind: ReplayRecordKind
    at: float
    session_id: str
    correlation_id: str | None
    payload: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, line_number: int) -> "ReplayRecord":
        if value.get("schema") != REPLAY_SCHEMA:
            raise ValueError(f"unsupported replay schema at line {line_number}")
        try:
            kind = ReplayRecordKind(str(value["kind"]))
            sequence = int(value["sequence"])
            at = float(value["at"])
            session_id = str(value["session_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid replay record at line {line_number}") from exc
        payload = value.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError(f"invalid replay payload at line {line_number}")
        correlation = value.get("correlation_id")
        return cls(sequence, kind, at, session_id,
                   None if correlation is None else str(correlation), dict(payload))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": REPLAY_SCHEMA,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "at": self.at,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "payload": _jsonable(self.payload),
        }


class ReplayRecorder:
    """Append-only recorder covering the runtime's observable boundaries."""

    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self._clock = clock
        self._handle = None
        self._session_id: str | None = None
        self._sequence = 0

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    def start_session(self, *, session_id: str | None = None,
                      metadata: Mapping[str, Any] | None = None) -> str:
        if self.is_open:
            raise RuntimeError("replay session already open")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")
        self._session_id = session_id or uuid4().hex
        self._sequence = 0
        self._append(ReplayRecordKind.SESSION_START, dict(metadata or {}))
        return self._session_id

    def record_observation(self, observation: Any, *, correlation_id: str | None = None) -> None:
        self._append(ReplayRecordKind.OBSERVATION, {"observation": _jsonable(observation)}, correlation_id)

    def record_event(self, event: Any, *, correlation_id: str | None = None) -> None:
        self._append(ReplayRecordKind.EVENT, {"event": _jsonable(event)}, correlation_id)

    def record_world_delta(self, delta: Any, *, correlation_id: str | None = None) -> None:
        self._append(ReplayRecordKind.WORLD_DELTA, {"delta": _jsonable(delta)}, correlation_id)

    def record_skill_transition(self, skill: str, previous: Any, current: Any, *,
                                reason: Any = None, correlation_id: str | None = None) -> None:
        self._append(ReplayRecordKind.SKILL_TRANSITION, {
            "skill": skill,
            "previous": _jsonable(previous),
            "current": _jsonable(current),
            "reason": _jsonable(reason),
        }, correlation_id)

    def record_command(self, command: Any, *, correlation_id: str | None = None) -> None:
        # A command is recorded as data only.  ReplayPlayer has no executor.
        self._append(ReplayRecordKind.COMMAND, {"command": _jsonable(command)}, correlation_id)

    def record_verification(self, verification: Any, *, correlation_id: str | None = None) -> None:
        self._append(ReplayRecordKind.VERIFICATION,
                     {"verification": _jsonable(verification)}, correlation_id)

    def checkpoint(self, state: Any = None, *, correlation_id: str | None = None) -> None:
        self._append(ReplayRecordKind.CHECKPOINT, {"state": _jsonable(state)}, correlation_id)
        assert self._handle is not None
        self._handle.flush()

    def close(self, *, metadata: Mapping[str, Any] | None = None) -> None:
        if not self.is_open:
            return
        self._append(ReplayRecordKind.SESSION_END, dict(metadata or {}))
        assert self._handle is not None
        self._handle.flush()
        self._handle.close()
        self._handle = None
        self._session_id = None

    def __enter__(self) -> "ReplayRecorder":
        self.start_session()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close(metadata={"exception": None if exc is None else type(exc).__name__})

    def _append(self, kind: ReplayRecordKind, payload: dict[str, Any],
                correlation_id: str | None = None) -> None:
        if self._handle is None or self._session_id is None:
            raise RuntimeError("start_session() must be called before recording")
        record = ReplayRecord(self._sequence, kind, float(self._clock()), self._session_id,
                              correlation_id, payload)
        self._sequence += 1
        self._handle.write(json.dumps(record.to_mapping(), ensure_ascii=False,
                                      separators=(",", ":")) + "\n")


@dataclass(frozen=True)
class ReplayComparison:
    equal: bool
    compared_records: int
    first_mismatch: int | None = None
    expected: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None


class ReplayPlayer:
    """Cursor-based deterministic replay with no real-executor dependency."""

    def __init__(self) -> None:
        self.records: tuple[ReplayRecord, ...] = ()
        self.position = 0

    def load(self, path: str | Path, *, session_id: str | None = None) -> tuple[ReplayRecord, ...]:
        loaded: list[ReplayRecord] = []
        with Path(path).open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError(f"invalid replay record at line {line_number}")
                record = ReplayRecord.from_mapping(raw, line_number=line_number)
                if session_id is None or record.session_id == session_id:
                    loaded.append(record)
        for previous, current in zip(loaded, loaded[1:]):
            if current.session_id == previous.session_id and current.sequence <= previous.sequence:
                raise ValueError("replay sequence is not strictly increasing")
        self.records = tuple(loaded)
        self.position = 0
        return self.records

    def seek(self, position: int) -> None:
        if position < 0 or position > len(self.records):
            raise IndexError("replay seek outside loaded record range")
        self.position = position

    def step(self) -> ReplayRecord | None:
        if self.position >= len(self.records):
            return None
        record = self.records[self.position]
        self.position += 1
        return record

    def run(self, consumer: Callable[[ReplayRecord], Any] | None = None) -> tuple[ReplayRecord, ...]:
        emitted: list[ReplayRecord] = []
        while (record := self.step()) is not None:
            emitted.append(record)
            if consumer is not None:
                consumer(record)
        return tuple(emitted)

    def inject_into_runtime(self, consumer: Callable[[ReplayRecord], Any]) -> tuple[ReplayRecord, ...]:
        """Feed an offline/in-memory runtime adapter; never an input executor."""
        if not callable(consumer):
            raise TypeError("replay consumer must be callable")
        if getattr(consumer, "is_real_input_executor", False):
            raise ValueError("real input executors are forbidden during replay")
        return self.run(consumer)

    def compare_golden_trace(self, golden: str | Path | Sequence[ReplayRecord]) -> ReplayComparison:
        expected = self._records_from(golden)
        actual = self.records
        compared = min(len(expected), len(actual))
        for index in range(compared):
            expected_value = self._stable_value(expected[index])
            actual_value = self._stable_value(actual[index])
            if expected_value != actual_value:
                return ReplayComparison(False, index + 1, index, expected_value, actual_value)
        if len(expected) != len(actual):
            index = compared
            return ReplayComparison(
                False, compared, index,
                None if index >= len(expected) else self._stable_value(expected[index]),
                None if index >= len(actual) else self._stable_value(actual[index]),
            )
        return ReplayComparison(True, compared)

    @staticmethod
    def _records_from(value: str | Path | Sequence[ReplayRecord]) -> tuple[ReplayRecord, ...]:
        if isinstance(value, (str, Path)):
            return ReplayPlayer().load(value)
        return tuple(value)

    @staticmethod
    def _stable_value(record: ReplayRecord) -> dict[str, Any]:
        # Wall-clock and generated session identity are transport metadata, not
        # behavioural golden-trace content.
        return {
            "sequence": record.sequence,
            "kind": record.kind.value,
            "correlation_id": record.correlation_id,
            "payload": _jsonable(record.payload),
        }
