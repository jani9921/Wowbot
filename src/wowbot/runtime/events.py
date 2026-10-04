"""Bounded, observable event delivery for the canonical runtime.

The bus stores no world belief, selects no skill and sends no input.  It only
provides ordered delivery, bounded backpressure and an audit trail between
producers (perception, skills, supervisor) and the canonical WorldModel loop.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
import threading
from typing import Any

from .contracts import RuntimeEvent
from .backpressure import prioritize_critical_event


class EventBus:
    """In-process event bus with explicit critical-event handling.

    Critical events are never silently dropped. If a bounded queue is full,
    an ordinary/coalescible event is evicted first; only a queue made entirely
    of critical events may temporarily exceed its normal capacity, and that is
    visible through ``diagnostics``.
    """

    _MAX_SEEN_EVENT_IDS = 4096
    _DEFAULT_MAX_EVENTS = 1024
    _CRITICAL = frozenset({
        "PLAYER_DIED", "DEATH", "DISCONNECTED", "COMBAT_STARTED", "COMBAT_ENDED",
        "STUCK_DETECTED", "TARGET_DEAD", "QUEST_COMPLETE", "QUEST_ACCEPTED",
        "SPELL_CAST_FAILED", "UI_FATAL_MODAL", "EXECUTOR_FAILURE",
        "LOOP_CONFIRMED",
    })
    _COALESCIBLE = frozenset({"ENTITY_UPDATED", "MOVEMENT_PROGRESS", "FREE_SPACE_UPDATED"})
    _PRIORITY = {
        "PLAYER_DIED": 0, "DEATH": 0, "DISCONNECTED": 0, "EXECUTOR_FAILURE": 0,
        "LOOP_CONFIRMED": 0,
        "LOADING_STARTED": 1, "CINEMATIC_STARTED": 1, "UI_FATAL_MODAL": 1,
        "WORLD_OBSERVATION_UPDATED": 2,
        "SKILL_SUCCEEDED": 3, "SKILL_FAILURE": 3, "SKILL_CANCELLED": 3, "SKILL_SUCCESS": 3,
        "QUEST_CREDIT_OBSERVED": 4,
        "COMBAT_STARTED": 5, "UI_BLOCKING_STATE": 5,
        "SKILL_STARTED": 6,
    }

    def __init__(self, *, max_events: int = _DEFAULT_MAX_EVENTS,
                 history_size: int = 512) -> None:
        self.max_events = max(8, int(max_events))
        self._events: deque[tuple[int, RuntimeEvent]] = deque()
        self._history: deque[RuntimeEvent] = deque(maxlen=max(8, int(history_size)))
        self._seen_event_ids: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._subscribers: dict[str, tuple[str | None, Callable[[RuntimeEvent], None]]] = {}
        self._sequence = 0
        self._subscriber_sequence = 0
        self._coalesced = 0
        self._dropped = 0
        self._critical_overflow = 0
        self._subscriber_errors: deque[dict[str, Any]] = deque(maxlen=32)
        self._last_published_at: float | None = None
        self._last_consumed_at: float | None = None
        self._lock = threading.RLock()

    def publish(self, event: RuntimeEvent) -> bool:
        """Publish one event; false means duplicate or safely dropped low value."""
        with self._lock:
            return self._publish_locked(event)

    def _publish_locked(self, event: RuntimeEvent) -> bool:
        if event.event_id and not self._accept_event_id(event.event_id):
            return False
        if event.event_type in self._COALESCIBLE:
            self._coalesce(event)
        if len(self._events) >= self.max_events and not self._make_space(event):
            return False
        self._sequence += 1
        self._events.append((self._sequence, event))
        self._history.append(event)
        self._last_published_at = float(event.at)
        self._deliver(event)
        return True

    def publish_critical(self, event: RuntimeEvent) -> bool:
        """Publish a safety event without depending on the producer's label."""
        if event.event_type not in self._CRITICAL:
            event = RuntimeEvent("SYSTEM_CRITICAL", event.at,
                                 {**event.metadata, "original_event_type": event.event_type},
                                 event.event_id, event.source, event.correlation_id)
        return self.publish(event)

    def subscribe(self, event_type: str | None, handler: Callable[[RuntimeEvent], None]) -> str:
        """Register an isolated callback; ``None`` receives every event."""
        if not callable(handler):
            raise TypeError("EventBus subscriber must be callable")
        with self._lock:
            self._subscriber_sequence += 1
            token = f"subscriber:{self._subscriber_sequence}"
            self._subscribers[token] = (
                str(event_type) if event_type is not None else None, handler)
            return token

    def unsubscribe(self, token: str) -> bool:
        with self._lock:
            return self._subscribers.pop(str(token), None) is not None

    def get_recent_events(self, event_type: str | None = None, *, max_count: int = 50) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            values = [event for event in self._history
                      if event_type is None or event.event_type == event_type]
            return tuple(values[-max(0, int(max_count)):])

    def consume(self) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            events = tuple(event for _, event in sorted(
                self._events,
                key=lambda item: (self._PRIORITY.get(item[1].event_type, 2), item[0])))
            self._events.clear()
            if events:
                self._last_consumed_at = max(float(event.at) for event in events)
            return events

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {"queued": len(self._events), "queue_depth": len(self._events),
                    "max_events": self.max_events,
                    "history": len(self._history), "subscribers": len(self._subscribers),
                    "coalesced": self._coalesced, "dropped": self._dropped,
                    "critical_overflow": self._critical_overflow,
                    "last_published_at": self._last_published_at,
                    "last_consumed_at": self._last_consumed_at,
                    "subscriber_errors": list(self._subscriber_errors)}

    def _accept_event_id(self, event_id: str) -> bool:
        if event_id in self._seen_event_ids:
            return False
        self._seen_event_ids.add(event_id)
        self._seen_order.append(event_id)
        if len(self._seen_order) > self._MAX_SEEN_EVENT_IDS:
            self._seen_event_ids.discard(self._seen_order.popleft())
        return True

    def _coalesce(self, event: RuntimeEvent) -> None:
        key = (event.event_type, str(event.metadata.get("entity_id") or event.metadata.get("track_id") or ""))
        retained: deque[tuple[int, RuntimeEvent]] = deque()
        for queued in self._events:
            candidate = queued[1]
            candidate_key = (candidate.event_type,
                             str(candidate.metadata.get("entity_id") or candidate.metadata.get("track_id") or ""))
            if candidate_key == key:
                self._coalesced += 1
                continue
            retained.append(queued)
        self._events = retained

    def _make_space(self, incoming: RuntimeEvent) -> bool:
        decision = prioritize_critical_event(
            self._events, (self._sequence + 1, incoming),
            max_size=self.max_events,
            is_critical=lambda item: (
                item[1].event_type in self._CRITICAL
                or item[1].event_type == "SYSTEM_CRITICAL"),
        )
        self._dropped += decision.dropped
        self._critical_overflow += decision.critical_overflow
        return decision.accepted

    def _deliver(self, event: RuntimeEvent) -> None:
        for token, (filter_type, handler) in tuple(self._subscribers.items()):
            if filter_type is not None and filter_type != event.event_type:
                continue
            try:
                handler(event)
            except Exception as error:  # no subscriber may poison runtime delivery
                self._subscriber_errors.append({"subscriber": token,
                                                "event_type": event.event_type,
                                                "error": f"{type(error).__name__}: {error}"})
