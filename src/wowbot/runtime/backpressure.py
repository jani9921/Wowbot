"""Shared bounded-queue/backpressure primitives; no domain or input logic."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, TypeVar


T = TypeVar("T")


def coalesce_latest(current: T | None, incoming: T) -> tuple[T, bool]:
    """Keep the newest state sample and report whether one was superseded."""
    return incoming, current is not None


def drop_stale(values: Iterable[T], *, now: float, max_age: float,
               timestamp: Callable[[T], float]) -> tuple[tuple[T, ...], int]:
    """Remove entries older than ``max_age`` without reordering survivors."""
    original = tuple(values)
    kept = tuple(value for value in original
                 if 0 <= now-float(timestamp(value)) <= max_age)
    return kept, max(0, len(original)-len(kept))


def bound_queue(queue, item: T, *, max_size: int) -> int:
    """Append one item and evict oldest entries until the hard bound holds."""
    dropped = 0
    while len(queue) >= max(1, int(max_size)):
        queue.popleft()
        dropped += 1
    queue.append(item)
    return dropped


@dataclass(frozen=True, slots=True)
class PriorityAdmission:
    accepted: bool
    dropped: int = 0
    critical_overflow: int = 0


def prioritize_critical_event(queue, incoming: T, *, max_size: int,
                              is_critical: Callable[[T], bool]) -> PriorityAdmission:
    """Make room for an event while never silently losing critical state."""
    if len(queue) < max(1, int(max_size)):
        return PriorityAdmission(True)
    for index, queued in enumerate(queue):
        if not is_critical(queued):
            del queue[index]
            return PriorityAdmission(True, dropped=1)
    if is_critical(incoming):
        return PriorityAdmission(True, critical_overflow=1)
    return PriorityAdmission(False, dropped=1)
