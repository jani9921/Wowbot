"""Live, input-free view of the exact World3D frame and tracks used by AIPC."""
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import multiprocessing as mp
import os
from queue import Empty, Full
import time
from typing import Any
import uuid

import cv2
import numpy as np

from wowbot.agent.shared_frame_buffer import SharedFrameRingBuffer


def _configure_monitor_process() -> dict[str, Any]:
    """Keep the diagnostic renderer below perception/control priority.

    A freshly spawned OpenCV process used all 12 logical CPUs and enabled
    OpenCL by default on the live Windows host.  Merely opening LIVE VISION
    then pre-empted the 1--2 ms patch tracker for 100--600 ms.  The viewer is
    latest-frame diagnostics only; one native OpenCV worker is sufficient and
    it must never compete with the agent for accelerator scheduling.
    """
    requested_threads = max(1, min(2, int(os.environ.get(
        "AIPC_LIVE_VISION_OPENCV_THREADS", "1"))))
    try:
        cv2.setNumThreads(requested_threads)
    except Exception:
        pass
    try:
        cv2.ocl.setUseOpenCL(False)
    except Exception:
        pass
    priority = "unchanged"
    try:
        if os.name == "nt":
            import ctypes
            # BELOW_NORMAL_PRIORITY_CLASS. Failure is harmless: thread/OpenCL
            # limits still prevent the original resource storm.
            if ctypes.windll.kernel32.SetPriorityClass(
                    ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000):
                priority = "below_normal"
        else:  # pragma: no cover - Windows is the production client
            os.nice(5)
            priority = "nice+5"
    except (AttributeError, OSError, ValueError):
        pass
    return {
        "opencv_threads": int(cv2.getNumThreads()),
        "opencl": bool(cv2.ocl.useOpenCL()),
        "priority": priority,
    }


@dataclass(frozen=True, slots=True)
class _MonitorFrame:
    raw: bytes
    width: int
    height: int
    overlay: dict[str, Any]
    diagnostics: dict[str, Any]
    frame_id: str
    latency_ms: float
    published_at: float


@dataclass(frozen=True, slots=True)
class _MonitorMetadata:
    frame_sequence: int
    overlay: dict[str, Any]
    diagnostics: dict[str, Any]
    frame_id: str
    latency_ms: float
    published_at: float


