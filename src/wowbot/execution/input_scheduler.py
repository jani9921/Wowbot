"""One bounded scheduler for persistent movement input leases.

This module intentionally has no planner, WorldModel, skill, binding-cache or
Windows API dependency.  It only serializes keys that have already passed the
authoritative executor's selected-PID, focus and binding validation.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable


class InputScheduler:
    """Serialize one held movement lease and release it on missed refreshes."""

    def __init__(self, backend, cancelled: threading.Event, *, watchdog_seconds: float = .45):
        self.backend = backend
        self.cancelled = cancelled
        self._lock = threading.RLock()
        self._held: set[str] = set()
        self._movement_deadline = 0.
        self._steering_deadline = 0.
        self._steering_keys: set[str] = set()
        self._movement_stops = 0
        self._last_movement_stop = 0.
        self._background_error: str | None = None
        self._shutdown = threading.Event()
        # Wake the worker immediately when a new/changed lease arrives.  A
        # fixed polling loop can start late under cold-test or high CPU load
        # and overrun a 20 ms steering lease even though the deadline itself
        # is correct.
        self._lease_changed = threading.Event()
        self.movement_watchdog_seconds = watchdog_seconds
        self._watchdog = threading.Thread(target=self._watchdog_loop,
                                          name="aipc-input-scheduler", daemon=True)
        self._watchdog.start()

    @property
    def background_error(self) -> str | None:
        return self._background_error

    def _release(self) -> None:
        errors = []
        for key in list(self._held):
            try:
                self.backend.key(key, False)
            except Exception as error:
                errors.append(str(error))
            else:
                self._held.discard(key)
        if errors:
            raise RuntimeError("Input release failed: " + "; ".join(errors))

    def stop_movement(self) -> None:
        """Idempotently release only the scheduler-owned movement lease."""
        with self._lock:
            keys = list(self._held)
            self._release()
            # A redundant key-up repairs a late/missed OS release and remains
            # idempotent. It never creates a reverse movement command.
            for key in keys:
                self.backend.key(key, False)
            self._movement_deadline = 0.
            self._steering_deadline = 0.
            self._steering_keys.clear()
            self._movement_stops += 1
            self._last_movement_stop = time.monotonic()
            self._lease_changed.set()

    def execute_movement(self, *, keys: tuple[str, ...], forward: set[str], steering: set[str],
                         steering_duration: float, check: Callable[[], None]) -> None:
        """Refresh one serialized forward/steering lease.

        ``check`` belongs to the selected-PID executor, preserving its focus,
        emergency-stop and binding authority immediately before input.
        """
        check()
        with self._lock:
            check()
            key_set = set(keys)
            is_key_down = getattr(self.backend, "is_key_down", None)
            stale = {key for key in key_set & self._held if is_key_down and not is_key_down(key)}
            for key in sorted((self._held-key_set) | stale):
                self.backend.key(key, False)
                self._held.discard(key)
            # Stable action order is observable at the backend and keeps a
            # forward+steering refresh deterministic for replay tests.
            for key in keys:
                if key in self._held:
                    continue
                self.backend.key(key, True)
                self._held.add(key)
            self._movement_deadline = time.monotonic()+self.movement_watchdog_seconds
            self._steering_keys = set(steering)
            self._steering_deadline = (time.monotonic()+steering_duration+.01
                                       if steering else 0.)
            self._lease_changed.set()

    def diagnostics(self) -> dict:
        with self._lock:
            held = sorted(self._held)
            deadline = self._movement_deadline
            stops = self._movement_stops
            last_stop = self._last_movement_stop
        return {
            "held_keys": held, "held_key_count": len(held),
            "movement_watchdog_seconds": self.movement_watchdog_seconds,
            "movement_lease_remaining": max(0., deadline-time.monotonic()),
            "movement_stops": stops, "movement_watchdog_alive": self._watchdog.is_alive(),
            "movement_watchdog_error": self._background_error,
            "last_movement_stop_age": (max(0., time.monotonic()-last_stop) if last_stop else None),
        }

    def _watchdog_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                now = time.monotonic()
                next_deadline = 0.
                with self._lock:
                    if self._steering_deadline and now >= self._steering_deadline:
                        for key in list(self._steering_keys & self._held):
                            self.backend.key(key, False)
                            self._held.discard(key)
                        self._steering_keys.clear()
                        self._steering_deadline = 0.
                    if self._movement_deadline and now >= self._movement_deadline:
                        self._release()
                        self._movement_deadline = 0.
                    deadlines = [value for value in (
                        self._steering_deadline, self._movement_deadline) if value > now]
                    next_deadline = min(deadlines) if deadlines else 0.
            except Exception as error:  # surfaced through executor._check()
                self._background_error = str(error)
                self.cancelled.set()
                next_deadline = 0.
            timeout = min(.02, max(.001, next_deadline-time.monotonic())) if next_deadline else .02
            self._lease_changed.wait(timeout)
            self._lease_changed.clear()

    def close(self) -> None:
        self.stop_movement()
        self._shutdown.set()
        self._lease_changed.set()
        self._watchdog.join(timeout=.5)
