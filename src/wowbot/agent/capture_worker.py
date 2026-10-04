"""Process-based screen capture (phase 2 of
docs/PROCESS_BASED_CAPTURE_DESIGN_2026-09-22.txt).

The capture worker runs in its own OS process so a busy main-process GIL
(the agent tick()/world-ingest CPU work) can never starve it of scheduling
time -- live-confirmed 2026-09-22 as the cause of the capture thread's
`poll_ms` staying low (4-9ms) while its *real* throughput collapsed for
many seconds at a time. It reuses the existing `ClientCapture`/
`DxgiClientCapture` classes completely unchanged; only *where* they run
changes. Runtime integration is opt-in through ``AIPC_CAPTURE_PROCESS=1``.
"""
from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from multiprocessing import Process, Queue

from .shared_frame_buffer import (PAYLOAD_DECODED, PAYLOAD_NONE, PAYLOAD_NOT_VISIBLE,
                                  SharedFrameRingBuffer)

_STOP = "STOP"


def _build_capture(pid: int, backend_name: str):
    from .windows_input import WindowsInput
    backend = WindowsInput(pid)
    if backend_name == "dxgi":
        from .dxgi_capture import DxgiClientCapture
        return DxgiClientCapture(pid, backend)
    if backend_name == "gdi":
        from .sensor import ClientCapture
        return ClientCapture(pid, backend)
    if backend_name == "fake":
        # Deterministic synthetic producer for offline/CI tests: no real
        # window, GPU or WinAPI involved, but exercises the exact same
        # write_frame()/write_status() calling pattern as a real backend.
        return _FakeCapture()
    raise ValueError(f"unknown capture backend: {backend_name!r}")


class _FakeCapture:
    """Test-only stand-in; never used outside this module's own tests."""

    def __init__(self) -> None:
        self.last_capture_status = "waiting"
        self._tick = 0

    def capture(self):
        self._tick += 1
        self.last_capture_status = "captured"
        width = height = 4
        return bytes([self._tick % 256]) * (width * height * 4), width, height


class _StripDecoder:
    """AIPC5 pixel-strip decoding next to the capture (off the main GIL).

    Mirrors PixelSensor's discovery throttle: while no strip is found, full
    grid discovery is retried at most once per second.
    """

    def __init__(self) -> None:
        self.next_discovery = 0.
        self.last_diagnostic = ""

    def decode(self, raw: bytes, width: int, height: int, now: float) -> tuple[str | None, int]:
        from adapters.pixel_bridge import (_GRID_CACHE, decode_payload_from_bgra,
                                           pixel_strip_diagnostics)
        if not _GRID_CACHE and now < self.next_discovery:
            return self.last_diagnostic, PAYLOAD_NOT_VISIBLE
        payload = decode_payload_from_bgra(raw, width, height)
        if payload is None:
            self.next_discovery = now + 1.
            diagnostic = pixel_strip_diagnostics()
            self.last_diagnostic = (f"{diagnostic.get('resolution', f'{width}x{height}')}:"
                                    f"{diagnostic.get('profile', 'fallback')}")
            return self.last_diagnostic, PAYLOAD_NOT_VISIBLE
        return payload, PAYLOAD_DECODED


def run_capture_worker(*, pid: int, backend_name: str, name_prefix: str,
                       control_queue: "Queue", interval: float,
                       decode_strip: bool = False) -> None:
    """`multiprocessing.Process` target. No Tkinter/WorldModel/GUI import --
    this process knows nothing beyond "grab a frame, decode its telemetry
    strip, publish both"."""
    capture = _build_capture(pid, backend_name)
    ring = SharedFrameRingBuffer.attach(name_prefix=name_prefix)
    decoder = _StripDecoder() if decode_strip else None
    try:
        while True:
            try:
                if control_queue.get_nowait() == _STOP:
                    break
            except queue.Empty:
                pass
            started = time.monotonic()
            try:
                frame = capture.capture()
            except Exception as error:  # noqa: BLE001 -- must never crash the worker silently
                frame = None
                capture.last_capture_status = f"capture_worker_error:{type(error).__name__}:{error}"
            if frame is not None:
                raw, width, height = frame
                payload, payload_state = None, PAYLOAD_NONE
                if decoder is not None:
                    try:
                        payload, payload_state = decoder.decode(raw, width, height, started)
                    except Exception:  # noqa: BLE001 -- main process decodes instead
                        payload, payload_state = None, PAYLOAD_NONE
                ring.write_frame(raw, width, height, capture.last_capture_status, started,
                                 payload=payload, payload_state=payload_state)
            else:
                ring.write_status(capture.last_capture_status, started)
            elapsed = time.monotonic() - started
            time.sleep(max(0., interval - elapsed))
    finally:
        ring.close()


