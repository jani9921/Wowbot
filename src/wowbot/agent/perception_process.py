"""World3D perception in its own process.

Live 2026-09-30: every per-frame World3D step cost ~1 ms offline but 28-56 ms
inside the agent process, because V3, the visual track layers, the canonical
evidence pipeline and Live Vision publication all waited for the same GIL as
the agent tick.  Here the unchanged ``PerceptionWorker`` runs in a spawned
process that reads frames from the capture ring itself and consumes the
capture-driven YOLO feed directly::

    capture process ──ring──> World3D process (PerceptionWorker) ──latest──> agent
    YOLO feed process ──results──┘            └──> Live Vision monitor

The agent keeps the same interface through ``ProcessPerceptionWorker``
(latest-only mailboxes both ways: requests in, projections out).  The feed
worker and the Live Vision window stay owned by the agent process; this
process only holds client endpoints.  Time stamps are ``time.monotonic()``,
which is system-wide on Windows, so freshness checks stay valid across the
process boundary.
"""
from __future__ import annotations

import multiprocessing as mp
from queue import Empty, Full
import time
from typing import Any


def _put_latest(queue, item) -> None:
    try:
        queue.put_nowait(item)
    except Full:
        try:
            queue.get_nowait()
        except Empty:
            pass
        try:
            queue.put_nowait(item)
        except Full:
            pass


def _perception_process_main(config: dict[str, Any], requests, results, stopped,
                             feed_endpoint, live_endpoint) -> None:
    import os
    import sys
    sys.setswitchinterval(max(.0005, float(os.environ.get("AIPC_GIL_SWITCH_INTERVAL", ".0005"))))
    from pathlib import Path
    from wowbot.agent.perception import PerceptionWorker
    from wowbot.agent.shared_frame_buffer import SharedFrameRingBuffer

    ring = SharedFrameRingBuffer.attach(name_prefix=config["capture_ring"])
    recent: dict[int, tuple[bytes, int, int]] = {}
    recent_order: list[int] = []
    feed = None
    if feed_endpoint is not None:
        from wowbot.vision.world3d.capture_yolo_feed import CaptureDrivenYoloFeed
        feed = CaptureDrivenYoloFeed.from_endpoint(feed_endpoint, frame_lookup=recent.get)
    live = None
    if live_endpoint is not None:
        from wowbot.diagnostics.live_vision_monitor import LiveVisionPublisher
        live = LiveVisionPublisher(live_endpoint)
    hard_examples = config.get("hard_example_directory")
    worker = PerceptionWorker(
        hard_example_directory=Path(hard_examples) if hard_examples else None,
        learned_detector=feed, live_vision_monitor=live,
        world3d_proposal_mode=config.get("proposal_mode", "YOLO_ONLY"))
    current: dict[str, Any] = {"frame": None}
    worker.start_background(lambda: current["frame"], hz=120.)
    last_frame_id = 0
    last_revision = -1
    last_publish = last_diagnostics = 0.
    last_batch = None
    try:
        while not stopped.is_set():
            request = None
            while True:
                try:
                    request = requests.get_nowait()
                except Empty:
                    break
                except (EOFError, OSError):
                    return
            if request is not None:
                worker.submit_latest(**request)
            frame = ring.read() if ring.peek_frame_id() != last_frame_id else None
            if (frame is not None and frame.raw is not None and frame.frame_id > 0
                    and frame.frame_id != last_frame_id):
                last_frame_id = frame.frame_id
                data = (frame.raw, frame.width, frame.height)
                recent[frame.frame_id] = data
                recent_order.append(frame.frame_id)
                while len(recent_order) > 16:
                    recent.pop(recent_order.pop(0), None)
                current["frame"] = data
                worker.notify_new_frame()
            now = time.monotonic()
            if worker.projection_revision != last_revision or now-last_publish > .25:
                last_revision, last_publish = worker.projection_revision, now
                world = worker.lanes["world"]
                payload = {
                    "items": list(worker._background_result),
                    "projection_revision": worker.projection_revision,
                    "projection_at": worker.projection_at,
                    "epoch": worker.epoch,
                    "status": worker.status,
                    "world_status": world["status"],
                    "world_at": world["at"],
                    "rates": worker.rates(now),
                    "background_error": worker._background_error,
                }
                if now-last_diagnostics > .5:
                    last_diagnostics = now
                    payload["diagnostics"] = worker.diagnostics
                if worker.world3d_batch is not last_batch:
                    last_batch = worker.world3d_batch
                    payload["world3d_batch"] = last_batch
                _put_latest(results, payload)
            # High-resolution sleep (Python >= 3.11 on Windows): polls the
            # capture ring at ~500 Hz without coarse-timer quantization.
            time.sleep(.002)
    finally:
        worker.close()
        if live is not None:
            live.close()
        ring.close()


