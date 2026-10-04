"""Capture-driven YOLO feed: the detector pulls frames itself.

Before (live 2026-09-30): World3D handed a frame to the YOLO process only when
its own, slower cycle had consumed the previous result, so ~47 captured frames
per second yielded 10-13 detector refreshes.  Here the architecture is::

    capture process ──(shared ring, latest frame)──> YOLO feed process
          │                         YOLO → V2 features → BoT-SORT association
          │                                               │
          └──> tracker / agent / WorldModel <──(latest tracked result mailbox)

The feed process attaches to the capture ring as an additional reader, runs
the unchanged ``LearnedWorldDetector`` policy (learned ROI, hard UI masks,
foveal/full sampling, class gates and budgets) on the newest captured frame,
then the unchanged V2 feature/budget stage and the detector-rate association
tracker on *every* result.  Association therefore runs at detector rate even
when World3D takes only some results (live 2026-09-30: association at the
10-16 Hz World3D intake dropped identities during turns; the public layer saw
one subject arrive under dozens of upstream ids).  The World3D pipeline only
takes the newest finished result when it runs; it never submits, waits, or
paces the detector.  Results carry the capture frame id so the patch tracker
can anchor them on the exact frame YOLO saw, and a generation so a World3D
reset discards results of the previous context.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import multiprocessing as mp
from queue import Empty, Full
import time
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class FeedResult:
    sequence: int
    captured_at: float
    width: int
    height: int
    candidates: tuple
    diagnostics: dict
    inference_ms: float
    published_at: float
    processed_frames: int = 0
    generation: int = 0
    # True: ``candidates`` are V2-enriched and association-tracked (public
    # track ids assigned in the feed process); False: raw learned candidates.
    tracked: bool = False
    tracker_diagnostics: dict | None = None
    tracker_ms: float | None = None


class _SizedBackend:
    """predict_at_size() over a primary and optional alternate-size engine."""

    name = "ultralytics_yolo_capture_feed"

    def __init__(self, primary, alternate, alternate_image_size: int) -> None:
        self.primary, self.alternate = primary, alternate
        self.alternate_image_size = int(alternate_image_size)
        self.status = "ready"
        self.active_device = getattr(primary, "active_device", None)
        self.model_path = getattr(primary, "model_path", None)
        self.transport = "capture_ring_direct"
        self.last_image_size = getattr(primary, "image_size", None)
        self.load_error = None

    def predict(self, bgr, *, confidence: float, iou: float):
        return self.predict_at_size(bgr, confidence=confidence, iou=iou,
                                    image_size=getattr(self.primary, "image_size", 640))

    def predict_at_size(self, bgr, *, confidence: float, iou: float, image_size: int):
        selected = (self.alternate if self.alternate is not None
                    and int(image_size) == self.alternate_image_size else self.primary)
        self.last_image_size = getattr(selected, "image_size", image_size)
        return selected.predict(bgr, confidence=confidence, iou=iou)


def _publish_latest(results, result: FeedResult) -> None:
    """Latest-result mailbox: replace an unconsumed older result."""
    try:
        results.put_nowait(result)
    except Full:
        try:
            results.get_nowait()
        except Empty:
            pass
        try:
            results.put_nowait(result)
        except Full:
            pass


class _AssociationTrace:
    """Per-frame association record of the feed process (diagnostics only).

    One JSON line per processed frame: the V2 candidates entering the
    association tracker, the published ids, bridge/assignment counts and the
    camera-motion warp.  Enough to replay association offline on the exact
    live detection stream.  Rotates to ``.1`` so it stays bounded.
    """

    def __init__(self, path: str, *, max_lines: int = 60000) -> None:
        self.path = Path(path)
        self.max_lines = max(1000, int(max_lines))
        self.lines = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "w", encoding="utf-8")

    @staticmethod
    def _box(candidate) -> list:
        rect = candidate.rect
        return [candidate.kind, rect.left, rect.top, rect.right, rect.bottom,
                round(float(candidate.confidence), 3), candidate.track_id,
                list(candidate.candidate_labels)[:2]]

    def write(self, frame, generation: int, detected, tracked, tracker) -> None:
        import json
        diagnostics = getattr(tracker, "last_diagnostics", {}) or {}
        gmc = getattr(getattr(tracker, "_tracker", None), "gmc", None)
        record = {
            "f": frame.frame_id, "t": round(float(frame.captured_at), 4), "g": generation,
            "wh": [frame.width, frame.height],
            "det": [self._box(item) for item in detected],
            "out": [self._box(item) for item in tracked],
            "assoc": {key: diagnostics.get(key) for key in (
                "status", "native_assignments", "tentative_legacy_bridge",
                "active_tracks", "lost_tracks")},
            "warp": getattr(gmc, "last_warp", None),
            "gmc_response": getattr(gmc, "last_response", None),
            "gmc_scale": getattr(gmc, "last_scale", None),
            "gmc_hypothesis": getattr(gmc, "last_hypothesis", None),
            "gmc_support": getattr(gmc, "last_detection_support", None),
        }
        self.handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        self.lines += 1
        if self.lines % 30 == 0:
            self.handle.flush()
        if self.lines >= self.max_lines:
            self.handle.close()
            rotated = self.path.with_name(self.path.name + ".1")
            try:
                rotated.unlink(missing_ok=True)
                self.path.replace(rotated)
            except OSError:
                pass
            self.handle = open(self.path, "w", encoding="utf-8")
            self.lines = 0

    def close(self) -> None:
        try:
            self.handle.close()
        except OSError:
            pass


def _feed_worker_main(results, status_messages, stopped, generation,
                      config: dict[str, Any]) -> None:
    from wowbot.agent.shared_frame_buffer import SharedFrameRingBuffer
    from .learned_detector import LearnedWorldDetector
    from .process_yolo_backend import load_warm_backends
    from .scene import build_scene_roi
    from .v2 import World3DPerceptionV2
    from .v3 import build_detector_tracker

    pipeline = dict(config.get("pipeline") or {})
    try:
        primary, alternate = load_warm_backends(config)
        ring = SharedFrameRingBuffer.attach(name_prefix=config["capture_ring"])
    except Exception as exc:  # noqa: BLE001 -- surfaced to the parent as status
        status_messages.put(("error", None, f"{type(exc).__name__}:{exc}"))
        return
    detector = LearnedWorldDetector(
        _SizedBackend(primary, alternate, config["alternate_image_size"]),
        **config["detector_kwargs"])
    tracking = bool(pipeline.get("enabled", True))
    v2 = tracker = None
    if tracking:
        v2 = World3DPerceptionV2(
            learned_detector=detector,
            proposal_mode=str(pipeline.get("proposal_mode") or "YOLO_ONLY"))

        def new_tracker():
            built = build_detector_tracker(
                str(pipeline.get("tracker_mode") or "auto"),
                learned_tracking_enabled=True, warmup_in_background=False)
            ensure = getattr(built, "_ensure_tracker", None)
            if callable(ensure):
                ensure()  # import/build before advertising readiness
            return built

        tracker = new_tracker()
    trace = None
    if tracking and config.get("trace_path"):
        try:
            trace = _AssociationTrace(config["trace_path"])
        except OSError:
            trace = None
    status_messages.put(("ready", primary.active_device, None))
    minimum_interval = 1. / max(1., float(config.get("max_hz") or 60.))
    local_generation = int(generation.value)
    last_frame_id = 0
    last_started = 0.
    processed = 0
    try:
        while not stopped.is_set():
            now = time.monotonic()
            if now-last_started < minimum_interval:
                time.sleep(max(0., minimum_interval-(now-last_started)))
            if int(generation.value) != local_generation:
                local_generation = int(generation.value)
                if tracking:
                    v2.reset()
                    reset = getattr(tracker, "reset", None)
                    if callable(reset):
                        reset()
                    else:
                        tracker = new_tracker()
            frame = ring.read() if ring.peek_frame_id() != last_frame_id else None
            if (frame is None or frame.raw is None or frame.frame_id <= 0
                    or frame.frame_id == last_frame_id or frame.width <= 0 or frame.height <= 0):
                time.sleep(.002)
                continue
            last_started = time.monotonic()
            last_frame_id = frame.frame_id
            scene = build_scene_roi(frame.width, frame.height)
            tracker_ms = None
            tracker_diagnostics = None
            try:
                if tracking:
                    candidates = v2.process(frame.raw, frame.width, frame.height, scene)
                    detected = tuple(candidates)
                    diagnostics = dict(v2.last_diagnostics)
                    inference_ms = (time.monotonic()-last_started)*1000
                    tracker_started = time.monotonic()
                    candidates = tracker.update(
                        tuple(candidates), timestamp=frame.captured_at, raw=frame.raw,
                        width=frame.width, height=frame.height,
                        gray=v2.previous_gray, gray_step=v2.downsample)
                    tracker_ms = (time.monotonic()-tracker_started)*1000
                    tracker_diagnostics = dict(getattr(tracker, "last_diagnostics", {}) or {})
                    if trace is not None:
                        trace.write(frame, local_generation, detected, candidates, tracker)
                else:
                    candidates = detector.detect(frame.raw, frame.width, frame.height, scene)
                    diagnostics = dict(detector.last_diagnostics)
                    inference_ms = (time.monotonic()-last_started)*1000
            except Exception as exc:  # noqa: BLE001 -- keep the stream alive
                candidates, diagnostics = (), {"runtime_error": f"{type(exc).__name__}:{exc}"}
                inference_ms = (time.monotonic()-last_started)*1000
            processed += 1
            _publish_latest(results, FeedResult(
                frame.frame_id, frame.captured_at, frame.width, frame.height,
                tuple(candidates), diagnostics, inference_ms, time.monotonic(),
                processed, local_generation, tracking, tracker_diagnostics, tracker_ms))
    finally:
        ring.close()
        if trace is not None:
            trace.close()


class CaptureDrivenYoloFeed:
    """Main-process handle: newest finished result, never a frame submission."""

    capture_driven = True
    name = "ultralytics_yolo_capture_feed"

    def __init__(self, *, model_config: dict[str, Any], detector_kwargs: dict[str, Any],
                 capture_ring: str, frame_lookup: Callable[[int], tuple | None] | None = None,
                 max_hz: float = 60.) -> None:
        self.model_path = Path(model_config["model_path"])
        self.frame_lookup = frame_lookup
        self.status = "warming"
        self.load_error: str | None = None
        self.active_device: str | None = None
        self.transport = "capture_ring_direct"
        self.backend = self
        self.last_diagnostics: dict[str, object] = {"backend": self.name, "status": "warming"}
        self._closed = False
        self._published: deque[float] = deque(maxlen=120)
        self._processed: deque[tuple[float, int]] = deque(maxlen=120)
        self._consumed: deque[float] = deque(maxlen=120)
        self._latencies: deque[float] = deque(maxlen=120)
        self._tracker_ms: deque[float] = deque(maxlen=120)
        self._last_sequence = -1
        self.results_received = 0
        self.results_consumed = 0
        self.results_stale_generation = 0
        context = mp.get_context("spawn")
        self._context = context
        self._stopped = context.Event()
        self._generation = context.Value("i", 0)
        self._results = context.Queue(maxsize=1)
        self._status_messages = context.Queue(maxsize=4)
        self._config = {
            **model_config, "capture_ring": capture_ring,
            "detector_kwargs": dict(detector_kwargs), "max_hz": float(max_hz)}
        self._process = None

    def endpoint(self) -> dict[str, Any]:
        """Picklable-at-spawn handles for a client in another process.

        The World3D perception process consumes feed results directly; this
        process keeps owning (and closing) the feed worker.
        """
        return {"results": self._results, "status_messages": self._status_messages,
                "generation": self._generation, "config": dict(self._config),
                "model_path": str(self.model_path)}

    @classmethod
    def from_endpoint(cls, endpoint: dict[str, Any], *,
                      frame_lookup: Callable[[int], tuple | None] | None = None) -> "CaptureDrivenYoloFeed":
        """Client-only feed in another process: poll/reset, never start/stop."""
        feed = cls.__new__(cls)
        feed.model_path = Path(endpoint["model_path"])
        feed.frame_lookup = frame_lookup
        feed.status = "warming"
        feed.load_error = None
        feed.active_device = None
        feed.transport = "capture_ring_direct"
        feed.backend = feed
        feed.last_diagnostics = {"backend": cls.name, "status": "warming"}
        feed._closed = False
        feed._client_only = True
        feed._published = deque(maxlen=120)
        feed._processed = deque(maxlen=120)
        feed._consumed = deque(maxlen=120)
        feed._latencies = deque(maxlen=120)
        feed._tracker_ms = deque(maxlen=120)
        feed._last_sequence = -1
        feed.results_received = feed.results_consumed = feed.results_stale_generation = 0
        feed._context = None
        feed._stopped = None
        feed._generation = endpoint["generation"]
        feed._results = endpoint["results"]
        feed._status_messages = endpoint["status_messages"]
        feed._config = dict(endpoint["config"])
        feed._process = None
        return feed

    def set_trace_path(self, path: str | Path | None) -> None:
        """Record per-frame association to ``path`` (set before start)."""
        if self._process is None:
            self._config["trace_path"] = str(path) if path else None

    def start_pipeline(self, **pipeline: Any) -> None:
        """Spawn the feed process; the first call's pipeline settings win.

        World3D calls this with its proposal mode and tracker mode so the
        feed runs the same V2 stage and association tracker it would.
        """
        if self._process is not None or self._closed or getattr(self, "_client_only", False):
            return
        if not pipeline and isinstance(self._config.get("pipeline"), dict):
            pipeline = {key: value for key, value in self._config["pipeline"].items() if key != "enabled"}
        self._config["pipeline"] = {"enabled": True, **pipeline}
        self._process = self._context.Process(
            target=_feed_worker_main,
            args=(self._results, self._status_messages, self._stopped,
                  self._generation, self._config),
            name="aipc-yolo-capture-feed", daemon=True)
        self._process.start()

    @property
    def generation(self) -> int:
        return int(self._generation.value)

    def reset(self) -> None:
        """Start a new association generation (World3D context reset)."""
        with self._generation.get_lock():
            self._generation.value += 1

    def _poll_status(self) -> None:
        while True:
            try:
                status, device, error = self._status_messages.get_nowait()
            except Empty:
                break
            self.status, self.active_device, self.load_error = str(status), device, error
        if (not self._closed and self._process is not None
                and not self._process.is_alive() and self.status != "error"):
            self.status = "error"
            self.load_error = f"yolo_feed_process_exited:{self._process.exitcode}"
        # Live 2026-10-04 18:05: the feed process died at start-up and the
        # agent stayed blind (no candidates -> only WAIT) for the whole run;
        # the next start worked.  Restart a dead feed a few times, spaced out.
        restarts = getattr(self, "restarts", 0)
        if (self.status == "error" and not self._closed
                and not getattr(self, "_client_only", False)
                and self._process is not None and not self._process.is_alive()
                and restarts < 3
                and time.monotonic()-getattr(self, "last_restart_at", -1e9) >= 10.):
            self.restarts = restarts+1
            self.last_restart_at = time.monotonic()
            self.last_failure = self.load_error
            self._process = None
            self.status = "restarting"
            self.start_pipeline()

    def poll(self) -> FeedResult | None:
        """Newest result not returned before; never blocks."""
        if self._process is None and not getattr(self, "_client_only", False):
            self.start_pipeline()
        self._poll_status()
        newest = None
        while True:
            try:
                newest = self._results.get_nowait()
            except Empty:
                break
            except (EOFError, OSError):
                break
            self.results_received += 1
            self._published.append(newest.published_at)
            self._processed.append((newest.published_at, newest.processed_frames))
            if newest.tracker_ms is not None:
                self._tracker_ms.append(newest.tracker_ms)
        if newest is None or newest.sequence <= self._last_sequence:
            return None
        if newest.generation != self.generation:
            self.results_stale_generation += 1
            return None
        now = time.monotonic()
        self._last_sequence = newest.sequence
        self.results_consumed += 1
        self._consumed.append(now)
        self._latencies.append(max(0., now-newest.captured_at)*1000)
        self.last_diagnostics = {
            **newest.diagnostics, "backend": self.name, "status": self.status,
            "transport": self.transport, "feed": self.feed_diagnostics(now),
        }
        if self.active_device is not None:
            self.last_diagnostics["device"] = self.active_device
        return newest

    def frame_for_sequence(self, sequence: int):
        return self.frame_lookup(sequence) if self.frame_lookup is not None else None

    @staticmethod
    def _rate(stamps: deque, now: float, window: float = 3.) -> float:
        recent = [stamp for stamp in stamps if now-stamp <= window]
        if len(recent) < 2:
            return 0.
        return round((len(recent)-1)/max(1e-6, recent[-1]-recent[0]), 2)

    def feed_diagnostics(self, now: float | None = None) -> dict:
        now = time.monotonic() if now is None else now
        latencies = sorted(self._latencies)
        recent = [entry for entry in self._processed if now-entry[0] <= 3.]
        inference_hz = (round((recent[-1][1]-recent[0][1])/max(1e-6, recent[-1][0]-recent[0][0]), 2)
                        if len(recent) >= 2 else 0.)
        tracker_ms = sorted(self._tracker_ms)
        return {
            "mode": "CAPTURE_DRIVEN",
            "status": self.status,
            "error": self.load_error,
            "restarts": getattr(self, "restarts", 0),
            "last_failure": getattr(self, "last_failure", None),
            # Frames the YOLO process actually ran on (independent of how often
            # World3D takes a result); consumed_hz is the World3D intake.
            # Association runs on every processed frame in the feed process.
            "inference_hz": inference_hz,
            "association_in_feed": bool((self._config.get("pipeline") or {}).get("enabled")),
            "frames_processed": recent[-1][1] if recent else 0,
            "consumed_hz": self._rate(self._consumed, now),
            "results_received": self.results_received,
            "results_consumed": self.results_consumed,
            "results_stale_generation": self.results_stale_generation,
            "generation": self.generation,
            "tracker_ms_p50": (round(tracker_ms[len(tracker_ms)//2], 2) if tracker_ms else None),
            "capture_to_consume_ms_p50": (round(latencies[len(latencies)//2], 1) if latencies else None),
            "capture_to_consume_ms_p90": (round(latencies[int(len(latencies)*.9)], 1) if latencies else None),
        }

    def detect(self, raw, width, height, scene):  # pragma: no cover - contract guard
        raise RuntimeError("capture-driven feed is consumed through poll(), not detect()")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if getattr(self, "_client_only", False):
            return  # the owning process stops the feed worker
        self._stopped.set()
        if self._process is not None:
            self._process.join(timeout=3.)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=1.)
        for queue in (self._results, self._status_messages):
            queue.close()
