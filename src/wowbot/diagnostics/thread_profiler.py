"""Low-overhead in-process thread profiler for live stall diagnosis.

Every ``interval`` seconds a daemon thread samples ``sys._current_frames()``
and, on Windows, each thread's kernel+user CPU time (``GetThreadTimes``).
Every ``report_seconds`` it atomically writes ``thread_profile.json`` with the
CPU share per named thread and the hottest sampled stack locations.  It reads
only this Python process; it sends no input and changes no agent state.
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

_IDLE_FUNCTIONS = frozenset({"wait", "sleep", "select", "_wait_for_tstate_lock", "get", "recv",
                             "recv_bytes", "_recv_bytes", "poll", "accept", "readline", "_poll"})


def _thread_cpu_seconds(native_id: int) -> float | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenThread(0x0800, False, native_id)  # THREAD_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel32.GetThreadTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        total = 0
        for filetime in times[2:]:  # kernel, user
            total += (filetime.dwHighDateTime << 32) | filetime.dwLowDateTime
        return total / 1e7
    finally:
        kernel32.CloseHandle(handle)


def _location(frame) -> str:
    return f"{Path(frame.f_code.co_filename).name}:{frame.f_code.co_name}:{frame.f_lineno}"


class ThreadProfiler:
    def __init__(self, output: Path, *, interval: float = .05, report_seconds: float = 5.,
                 stack_depth: int = 6) -> None:
        self.output = Path(output)
        self.interval = interval
        self.report_seconds = report_seconds
        self.stack_depth = stack_depth
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="aipc-thread-profiler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        own = threading.get_ident()
        window_started = time.perf_counter()
        cpu_start = self._cpu_by_thread()
        hot: dict[str, Counter] = {}
        samples = 0
        max_gap = 0.
        last = time.perf_counter()
        while not self._stop.wait(self.interval):
            now = time.perf_counter()
            max_gap = max(max_gap, now-last)  # how late this sampler itself woke up
            last = now
            samples += 1
            names = {thread.ident: thread.name for thread in threading.enumerate()}
            for ident, frame in sys._current_frames().items():
                if ident == own:
                    continue
                if frame.f_code.co_name in _IDLE_FUNCTIONS:
                    continue
                stack = [_location(item) for item, _ in traceback.walk_stack(frame)][:self.stack_depth]
                hot.setdefault(names.get(ident, str(ident)), Counter())[" <- ".join(stack)] += 1
            if now-window_started >= self.report_seconds:
                cpu_end = self._cpu_by_thread()
                elapsed = now-window_started
                self._write(elapsed, cpu_start, cpu_end, hot, samples, max_gap)
                window_started, cpu_start, hot, samples, max_gap = now, cpu_end, {}, 0, 0.

    @staticmethod
    def _cpu_by_thread() -> dict[str, float]:
        result = {}
        for thread in threading.enumerate():
            native = getattr(thread, "native_id", None)
            seconds = _thread_cpu_seconds(native) if native else None
            if seconds is not None:
                result[f"{thread.name}#{native}"] = seconds
        return result

    def _write(self, elapsed, cpu_start, cpu_end, hot, samples, max_gap) -> None:
        cpu = sorted(((round((cpu_end[key]-cpu_start.get(key, cpu_end[key]))/elapsed*100, 1), key)
                      for key in cpu_end), reverse=True)
        report = {
            "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "window_seconds": round(elapsed, 2),
            "sampler_samples": samples,
            "sampler_max_wakeup_gap_ms": round(max_gap*1000, 1),
            "thread_cpu_percent_of_one_core": [{"thread": key, "cpu_percent": value} for value, key in cpu],
            "hot_stacks": {name: [{"samples": count, "stack": stack}
                                  for stack, count in counter.most_common(5)]
                           for name, counter in sorted(hot.items(), key=lambda item: -sum(item[1].values()))},
        }
        try:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.output.with_suffix(".tmp")
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            temporary.replace(self.output)
            history = self.output.with_name("thread_profile_history.jsonl")
            with history.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(report, ensure_ascii=False) + "\n")
        except OSError:
            pass
