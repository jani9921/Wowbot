"""Read-only runtime health aggregation; never changes agent control state."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: str
    observation_age: float | None
    event_queue_depth: int
    active_skill: str | None
    reasons: tuple[str, ...]
    event_bus_age: float | None = None
    supervisor_age: float | None = None
    input_watchdog_alive: bool | None = None


class HealthMonitor:
    """Makes stalls visible without inventing a hidden recovery controller."""
    def __init__(self, *, stale_after_seconds: float = 5.) -> None:
        self.stale_after_seconds = stale_after_seconds
        self._latest: HealthReport | None = None

    def observe(self, *, now: float, last_received: float | None,
                event_bus: dict[str, Any], active_skill: str | None,
                last_supervisor_tick: float | None = None,
                input_safety: dict[str, Any] | None = None) -> HealthReport:
        age = None if last_received is None else max(0., now-last_received)
        depth = int(event_bus.get("queue_depth", event_bus.get("queued", 0)) or 0)
        consumed_at = event_bus.get("last_consumed_at")
        event_age = None if consumed_at is None else max(0., now-float(consumed_at))
        supervisor_age = (None if last_supervisor_tick is None
                          else max(0., now-float(last_supervisor_tick)))
        input_safety = input_safety or {}
        watchdog_alive = input_safety.get("movement_watchdog_alive")
        reasons = []
        if age is None or age > self.stale_after_seconds:
            reasons.append("observation_stale")
        if event_bus.get("critical_overflow"):
            reasons.append("critical_event_overflow")
        if event_bus.get("subscriber_failures") or event_bus.get("subscriber_errors"):
            reasons.append("subscriber_failure")
        # A quiet, empty EventBus is normal.  A nonempty queue that no longer
        # drains is the actionable stall signal.
        if depth and event_age is not None and event_age > self.stale_after_seconds:
            reasons.append("event_bus_stalled")
        if active_skill and supervisor_age is not None and supervisor_age > self.stale_after_seconds:
            reasons.append("supervisor_stalled")
        if watchdog_alive is False or input_safety.get("movement_watchdog_error"):
            reasons.append("input_watchdog_unhealthy")
        report = HealthReport("FAILED" if "critical_event_overflow" in reasons else
                              "DEGRADED" if reasons else "HEALTHY", age, depth,
                              active_skill, tuple(reasons), event_age,
                              supervisor_age, watchdog_alive)
        self._latest = report
        return report

    def snapshot(self) -> dict[str, Any]:
        return asdict(self._latest) if self._latest else {"status": "UNKNOWN"}
