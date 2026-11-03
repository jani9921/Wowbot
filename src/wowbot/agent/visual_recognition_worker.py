"""Bounded advisory visual-memory reader, outside the input/control cadence.

No identity facts, input, planner or world writes live here. An epoch reset
discards pending and late results; a busy database never blocks lookup().
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import threading
import time


class VisualRecognitionWorker:
    def __init__(self, memory, *, max_pending=32, cache_seconds=1., clock=time.monotonic):
        self.memory, self.clock = memory, clock
        self.max_pending, self.cache_seconds = max_pending, cache_seconds
        self._condition = threading.Condition()
        self._pending = OrderedDict()
        self._cache = OrderedDict()
        self._in_flight = set()
        self._epoch = None
        self._stopped = False
        self.thread = None
        self.completed = self.dropped = 0
        self.error = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name="aipc-visual-memory", daemon=True)
        self.thread.start()

    def lookup(self, signature, *, track_id, epoch, now):
        identity = str(track_id or (signature.get("signature_id") if isinstance(signature, dict) else signature) or "")
        key = (epoch, identity)
        with self._condition:
            if epoch != self._epoch:
                self._epoch = epoch
                self._pending.clear()
                self._cache.clear()
            cached = self._cache.get(key)
            if cached is not None and 0 <= now-cached[0] <= self.cache_seconds:
                return list(cached[1])
            if key not in self._in_flight and not self._stopped:
                self._pending[key] = deepcopy(signature)
                if len(self._pending) > self.max_pending:
                    self._pending.popitem(last=False)
                    self.dropped += 1
                self._condition.notify()
            return []

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending or self._stopped)
                if self._stopped:
                    return
                key, signature = self._pending.popitem(last=False)
                self._in_flight.add(key)
            try:
                result = self.memory.recognize_visual(signature, as_of=time.time(), max_age=30*86400)
                error = None
            except Exception as exc:
                result, error = [], f"{type(exc).__name__}: {exc}"[:200]
            with self._condition:
                self._in_flight.discard(key)
                if key[0] == self._epoch and not self._stopped:
                    self._cache[key] = (self.clock(), result)
                    while len(self._cache) > 256:
                        self._cache.popitem(last=False)
                self.completed += 1
                self.error = error

    def snapshot(self):
        with self._condition:
            return {"pending": len(self._pending), "in_flight": len(self._in_flight),
                    "completed": self.completed, "dropped": self.dropped, "error": self.error}

    def close(self):
        with self._condition:
            self._stopped = True
            self._pending.clear()
            self._condition.notify_all()
        if self.thread:
            self.thread.join(timeout=2.)
