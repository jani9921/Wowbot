"""Default-sensor construction, extracted from AgentRuntime.__init__ to keep
runtime.py's line count down (tests/test_v4_083_095_module_size_reduction.py).

Picks the capture backend (GDI/DXGI) and whether it runs in-process or in a
separate OS process (see docs/PROCESS_BASED_CAPTURE_DESIGN_2026-09-22.txt),
both opt-in via environment variables so the default behavior is unchanged.
"""
from __future__ import annotations

import os

from .sensor import BufferedPixelSensor, ClientCapture, PixelSensor
from .sensor_hub import SensorHub


def build_default_sensor(pid: int, executor_backend):
    """Returns (sensor_hub, capture_process_handle | None)."""
    # Opt-in only; unset (the default) keeps the exact existing GDI capture
    # with zero behavior change. See dxgi_capture.py for why this exists (a
    # live-measured ~30% torn-frame loss from GDI BitBlt being slower than
    # the addon's own write cadence) and what has/hasn't been confirmed live
    # yet before defaulting to it.
    capture_backend = os.environ.get("AIPC_CAPTURE_BACKEND", "gdi").strip().lower()
    # DXGI can cheaply report "no new frame" and WoW normally presents near
    # 60 Hz. Polling it at 120 Hz avoids phase-locking to the present cadence
    # and missing every other strip update. GDI still performs a full
    # BitBlt, so retain its established 40 Hz ceiling.
    sensor_interval = 1. / 120. if capture_backend == "dxgi" else .025
    # Opt-in only: live-confirmed 2026-09-22 that the capture thread's
    # poll_ms stays low (4-9ms) even while its real throughput collapses for
    # many seconds at a time -- a GIL-starvation symptom from the busy agent
    # thread sharing this process, not a slow capture call. Moving the
    # capture loop to its own OS process removes it from that GIL entirely;
    # ClientCapture/DxgiClientCapture/PixelSensor/BufferedPixelSensor are all
    # reused completely unchanged either way.
    capture_process_handle = None
    if os.environ.get("AIPC_CAPTURE_PROCESS", "").strip() == "1":
        from .capture_worker import start_capture_process
        capture_process_handle = start_capture_process(
            pid=pid, backend_name=capture_backend if capture_backend in {"dxgi", "gdi"} else "gdi",
            name_prefix=f"aipc_capture_{pid}_{os.getpid()}",
            max_width=3840, max_height=2160, interval=sensor_interval)
        capture = capture_process_handle.client
    elif capture_backend == "dxgi":
        from .dxgi_capture import DxgiClientCapture
        capture = DxgiClientCapture(pid, executor_backend)
    else:
        capture = ClientCapture(pid, executor_backend)
    buffered_sensor = BufferedPixelSensor(PixelSensor(capture), interval=sensor_interval)
    return SensorHub.for_primary(buffered_sensor), capture_process_handle
