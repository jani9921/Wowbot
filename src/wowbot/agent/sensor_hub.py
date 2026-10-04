"""Unified sensor scheduling, freshness and health facade.

The existing ``BufferedPixelSensor`` remains the proven bounded producer.  The
hub is its sole live-runtime owner and provides the common SensorHub contract
without creating a second capture or perception loop.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Mapping


@dataclass(frozen=True)
class SensorHealth:
    name: str
    status: str
    rate_hz: float
    last_published_at: float | None
    age_seconds: float | None
    failure_reason: str | None
    fresh: bool


class SensorHub:
    """Own one or more bounded latest-value sensors under one lifecycle."""

    def __init__(self, sensors: Mapping[str, Any], *, primary: str = "telemetry",
                 freshness_seconds: float = .5, clock=time.monotonic) -> None:
        if primary not in sensors:
            raise ValueError("primary sensor must be registered")
        self._sensors = dict(sensors)
        self.primary = primary
        self.freshness_seconds = max(.01, float(freshness_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._latest: dict[str, tuple[Any, float]] = {}
        self._last_published_at: dict[str, float] = {}
        self._failures: dict[str, str] = {}
        self._started = False

    @classmethod
    def for_primary(cls, sensor: Any, **kwargs) -> "SensorHub":
        return cls({"telemetry": sensor}, primary="telemetry", **kwargs)

    @property
    def source(self) -> Any:
        """Compatibility projection used by capture diagnostics/tests."""
        return getattr(self._sensors[self.primary], "source", None)

    @property
    def interval(self) -> float | None:
        return getattr(self._sensors[self.primary], "interval", None)

    @property
    def frame(self) -> Any:
        return getattr(self._sensors[self.primary], "frame", None)

    def add_frame_listener(self, callback) -> bool:
        """Register a new-frame wake-up callback on the primary sensor."""
        listeners = getattr(self._sensors.get(self.primary), "frame_listeners", None)
        if isinstance(listeners, list):
            listeners.append(callback)
            return True
        return False

    @property
    def health(self) -> str:
        primary = self.sensor_health(self.primary)
        return primary.status

    @property
    def diagnostics(self) -> dict[str, Any]:
        return {
            "primary": self.primary,
            "sensors": {
                name: {
                    **health.__dict__,
                    "source": getattr(sensor, "diagnostics", {}),
                }
                for name, sensor in self._sensors.items()
                for health in (self.sensor_health(name),)
            },
            # Preserve the established top-level diagnostics shape for the
            # live monitor while exposing all named sensors above.
            **dict(getattr(self._sensors[self.primary], "diagnostics", {}) or {}),
        }

    def start(self) -> None:
        if self._started:
            raise RuntimeError("SensorHub already started")
        started: list[Any] = []
        try:
            for sensor in self._sensors.values():
                if hasattr(sensor, "start"):
                    sensor.start()
                started.append(sensor)
        except Exception:
            for sensor in reversed(started):
                if hasattr(sensor, "close"):
                    sensor.close()
            raise
        self._started = True

    def stop(self) -> None:
        for sensor in self._sensors.values():
            if hasattr(sensor, "close"):
                sensor.close()
        with self._lock:
            self._latest.clear()
            self._last_published_at.clear()
        self._started = False

    close = stop

    def poll_latest(self, sensor: str | None = None, *, now: float | None = None) -> Any:
        name = sensor or self.primary
        source = self._require(name)
        current = self._clock() if now is None else float(now)
        value = source.poll(current)
        if value is not None:
            self.publish_frame(name, value, published_at=current)
        with self._lock:
            latest = self._latest.get(name)
        if latest is None:
            return None
        payload, published_at = latest
        if current-published_at > self.freshness_seconds:
            with self._lock:
                self._latest.pop(name, None)
            return None
        # Latest-value mailbox semantics: return each value once. The
        # underlying BufferedPixelSensor separately preserves bounded edges.
        with self._lock:
            self._latest.pop(name, None)
        return payload

    def poll(self, now: float) -> Any:
        return self.poll_latest(now=now)

    def publish_frame(self, sensor: str, frame: Any, *, published_at: float | None = None) -> None:
        self._require(sensor)
        at = self._clock() if published_at is None else float(published_at)
        with self._lock:
            self._latest[sensor] = (frame, at)
            self._last_published_at[sensor] = at
            self._failures.pop(sensor, None)

    def set_rate(self, sensor: str, hz: float) -> None:
        source = self._require(sensor)
        if hz <= 0:
            raise ValueError("sensor rate must be positive")
        if not hasattr(source, "interval"):
            raise TypeError(f"sensor {sensor!r} does not expose a configurable interval")
        source.interval = 1.0 / float(hz)

    def mark_sensor_failure(self, sensor: str, reason: str) -> None:
        self._require(sensor)
        with self._lock:
            self._failures[sensor] = str(reason)
            self._latest.pop(sensor, None)

    def sensor_health(self, sensor: str | None = None) -> SensorHealth:
        name = sensor or self.primary
        source = self._require(name)
        now = self._clock()
        with self._lock:
            latest = self._latest.get(name)
            failure = self._failures.get(name)
            at = self._last_published_at.get(name)
        age = None if at is None else max(0.0, now-at)
        fresh = failure is None and (age is None or age <= self.freshness_seconds)
        diagnostics = getattr(source, "diagnostics", {}) or {}
        rate = diagnostics.get("update_hz", diagnostics.get("poll_hz", 0.0))
        status = f"sensor_error:{failure}" if failure else str(getattr(source, "health", "unknown"))
        return SensorHealth(name, status, float(rate or 0.0), at, age, failure, fresh)

    def _require(self, name: str) -> Any:
        try:
            return self._sensors[name]
        except KeyError as exc:
            raise KeyError(f"unknown sensor {name!r}") from exc
