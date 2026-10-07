"""Rate-limited reporting for deliberately non-blocking error paths (#31).

Some runtime side tasks (entrance learning, ability-effect persistence,
navigation overlay, frame listeners) must never stop the control loop, but
swallowing their exceptions silently hid data loss.  Each failure is
counted per (component, exception type); the first occurrence and then at
most one summary per interval go to ``runtime_errors.log`` and the logger.
"""
from __future__ import annotations

import logging
from pathlib import Path
import threading
import time

_logger = logging.getLogger(__name__)


class SuppressedErrors:
    def __init__(self, log_path: str | Path | None = None, *, interval_seconds: float = 60.,
                 clock=time.monotonic) -> None:
        self.log_path = Path(log_path) if log_path is not None else None
        self.interval_seconds = float(interval_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self.counts: dict[tuple[str, str], int] = {}
        self._first: dict[tuple[str, str], str] = {}
        self._reported_at: dict[tuple[str, str], float] = {}

    def report(self, component: str, error: BaseException) -> None:
        key = (str(component), type(error).__name__)
        now = self._clock()
        with self._lock:
            count = self.counts.get(key, 0) + 1
            self.counts[key] = count
            self._first.setdefault(key, f"{type(error).__name__}: {error}")
            last = self._reported_at.get(key)
            if last is not None and now - last < self.interval_seconds:
                return
            self._reported_at[key] = now
        line = (f"suppressed error in {key[0]}: {key[1]} x{count} "
                f"(first: {self._first[key]}; latest: {error})")
        _logger.warning(line)
        if self.log_path is not None:
            try:
                with self.log_path.open("a", encoding="utf-8") as log:
                    log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
            except OSError:
                pass

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {f"{component}:{kind}": count
                    for (component, kind), count in self.counts.items()}