class LiveVisionMonitor:
    """Single-slot live renderer; it never captures or runs inference itself.

    Perception publishes the completed source frame plus canonical tracked
    output. Slow UI painting can only replace an older pending display frame;
    it cannot back-pressure capture, inference, planning, or input execution.
    """

    WINDOW_TITLE = "AIPC LIVE VISION - agent perception (Q/Esc closes monitor)"
    CLASS_COLORS = {
        "humanoid_unit_like": (70, 220, 70),
        "creature_unit_like": (30, 160, 255),
        "corpse_like": (180, 80, 220),
        "quest_object_outline_like": (255, 220, 20),
        "world_object_like": (255, 140, 40),
        "overhead_symbol_like": (0, 255, 255),
        "entrance_or_door_like": (255, 100, 180),
    }

    def __init__(self, *, maximum_hz: float = 60.0) -> None:
        self.maximum_hz = max(1.0, min(120.0, float(maximum_hz)))
        self._closed = False
        # HighGUI and Tkinter cannot reliably own windows in different threads
        # of the same Windows process. Keep rendering in a spawned process and
        # make its mailbox latest-only so display can never stall the agent.
        context = mp.get_context("spawn")
        self._stopped = context.Event()
        self._queue = context.Queue(maxsize=1)
        # Latest-only route packets from the agent (design doc §11); their own
        # mailbox, so they never displace a frame.
        self._navigation = context.Queue(maxsize=1)
        max_width = max(640, int(os.environ.get("AIPC_LIVE_VISION_MAX_WIDTH", "3840")))
        max_height = max(480, int(os.environ.get("AIPC_LIVE_VISION_MAX_HEIGHT", "2160")))
        prefix = f"aipc_vision_{os.getpid()}_{uuid.uuid4().hex[:10]}"
        self._frames = SharedFrameRingBuffer.create(
            name_prefix=prefix, max_width=max_width, max_height=max_height)
        self._process = context.Process(
            target=_monitor_process_main,
            args=(self._queue, self._stopped, self.maximum_hz, self.WINDOW_TITLE,
                  self._frames.name_prefix, self._navigation),
            name="aipc-live-vision-monitor",
            daemon=True,
        )
        self._process.start()

    def endpoint(self) -> dict[str, Any]:
        """Picklable-at-spawn handles for a publisher in another process."""
        return {"queue": self._queue, "stopped": self._stopped,
                "frames": self._frames.name_prefix}

    def publish_navigation(self, navigation: dict[str, Any] | None) -> None:
        """Replace the route view drawn on the following frames."""
        if self._closed or not self._process.is_alive() or navigation is None:
            return
        item = {**navigation, "published_at": time.monotonic()}
        try:
            self._navigation.put_nowait(item)
        except Full:
            try:
                self._navigation.get_nowait()
            except Empty:
                pass
            try:
                self._navigation.put_nowait(item)
            except Full:
                pass

    def publish(self, frame: tuple[bytes, int, int], overlay: dict[str, Any], *,
                diagnostics: dict[str, Any] | None = None, frame_id: str = "",
                processing_latency_ms: float = 0.0) -> None:
        if self._closed or not self._process.is_alive():
            return
        _publish_monitor_frame(self._frames, self._queue, self._stopped, frame, overlay,
                               diagnostics=diagnostics, frame_id=frame_id,
                               processing_latency_ms=processing_latency_ms)
    @staticmethod
    def _bbox(track: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int] | None:
        bbox = track.get("bbox") or {}
        try:
            left, top, right, bottom = (float(bbox[key]) for key in
                                        ("left", "top", "right", "bottom"))
        except (KeyError, TypeError, ValueError):
            return None
        # Canonical tracks normally retain client pixels. Accept normalized
        # boxes as well so the monitor remains useful for future adapters.
        if max(abs(left), abs(top), abs(right), abs(bottom)) <= 1.01:
            left, right = left * width, right * width
            top, bottom = top * height, bottom * height
        result = (max(0, min(width - 1, round(left))),
                  max(0, min(height - 1, round(top))),
                  max(0, min(width - 1, round(right))),
                  max(0, min(height - 1, round(bottom))))
        return result if result[2] > result[0] and result[3] > result[1] else None

    @staticmethod
    def _track_label(track: dict[str, Any]) -> str:
        appearance = track.get("appearance") or {}
        learned_label = str(appearance.get("learned_label_hypothesis") or "UNKNOWN")
        confidence = float(track.get("confidence") or 0.0)
        lifecycle = str(track.get("lifecycle") or "UNKNOWN")
        display_name = str(track.get("display_name") or "").strip()
        track_id = str(track.get("track_id") or "").strip()
        identity = f"{track_id} " if track_id else ""
        subject = f"{display_name} [SELF]" if display_name else learned_label
        return f"{identity}{subject} {confidence:.2f} {lifecycle}"

    @classmethod
    def render_frame(cls, item: _MonitorFrame, *, display_hz: float = 0.0,
                     source_hz: float = 0.0,
                     timing: str = "",
                     max_width: int | None = None,
                     max_height: int | None = None,
                     navigation: dict[str, Any] | None = None) -> np.ndarray:
        pixels = np.frombuffer(item.raw, dtype=np.uint8).reshape(
            item.height, item.width, 4)
        scale = 1.0
        if max_width and max_height:
            scale = min(1.0, max_width / item.width, max_height / item.height)
        if scale < .999:
            display_width = max(1, round(item.width * scale))
            display_height = max(1, round(item.height * scale))
            # Resize all four channels in one native operation, then discard
            # alpha. This avoids constructing a full-resolution BGR copy just
            # to let HighGUI immediately scale it down again.
            resized = cv2.resize(
                pixels, (display_width, display_height),
                # Linear is visually sufficient for a diagnostic preview and
                # measured ~3x faster than INTER_AREA for 4K -> 1600x900.
                interpolation=cv2.INTER_LINEAR)
            canvas = cv2.cvtColor(resized, cv2.COLOR_BGRA2BGR)
        else:
            display_width, display_height = item.width, item.height
            canvas = cv2.cvtColor(pixels, cv2.COLOR_BGRA2BGR)
        tracks = item.overlay.get("tracks") or ()
        for track in tracks:
            rect = cls._bbox(track, item.width, item.height)
            if rect is None:
                continue
            if scale < .999:
                rect = tuple(round(value * scale) for value in rect)
            appearance = track.get("appearance") or {}
            learned_label = str(appearance.get("learned_label_hypothesis") or "UNKNOWN")
            color = ((255, 190, 40) if track.get("self_player_avatar")
                     else cls.CLASS_COLORS.get(learned_label, (220, 220, 220)))
            cv2.rectangle(canvas, rect[:2], rect[2:], color, 2, cv2.LINE_8)
            label = cls._track_label(track)
            (text_width, text_height), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, .48, 1)
            label_top = max(0, rect[1] - text_height - baseline - 5)
            cv2.rectangle(canvas, (rect[0], label_top),
                          (min(display_width - 1, rect[0] + text_width + 5), rect[1]),
                          (15, 15, 15), -1)
            cv2.putText(canvas, label, (rect[0] + 2, max(text_height, rect[1] - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, .48, color, 1, cv2.LINE_8)

        detector = item.diagnostics.get("detector") or {}
        learned = detector.get("learned_detector") or detector.get("learned") or {}
        device = learned.get("device") or detector.get("device") or "loading/unknown"
        header = (f"AIPC LIVE | tracks {len(tracks)} | view {display_hz:.1f} Hz | "
                  f"source {source_hz:.1f} Hz | "
                  f"vision {item.latency_ms:.0f} ms | device {device} | {item.frame_id}"
                  + (f" | {timing}" if timing else ""))
        if navigation:
            from .navigation_overlay import draw_navigation
            draw_navigation(canvas, navigation)
        cv2.rectangle(canvas, (0, 0), (display_width, 31), (10, 10, 10), -1)
        cv2.putText(canvas, header, (9, 21), cv2.FONT_HERSHEY_SIMPLEX,
                    .55, (245, 245, 245), 1, cv2.LINE_8)
        return canvas

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stopped.set()
        try:
            self._queue.put_nowait(None)
        except Full:
            pass
        self._process.join(timeout=2.0)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1.0)
        self._queue.close()
        self._frames.close()
        self._frames.unlink()


def _publish_monitor_frame(frames, queue, stopped, frame, overlay, *, diagnostics=None,
                           frame_id: str = "", processing_latency_ms: float = 0.) -> None:
    """Latest-only publication shared by the owning monitor and a publisher
    in the World3D perception process."""
    raw, width, height = frame
    if stopped.is_set() or width < 1 or height < 1 or len(raw) != width * height * 4:
        return
    compact_overlay = {
        "tracks": [dict(item) for item in overlay.get("tracks") or ()],
        "obstacles": [dict(item) for item in overlay.get("obstacles") or ()],
        "entrances": [dict(item) for item in overlay.get("entrances") or ()],
        "traversability": [dict(item) for item in overlay.get("traversability") or ()],
    }
    try:
        frame_sequence = frames.write_frame(raw, width, height, "ready", time.monotonic())
    except ValueError:
        return
    item = _MonitorMetadata(frame_sequence, compact_overlay, dict(diagnostics or {}),
                            str(frame_id), float(processing_latency_ms), time.monotonic())
    try:
        queue.put_nowait(item)
    except Full:
        try:
            queue.get_nowait()
        except Empty:
            return
        try:
            queue.put_nowait(item)
        except Full:
            return


class LiveVisionPublisher:
    """Publishes to a LiveVisionMonitor owned by another process."""

    def __init__(self, endpoint: dict[str, Any]) -> None:
        self._queue = endpoint["queue"]
        self._stopped = endpoint["stopped"]
        self._frames = SharedFrameRingBuffer.attach(name_prefix=endpoint["frames"])
        self._closed = False

    def publish(self, frame, overlay, *, diagnostics=None, frame_id: str = "",
                processing_latency_ms: float = 0.) -> None:
        if self._closed:
            return
        _publish_monitor_frame(self._frames, self._queue, self._stopped, frame, overlay,
                               diagnostics=diagnostics, frame_id=frame_id,
                               processing_latency_ms=processing_latency_ms)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._frames.close()


def _monitor_process_main(queue, stopped, maximum_hz: float, window_title: str,
                          frame_prefix: str, navigation_queue=None) -> None:
    """Own the HighGUI message loop outside the Tk/agent process."""
    _configure_monitor_process()
    next_display = 0.0
    display_times: deque[float] = deque(maxlen=120)
    source_times: deque[float] = deque(maxlen=120)
    latest: _MonitorFrame | None = None
    navigation: dict[str, Any] | None = None
    dirty = False
    # Where a displayed frame's time goes (EMA, ms): our drawing vs HighGUI
    # imshow + event pump.  The process runs BELOW_NORMAL on purpose, so a
    # loaded host shows up here rather than as perception stalls.
    draw_ms = show_ms = 0.0
    window_created = False
    preview_width = max(640, int(os.environ.get(
        "AIPC_LIVE_VISION_PREVIEW_WIDTH", "1600")))
    preview_height = max(480, int(os.environ.get(
        "AIPC_LIVE_VISION_PREVIEW_HEIGHT", "900")))
    frames = SharedFrameRingBuffer.attach(name_prefix=frame_prefix)
    try:
        # Event-driven (live 2026-10-01: view 33 Hz vs source 50-60 Hz).  The
        # old loop woke on a 5 ms queue poll, a sleep and two blocking
        # waitKeyEx(1) per displayed frame; at BELOW_NORMAL priority on a
        # loaded host every wake-up can cost a scheduler quantum.  Now the
        # only blocking wait is for the next frame, and HighGUI events are
        # pumped without waiting (bench under full CPU load: 30 -> 40 Hz,
        # view == source).
        poll_key = getattr(cv2, "pollKey", None) or (lambda: cv2.waitKeyEx(1))
        while not stopped.is_set():
            received = False
            now = time.monotonic()
            wait = (max(.001, next_display - now) if dirty and latest is not None
                    and now < next_display else .05)
            try:
                item = queue.get(timeout=wait)
                received = True
            except Empty:
                item = None
            if received and item is None:
                break
            while navigation_queue is not None:
                try:
                    navigation = navigation_queue.get_nowait()
                except Empty:
                    break
            if (navigation is not None
                    and time.monotonic() - float(navigation.get("published_at") or 0.) > 2.):
                navigation = None      # stale: the agent stopped routing
            if received:
                # Collapse any queued replacements to the newest available frame.
                while True:
                    try:
                        newer = queue.get_nowait()
                    except Empty:
                        break
                    if newer is None:
                        stopped.set()
                        break
                    item = newer
                captured = frames.read()
                # Metadata and pixels must describe the same canonical frame.
                # If publication advanced while the tiny metadata message was
                # in transit, skip the stale pair instead of drawing wrong boxes.
                if (captured is not None and captured.raw is not None
                        and captured.sequence == item.frame_sequence):
                    latest = _MonitorFrame(
                        captured.raw, captured.width, captured.height,
                        item.overlay, item.diagnostics, item.frame_id,
                        item.latency_ms, item.published_at)
                    source_times.append(time.monotonic())
                    dirty = True
            now = time.monotonic()
            while source_times and now - source_times[0] > 2.0:
                source_times.popleft()
            source_hz = ((len(source_times) - 1) /
                         max(.001, source_times[-1] - source_times[0])
                         if len(source_times) >= 2 else 0.0)
            if latest is None or not dirty or now < next_display:
                if window_created and poll_key() in (27, ord("q"), ord("Q")):
                    break
                continue
            render_at = now
            display_times.append(render_at)
            while display_times and render_at - display_times[0] > 2.0:
                display_times.popleft()
            display_hz = ((len(display_times) - 1) /
                          max(.001, display_times[-1] - display_times[0])
                          if len(display_times) >= 2 else 0.0)
            draw_started = time.perf_counter()
            canvas = LiveVisionMonitor.render_frame(
                latest, display_hz=display_hz, source_hz=source_hz,
                timing=f"draw {draw_ms:.1f} show {show_ms:.1f} ms",
                max_width=preview_width, max_height=preview_height,
                navigation=navigation)
            draw_ms = .8*draw_ms + .2*(time.perf_counter()-draw_started)*1000
            if not window_created:
                cv2.namedWindow(window_title, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(window_title, 1280, 720)
                window_created = True
            show_started = time.perf_counter()
            cv2.imshow(window_title, canvas)
            dirty = False
            next_display = time.monotonic() + 1.0 / maximum_hz
            key = poll_key()
            show_ms = .8*show_ms + .2*(time.perf_counter()-show_started)*1000
            if key in (27, ord("q"), ord("Q")):
                break
    finally:
        stopped.set()
        frames.close()
        if window_created:
            try:
                cv2.destroyWindow(window_title)
            except cv2.error:
                pass
