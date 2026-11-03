"""Live fast pump, independent of observation/memory/planner work.

It only calls the agent's shared control adapter with non-consuming sensor
snapshots. The agent lock, existing FSMs and executor remain authoritative.
Offline direct step() callers retain deterministic, synchronous behavior.
"""
from __future__ import annotations

import threading
import time

from .models import Mode


class ParallelRuntimePump:
    def __init__(self, runtime, *, hz=60.):
        self.runtime = runtime
        self.interval = 1./hz
        self.stopped = threading.Event()
        self.wake_medium = threading.Event()
        self.thread = None
        self.error = None
        self.start_status = "not_started"

    @property
    def active(self):
        return self.thread is not None and self.thread.is_alive() and not self.stopped.is_set()

    def snapshot(self):
        status = self.start_status
        if self.stopped.is_set():
            status = "stopped"
        elif self.error:
            status = "error"
        elif self.thread is not None and not self.thread.is_alive():
            status = "thread_exited"
        return {"status": status, "active": self.active,
                "sensor": type(self.runtime.sensor).__name__,
                "error": self.error}

    def start(self):
        if self.thread is not None or self.stopped.is_set():
            raise RuntimeError("Parallel control pump can only be started once")
        sensor = self.runtime.sensor
        if (not callable(getattr(sensor, "peek_latest", None))
                or not getattr(sensor, "supports_peek_latest", True)):
            self.runtime.agent.parallel_control.enabled = False
            self.start_status = "sensor_without_peek_latest"
            return False
        self.runtime.agent.parallel_control.enabled = True
        self.thread = threading.Thread(target=self._run, name="aipc-fast-control", daemon=True)
        try:
            self.thread.start()
        except Exception as exc:
            self.runtime.agent.parallel_control.enabled = False
            self.start_status = "start_failed"
            self.error = f"{type(exc).__name__}: {exc}"[:300]
            raise
        self.start_status = "running"
        return True

    def step(self, now):
        runtime, agent = self.runtime, self.runtime.agent
        if agent.mode != Mode.FULL_AI:
            return
        cancelled = getattr(runtime.executor, "cancelled", None)
        if cancelled is not None and cancelled.is_set():
            self.wake_medium.set()           # only the canonical recovery may re-arm input
            return
        backend = getattr(runtime.executor, "backend", None)
        if backend and backend.emergency_pressed():
            runtime.executor.stop()          # release first, before any canonical lock
            agent.set_mode(Mode.MANUAL)
            self.wake_medium.set()
            return
        if backend and not backend.is_selected_foreground():
            agent.parallel_control.stop(now, "foreground_lost")
            self.wake_medium.set()
            return
        if any(deadline is not None and now >= deadline for deadline in (
                runtime.test_deadline, runtime.test_dialog_grace_deadline)):
            agent.parallel_control.stop(now, "bounded_test_deadline")
            self.wake_medium.set()
            return
        latest = runtime.sensor.peek_latest(now)
        if latest is None:
            agent.parallel_control.stop(now, "telemetry_gap")
            self.wake_medium.set()
            return
        payload, received_at = latest
        provider = getattr(getattr(runtime, "packet_telemetry", None), "session_provider", None)
        if provider is not None:
            payload = provider.session_alias(payload)   # the same session name as the medium tick
        peek = getattr(runtime.perception, "peek_control", None)
        vision = peek(now) if callable(peek) else None
        result = agent.parallel_control.tick(payload, received_at, vision, now)
        if result.get("force_medium") or result.get("terminal"):
            self.wake_medium.set()

    def _run(self):
        while not self.stopped.is_set():
            started = time.monotonic()
            try:
                self.step(started)
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"[:300]
                self.runtime.executor.stop()
                self.runtime.agent.set_mode(Mode.MANUAL)
                self.runtime.agent.last_result = {"outcome": "FAILURE", "reason": self.error,
                                                   "skill": "PARALLEL_CONTROL"}
                self.wake_medium.set()
            self.stopped.wait(max(.001, self.interval-(time.monotonic()-started)))

    def close(self):
        self.stopped.set()
        self.runtime.agent.parallel_control.enabled = False
        self.runtime.agent.parallel_control.stop(time.monotonic(), "runtime_closed")
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.)