class ProcessCaptureClient:
    """Drop-in replacement for `ClientCapture`/`DxgiClientCapture`: same
    `.capture()` -> `(bytes, width, height) | None` and `.last_capture_status`
    contract, so `PixelSensor(capture)` needs no changes at all."""

    def __init__(self, process: Process, ring: SharedFrameRingBuffer) -> None:
        self._process = process
        self._ring = ring
        self.last_capture_status = "waiting_for_capture_process"
        self._last_frame_id = 0
        self.last_frame_id = 0
        self.geometry = None
        # frame_id -> frame, so a detector result produced in another process
        # can be anchored on exactly the pixels it saw.
        self._recent: dict[int, tuple[bytes, int, int]] = {}
        self._recent_order: list[int] = []
        # Telemetry decoded by the capture process for the frame last
        # returned by capture(): (payload_or_diagnostic, state) or None.
        self.last_decoded: tuple[str | None, int] | None = None

    def capture(self):
        if not self._process.is_alive():
            self.last_capture_status = "capture_process_died"
            return None
        header = self._ring._read_raw_header()
        if header[0] % 2 == 0 and header[6] == self._last_frame_id and self._last_frame_id:
            # No new frame: keep the status contract, skip the pixel copy.
            self.last_capture_status = header[5]
            return None
        result = self._ring.read()
        if result is None:
            return None
        self.last_capture_status = result.status
        # Shared memory exposes a snapshot, not a consuming queue. Frame
        # identity (not the header sequence, which status-only updates also
        # advance) prevents replaying one old frame as fresh telemetry, and a
        # 120 Hz "no_new_frame" status overwrite can no longer hide a frame.
        if result.raw is None or result.frame_id <= 0 or result.frame_id == self._last_frame_id:
            return None
        self._last_frame_id = self.last_frame_id = result.frame_id
        self.last_capture_status = "captured"
        self.last_decoded = ((result.payload, result.payload_state)
                             if result.payload_state != PAYLOAD_NONE else None)
        self.geometry = {"width": result.width, "height": result.height,
                         "origin": None, "dpi_context": "capture_process",
                         "backend": "process"}
        frame = (result.raw, result.width, result.height)
        self._recent[result.frame_id] = frame
        self._recent_order.append(result.frame_id)
        while len(self._recent_order) > 16:
            self._recent.pop(self._recent_order.pop(0), None)
        return frame

    def frame_for_id(self, frame_id: int):
        return self._recent.get(int(frame_id))

    @property
    def ring_name(self) -> str:
        return self._ring.name_prefix


@dataclass
class CaptureProcessHandle:
    client: ProcessCaptureClient
    process: Process
    ring: SharedFrameRingBuffer
    control_queue: "Queue"
    _stopped: bool = False

    def stop(self, *, timeout: float = 2.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        try:
            self.control_queue.put(_STOP)
        except Exception:  # noqa: BLE001 -- best-effort; terminate() below covers it
            pass
        self.process.join(timeout=timeout)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=timeout)
        self.ring.close()
        self.ring.unlink()
        self.control_queue.close()
        self.control_queue.join_thread()


def start_capture_process(*, pid: int, backend_name: str, name_prefix: str,
                          max_width: int, max_height: int,
                          interval: float, decode_strip: bool | None = None) -> CaptureProcessHandle:
    import os
    if decode_strip is None:
        decode_strip = os.environ.get("AIPC_CAPTURE_DECODE", "1").strip() != "0"
    ring = SharedFrameRingBuffer.create(name_prefix=name_prefix, max_width=max_width, max_height=max_height)
    control_queue: "Queue" = Queue()
    process = Process(target=run_capture_worker, kwargs=dict(
        pid=pid, backend_name=backend_name, name_prefix=name_prefix,
        control_queue=control_queue, interval=interval,
        decode_strip=bool(decode_strip)), daemon=True)
    try:
        process.start()
        client = ProcessCaptureClient(process, SharedFrameRingBuffer.attach(name_prefix=name_prefix))
        return CaptureProcessHandle(client, process, ring, control_queue)
    except Exception:
        ring.close()
        ring.unlink()
        control_queue.close()
        control_queue.join_thread()
        raise
