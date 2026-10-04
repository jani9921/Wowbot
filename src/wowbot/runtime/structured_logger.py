"""Bounded structured diagnostics for the canonical runtime pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Callable


class LogLevel(StrEnum):
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class StructuredLogEntry:
    at: float
    level: LogLevel
    module: str
    event_type: str
    correlation_id: str | None
    entity_id: str | None
    message: str
    payload: dict[str, Any]


class StructuredLogger:
    """Diagnostic sink only; it cannot affect plans, skills or input."""

    _ERROR_EVENTS = frozenset({"EXECUTOR_FAILURE", "SYSTEM_HEALTH_FAILURE", "PREDICTION_ERROR"})
    _CRITICAL_EVENTS = frozenset({"LOOP_CONFIRMED", "PLAYER_DIED", "CONNECTION_LOST",
                                  "STUCK_DETECTED", "UI_FATAL_MODAL"})
    _WARNING_EVENTS = frozenset({"POSSIBLE_STUCK", "STUCK_RECOVERY", "SAFETY_PAUSED"})

    def __init__(self, capacity: int = 512) -> None:
        self.capacity = max(1, int(capacity))
        self._entries: list[StructuredLogEntry] = []
        # snapshot() is built on the control thread every tick; profiling a
        # 6000-tick session showed its 64 deep asdict() calls per tick as the
        # single largest status cost. Entries are frozen and appended once, so
        # serialize each exactly once here, in lockstep with _entries.
        self._serialized: list[dict] = []
        self._sinks: list[Callable[[StructuredLogEntry], None]] = []

    def subscribe(self, sink: Callable[[StructuredLogEntry], None]) -> Callable[[], None]:
        """Attach a diagnostic observer; it can never affect agent control."""
        if not callable(sink):
            raise TypeError("structured-log sink must be callable")
        self._sinks.append(sink)

        def unsubscribe() -> None:
            if sink in self._sinks:
                self._sinks.remove(sink)
        return unsubscribe

    def log(self, at: float, event_type: str, payload: dict | None = None, *, module: str = "AutonomousAgent") -> None:
        payload = dict(payload or {})
        level = (LogLevel.CRITICAL if event_type in self._CRITICAL_EVENTS else
                 LogLevel.ERROR if event_type in self._ERROR_EVENTS else
                 LogLevel.WARN if event_type in self._WARNING_EVENTS else
                 LogLevel.WARN if "FAIL" in event_type or "CANCEL" in event_type else
                 LogLevel.INFO)
        correlation = str(payload.get("correlation_id") or payload.get("action_id")
                          or payload.get("plan_id") or payload.get("verification_id") or "") or None
        entity = str(payload.get("entity_id") or payload.get("guid") or payload.get("target_guid") or "") or None
        entry = StructuredLogEntry(float(at), level, module, str(event_type), correlation,
                                   entity, str(event_type).replace("_", " ").lower(), payload)
        self._entries.append(entry)
        self._serialized.append(asdict(entry))
        del self._entries[:-self.capacity]
        del self._serialized[:-self.capacity]
        for sink in tuple(self._sinks):
            try:
                sink(entry)
            except Exception:
                # Diagnostics must never change planner/input behavior.
                continue

    def snapshot(self, limit: int = 64) -> list[dict]:
        # Returns the cached per-entry dicts; consumers only serialize them.
        return list(self._serialized[-max(1, int(limit)):])
