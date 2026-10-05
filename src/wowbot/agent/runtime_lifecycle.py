"""AgentRuntime start/run/close and the background status writer.

Split out of runtime.py (2026-10-05, module-size gate V4-083); the methods are
unchanged and still run on the one AgentRuntime instance.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import threading
import time
import traceback
from .models import Mode


class RuntimeLifecycleMixin:
    """Methods of AgentRuntime (runtime.py); moved verbatim."""

    def start(self):
        if self.started:
            raise RuntimeError("A runtime csak egyszer indítható")
        self.started = True
        if self.replay_bridge is not None:
            self.replay_bridge.start(agent=self.agent, metadata={
                "pid": self.pid,
                "bindings_cache": str(self.bindings.path),
                "bindings_sha256": self.bindings.digest,
                "mmap_configured": self.agent.navigation.snapshot(time.monotonic())["navmesh"]["configured"],
            })
        if hasattr(self.sensor, "start"):
            self.sensor.start()
        if self.perception is not None and hasattr(self.perception, "start_background"):
            # 60 Hz pump + 30 Hz cadence gate gives the tracker a real 30 Hz
            # opportunity. A 40 Hz pump quantized a 33 ms gate to every second
            # tick, capping measured throughput near 20 Hz even at <2 ms cost.
            self.perception.start_background(lambda: self.sensor.frame, hz=120.)
            add_listener = getattr(self.sensor, "add_frame_listener", None)
            if callable(add_listener):
                add_listener(self.perception.notify_new_frame)
        self._status_writer_thread = threading.Thread(
            target=self._status_writer_loop, name="aipc-status-writer", daemon=True)
        self._status_writer_thread.start()
        if os.environ.get("AIPC_THREAD_PROFILE", "1").strip() != "0":
            from wowbot.diagnostics.thread_profiler import ThreadProfiler
            ThreadProfiler(self.output / "thread_profile.json").start()
        # The perception pump, capture/feed polling and input threads mostly
        # wait on native work; with CPU-bound Python threads alive each GIL
        # re-acquisition could wait the default 5 ms switch interval.
        import sys
        sys.setswitchinterval(max(.0005, float(os.environ.get(
            "AIPC_GIL_SWITCH_INTERVAL", ".0005"))))
        self.thread = threading.Thread(target=self.run, name="aipc-agent", daemon=True)
        self.thread.start()

    def _save_quest_npcs(self):
        npcs = getattr(self.agent.world, "__dict__", {}).get("quest_relevant_npcs")
        if not npcs:
            return
        try:
            text = json.dumps(dict(npcs), sort_keys=True)
            if text != self._quest_npcs_saved:
                from adapters.atomic_file import write_json_replace
                write_json_replace(self._quest_npcs_path, json.loads(text))
                self._quest_npcs_saved = text
        except (OSError, TypeError, ValueError, RuntimeError):
            pass

    def _write_status_now(self, result):
        write_started = time.perf_counter()
        self._save_quest_npcs()
        try:
            from adapters.atomic_file import write_json_replace
            write_json_replace(self.output / "agent_status.json", result)
            self._status_write_error = None
        except Exception as error:
            self._status_write_error = f"{type(error).__name__}: {error}"
        finally:
            self._status_write_ms = (time.perf_counter()-write_started)*1000

    def _status_writer_loop(self):
        """Write only the newest diagnostic snapshot off the control thread."""
        while True:
            self._status_write_event.wait(.5)
            self._status_write_event.clear()
            with self._status_write_lock:
                pending, self._status_write_pending = self._status_write_pending, None
            if pending is not None:
                self._write_status_now(pending)
            with self._status_write_lock:
                empty = self._status_write_pending is None
            if self._status_write_stop.is_set() and empty:
                return

    def _publish_status(self, result):
        if self._status_writer_thread is None:
            # Direct step() calls in tests/tools remain deterministic.
            self._write_status_now(result)
            self._step_latencies.append(self._status_write_ms)
            return
        with self._status_write_lock:
            self._status_write_pending = result
        self._status_write_event.set()

    def run(self):
        try:
            control_interval = 1./self.control_hz
            while not self.stopped.is_set():
                at = time.monotonic()
                try:
                    self.step(at)
                except Exception as error:
                    self.mode("MANUAL")
                    # Live 2026-10-04 00:16 an INTERACT crash left only the
                    # message; keep the stack for offline diagnosis.
                    stack = traceback.format_exc()
                    self.status = {**(self.status or {}), "mode": "MANUAL",
                                   "runtime_error": f"{type(error).__name__}: {error}",
                                   "runtime_traceback": stack[-4000:]}
                    print(stack, flush=True)
                    try:
                        with (Path(self.output) / "runtime_errors.log").open("a", encoding="utf-8") as log:
                            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{stack}\n")
                    except OSError:
                        pass
                    self.stopped.wait(.5)
                self.stopped.wait(max(0., control_interval-(time.monotonic()-at)))
        finally:
            self.agent.set_mode(Mode.STOPPED)

    def close(self):
        self.arm_at = self.arm_deadline = self.test_deadline = None
        self.stopped.set()
        self.agent.set_mode(Mode.STOPPED)
        if hasattr(self.executor, "close"):
            self.executor.close()
        if self.thread:
            self.thread.join(timeout=2)
        self.agent.navigation.close()
        if self.replay_bridge is not None:
            self.replay_bridge.checkpoint({"mode": self.agent.mode.value})
            self.replay_bridge.close(metadata={"terminal_mode": "STOPPED"})
        self._status_write_stop.set()
        self._status_write_event.set()
        if self._status_writer_thread:
            self._status_writer_thread.join(timeout=2)
        # Persist the actual terminal safety state synchronously.  Otherwise
        # the last periodic snapshot can keep claiming FULL_AI (and even show
        # a formerly held movement key) after the process has already released
        # every key and stopped.
        final_status = {
            **self.status,
            "mode": "STOPPED",
            "arm_in": None,
            "arm_waiting_for_fresh_state": False,
            "test_remaining": None,
            "input_safety": (self.executor.diagnostics()
                             if hasattr(self.executor, "diagnostics") else {}),
            "stopped_at": time.time(),
        }
        self.status = final_status
        self._write_status_now(final_status)
        if self.memory:
            self.memory.close()
        if hasattr(self.spatial, "entities") and hasattr(self.spatial.entities, "close"):
            self.spatial.entities.close()
        if hasattr(self.spatial, "points") and hasattr(self.spatial.points, "close"):
            self.spatial.points.close()
        self.live_capture.close()
        if hasattr(self.sensor, "close"):
            self.sensor.close()
        if self._capture_process_handle is not None:
            self._capture_process_handle.stop()
        if self.perception:
            self.perception.close()
        self.reasoner.close()
        self.semantic.close()
