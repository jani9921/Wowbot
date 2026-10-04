"""Read-only bounded performance telemetry for the canonical runtime."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from functools import wraps
import math
import time
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class LatencySummary:
    count: int
    latest_ms: float | None
    average_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    max_ms: float | None


class PerformanceMonitor:
    """Bounded measurements only; this class has no control or input methods."""

    def __init__(self, *, window: int = 256) -> None:
        self._window = max(8, int(window))
        self._samples: dict[str, deque[float]] = {}
        self._rates: dict[str, deque[float]] = {}
        self._captures: deque[float] = deque(maxlen=self._window)
        self._queue_depth: deque[int] = deque(maxlen=self._window)

    def observe_latency(self, name: str, duration_ms: float) -> None:
        try:
            value = float(duration_ms)
        except (TypeError, ValueError):
            return
        if not math.isfinite(value) or value < 0.:
            return
        self._samples.setdefault(str(name), deque(maxlen=self._window)).append(value)

    def observe_capture(self, at: float) -> None:
        try:
            value = float(at)
        except (TypeError, ValueError):
            return
        if math.isfinite(value):
            self._captures.append(value)

    def observe_rate(self, name: str, value: float | int | None) -> None:
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0.:
            return
        self._rates.setdefault(str(name), deque(maxlen=self._window)).append(float(value))

    def observe_event_queue_depth(self, depth: int | float | None) -> None:
        if isinstance(depth, (int, float)) and math.isfinite(float(depth)):
            self._queue_depth.append(max(0, int(depth)))

    def summary(self, name: str) -> LatencySummary:
        values = list(self._samples.get(str(name), ()))
        if not values:
            return LatencySummary(0, None, None, None, None, None, None)
        ordered = sorted(values)
        return LatencySummary(
            len(values), round(values[-1], 4), round(sum(values) / len(values), 4),
            round(self._percentile(ordered, .50), 4), round(self._percentile(ordered, .95), 4),
            round(self._percentile(ordered, .99), 4), round(ordered[-1], 4),
        )

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        capture_fps = None
        if len(self._captures) >= 2:
            span = self._captures[-1] - self._captures[0]
            if span > 0.:
                capture_fps = round((len(self._captures) - 1) / span, 3)
        measured_capture = self._rates.get("capture_fps")
        if measured_capture:
            capture_fps = round(measured_capture[-1], 3)
        return {
            "capture_fps": capture_fps,
            "event_queue_depth_latest": self._queue_depth[-1] if self._queue_depth else None,
            "event_queue_depth_max": max(self._queue_depth) if self._queue_depth else None,
            "latencies": {name: asdict(self.summary(name)) for name in sorted(self._samples)},
            "rates": {name: {"latest": round(values[-1], 3),
                              "average": round(sum(values) / len(values), 3)}
                      for name, values in sorted(self._rates.items()) if values},
            "source": "RUNTIME_PERFORMANCE_MONITOR",
            "fact": False,
        }

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        index = (len(values) - 1) * percentile
        lower, upper = int(index), math.ceil(index)
        if lower == upper:
            return values[lower]
        return values[lower] + (values[upper] - values[lower]) * (index - lower)


def measure_runtime_tick(method: Callable) -> Callable:
    """Instrument a runtime tick without changing its result or control flow."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return method(self, *args, **kwargs)
        finally:
            monitor = getattr(self, "performance_monitor", None)
            if monitor is not None:
                monitor.observe_latency("supervisor_tick", (time.perf_counter() - started) * 1000.)
                events = getattr(self, "events", None)
                if events is not None:
                    monitor.observe_event_queue_depth(events.diagnostics().get("queue_depth"))
    return wrapped


def measure_input_dispatch(method: Callable) -> Callable:
    """Measure the designated executor boundary without changing exceptions."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return method(self, *args, **kwargs)
        finally:
            monitor = getattr(self, "performance_monitor", None)
            if monitor is not None:
                monitor.observe_latency("input_dispatch", (time.perf_counter() - started) * 1000.)
    return wrapped