class ProcessPerceptionWorker:
    """Agent-side proxy with the PerceptionWorker interface the runtime uses."""

    RESULT_TTL_SECONDS = 3.0
    background_active = True

    def __init__(self, *, capture_ring: str, feed=None, live_vision_monitor=None,
                 hard_example_directory=None, proposal_mode: str = "YOLO_ONLY") -> None:
        self._feed = feed
        self._live_vision_monitor = live_vision_monitor
        context = mp.get_context("spawn")
        self._stopped = context.Event()
        self._requests = context.Queue(maxsize=1)
        self._results = context.Queue(maxsize=1)
        self.items: list[dict] = []
        self.diagnostics: dict = {}
        self.status = "starting_world3d_process"
        self.projection_revision = 0
        self.projection_at = 0.
        self.epoch = 0
        self.world3d_batch = None
        self._rates: dict = {}
        self._world_status = "idle"
        self._world_at = 0.
        self._background_error: str | None = None
        self._process = context.Process(
            target=_perception_process_main,
            args=({"capture_ring": capture_ring,
                   "hard_example_directory": (str(hard_example_directory)
                                              if hard_example_directory else None),
                   "proposal_mode": proposal_mode},
                  self._requests, self._results, self._stopped,
                  feed.endpoint() if feed is not None else None,
                  live_vision_monitor.endpoint() if live_vision_monitor is not None else None),
            name="aipc-world3d-perception", daemon=True)
        self._process.start()

    # The process owns its own capture reader and pump.
    def start_background(self, frame_provider, *, hz: float = 40.) -> None:
        return None

    def notify_new_frame(self) -> None:
        return None

    def _drain(self) -> None:
        newest = None
        while True:
            try:
                newest = self._results.get_nowait()
            except Empty:
                break
            except (EOFError, OSError):
                break
            if "diagnostics" in newest:
                self.diagnostics = newest["diagnostics"]
            if "world3d_batch" in newest:
                self.world3d_batch = newest["world3d_batch"]
        if newest is not None:
            self.items = newest["items"]
            self.projection_revision = newest["projection_revision"]
            self.projection_at = newest["projection_at"]
            self.epoch = newest["epoch"]
            self.status = newest["status"]
            self._rates = newest["rates"]
            self._world_status = newest["world_status"]
            self._world_at = newest["world_at"]
            self._background_error = newest.get("background_error")
        if not self._process.is_alive() and not self._stopped.is_set():
            self.status = f"world3d_process_exited:{self._process.exitcode}"

    def submit_latest(self, *, allow=True, geometry=None, context=None,
                      world_map_open=False) -> list[dict]:
        _put_latest(self._requests, {"allow": allow, "geometry": dict(geometry or {}),
                                     "context": context, "world_map_open": world_map_open})
        self._drain()
        return [dict(item) for item in self.items]

    def update(self, frame, now, *, allow=True, geometry=None, context=None,
               world_map_open=False) -> list[dict]:
        return self.submit_latest(allow=allow, geometry=geometry, context=context,
                                  world_map_open=world_map_open)

    def rates(self, now: float) -> dict:
        self._drain()
        return dict(self._rates)

    def detector_ready(self, now: float) -> bool:
        self._drain()
        if float(self._rates.get("world_detector_hz") or 0.) > 0:
            self._detector_seen = True
        return bool(getattr(self, "_detector_seen", False))

    def ready_for_action(self, now: float) -> bool:
        self._drain()
        return (self._world_status == "ready" and bool(self._world_at)
                and 0 <= now-self._world_at <= self.RESULT_TTL_SECONDS)

    def close(self) -> None:
        self._stopped.set()
        self._process.join(timeout=3.)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1.)
        for queue in (self._requests, self._results):
            queue.close()
        if self._feed is not None:
            self._feed.close()
        if self._live_vision_monitor is not None:
            self._live_vision_monitor.close()
