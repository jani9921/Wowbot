"""Optional DXGI Desktop Duplication capture backend. Opt-in only.

sensor.py's ClientCapture (GDI BitBlt+GetDIBits) remains the shipped,
tested default -- this file changes nothing about it and is never imported
unless explicitly selected.

Why this exists: live-measured 2026-09-14 against the real running game
window, ClientCapture.capture() cost ~20-35ms per 1128x634 frame (the
sensor_diagnostics.poll_ms this session's own telemetry reported all
night), well above the addon's own 25ms pixel-strip write cadence
(TRANSPORT_INTERVAL in the Lua source). That gap meant a real portion of
polls landed mid-write and got discarded by the payload's own checksum
(pixel_bridge.py) -- never a correctness risk (bad data is never used),
but a throughput one: the effective decoded-payload rate this session
averaged only ~12-14 Hz, well under either nominal rate, and directly
behind several of this session's `telemetry_stalled`/
`expected_observation_missing` failures.

A live smoke test the same night (against this exact WoW window, PID and
resolution) with the `dxcam` package (DXGI Desktop Duplication, no GDI
involved) measured ~4-6ms for a cold first grab. The very first measurement
of a *sustained* call rate was wrong -- it counted every grab() call
(~13,900/s with new_frame_only=True) without checking how many returned
None, which turned out to be nearly all of them (dxcam correctly returns
None immediately when the compositor has nothing new since the last call,
rather than blocking or re-returning stale data). Redone properly,
distinguishing None from a real frame and hashing a strided sample of each
real frame to detect genuine content changes: only ~60 *distinct* frames
per second were ever produced, whether polled at ~62 Hz (new_frame_only=True)
or ~1840 Hz raw call rate (new_frame_only=False, forcing a fresh GPU read
every call). That ~60 Hz ceiling is the monitor's own refresh rate -- no
capture method can exceed it, since the compositor itself does not produce
new frames faster than that.

So the realistic comparison is ~60 Hz (DXGI, refresh-rate-limited) vs the
~28 Hz raw poll rate GDI achieves today -- a real but modest ~2x, not the
500x the first (wrong) measurement suggested. The more important difference
isn't the raw rate: DXGI hands back one complete, compositor-consistent
frame per acquisition, atomically, with no possibility of the torn
old+new-payload mix that GDI's BitBlt-against-an-in-progress-redraw can
produce (that's a race between two independent, unsynchronized loops, not
a raw-speed problem) -- so the ~30% checksum-rejected torn-frame loss this
session measured against GDI should not occur here at all, which matters
more for effective decoded-payload throughput than the 2x alone would.

Byte length matched exactly (width*height*4) and a saved screenshot from
the capture was visually correct (crisp UI text, natural colors -- a
channel-order bug would show as a visible red/cyan or magenta/green shift,
which it did not). The one thing NOT yet confirmed live: decoding an actual
AIPC5 pixel-strip payload through this path, since no character was
in-world at test time (the addon only draws the strip in-game). Functionally
this should be identical to GDI's output (both feed the same BGRA byte
layout into decode_payload_from_bgra), but treat that specific claim as
unconfirmed until checked against a live in-game frame.

Enable with the AIPC_CAPTURE_BACKEND=dxgi environment variable (see
runtime.py). Leaving it unset uses ClientCapture exactly as before --
zero behavior change. Requires `pip install dxcam`; the import is lazy so
the base install is unaffected either way. To roll back: unset the
environment variable (or never set it). No code or data changes are
needed to revert.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import logging
import numpy as np
from .coordinates import pixel_context

_logger = logging.getLogger(__name__)


class DxgiClientCapture:
    def __init__(self, pid: int, backend):
        self.pid, self.backend = pid, backend
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        self.u.GetForegroundWindow.restype = w.HWND
        self.u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        self.u.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
        try:
            import dxcam
        except ImportError as error:
            raise RuntimeError(
                "AIPC_CAPTURE_BACKEND=dxgi requires the 'dxcam' package "
                "(pip install dxcam); it is not installed") from error
        self._dxcam = dxcam
        self._dxgi_camera = None
        self.geometry = {}
        self.last_capture_status = "waiting"

    def _camera(self):
        # Created lazily, on first use, from whichever thread actually calls
        # capture() -- for the real sensor that is always the single
        # dedicated BufferedPixelSensor background thread, never the
        # constructing thread. COM objects (which dxcam/comtypes use
        # internally for DXGI) are thread-affine; creating and using this on
        # the same thread avoids relying on cross-thread COM marshaling that
        # was never exercised in the live smoke test.
        if self._dxgi_camera is None:
            self._dxgi_camera = self._dxcam.create(output_color="BGRA")
            if self._dxgi_camera is None:
                raise RuntimeError("dxcam.create() nem talált rögzíthető DXGI kimenetet")
        return self._dxgi_camera

    @staticmethod
    def _clip_client_to_output(origin_x: int, origin_y: int, width: int, height: int,
                               output_bounds: tuple[int, int, int, int]):
        """Translate a global client rect to a valid output-local DXGI region.

        A window may extend a few pixels beyond the desktop while being moved,
        maximized or restored. dxcam rejects that entire grab. Preserve the
        client-sized coordinate space by capturing the visible intersection and
        padding the off-screen edge instead.
        """
        output_left, output_top, output_right, output_bottom = output_bounds
        visible_left = max(origin_x, output_left)
        visible_top = max(origin_y, output_top)
        visible_right = min(origin_x+width, output_right)
        visible_bottom = min(origin_y+height, output_bottom)
        if visible_left >= visible_right or visible_top >= visible_bottom:
            return None
        region = (visible_left-output_left, visible_top-output_top,
                  visible_right-output_left, visible_bottom-output_top)
        return (region, visible_left-origin_x, visible_top-origin_y,
                visible_right-visible_left, visible_bottom-visible_top,
                (visible_left, visible_top, visible_right, visible_bottom)
                != (origin_x, origin_y, origin_x+width, origin_y+height))

    @staticmethod
    def _output_bounds(camera) -> tuple[int, int, int, int]:
        desc = getattr(getattr(camera, "_output", None), "desc", None)
        rect = getattr(desc, "DesktopCoordinates", None)
        if rect is not None:
            return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        return 0, 0, int(camera.width), int(camera.height)

    @pixel_context("u")
    def capture(self):
        if not self.backend.is_selected_foreground():
            self.last_capture_status = "selected_PID_not_foreground"
            return None
        hwnd = self.u.GetForegroundWindow()
        rect, origin = w.RECT(), w.POINT()
        if not self.u.GetClientRect(hwnd, ctypes.byref(rect)) or not self.u.ClientToScreen(hwnd, ctypes.byref(origin)):
            raise ctypes.WinError(ctypes.get_last_error())
        width, height = rect.right, rect.bottom
        if width < 320 or height < 200 or width * height > 20000000:
            raise RuntimeError("Érvénytelen/minimalizált kliensablak")
        camera = self._camera()
        output_bounds = self._output_bounds(camera)
        clipped = self._clip_client_to_output(origin.x, origin.y, width, height,
                                              output_bounds)
        if clipped is None:
            self.last_capture_status = "selected_client_outside_dxgi_output"
            return None
        region, paste_x, paste_y, visible_width, visible_height, was_clipped = clipped
        frame = camera.grab(region=region)
        if frame is None:
            self.last_capture_status = "no_new_frame"
            return None
        if not self.backend.is_selected_foreground() or self.u.GetForegroundWindow() != hwnd:
            self.last_capture_status = "selected_PID_not_foreground"
            return None
        if frame.shape[1] != visible_width or frame.shape[0] != visible_height:
            # A resize/DPI change mid-grab; drop this sample rather than
            # hand the decoder a buffer length it does not expect.
            self.last_capture_status = "client_resized_during_capture"
            return None
        if was_clipped:
            client_frame = np.zeros((height, width, frame.shape[2]), dtype=frame.dtype)
            client_frame[paste_y:paste_y+visible_height,
                         paste_x:paste_x+visible_width] = frame
            frame = client_frame
        self.geometry = {"width": width, "height": height, "origin": [origin.x, origin.y],
                         "dpi_context": "PER_MONITOR_AWARE_V2", "backend": "dxgi",
                         "output_bounds": list(output_bounds), "capture_region": list(region),
                         "client_clipped_to_output": was_clipped}
        self.last_capture_status = "captured"
        return frame.tobytes(), width, height

    def close(self):
        if self._dxgi_camera is not None:
            try:
                self._dxgi_camera.release()
            except Exception:
                # V4-077: cleanup-time failure must not raise (would mask
                # the caller's own shutdown), but must not be silent either.
                _logger.warning("dxgi_camera.release() failed during close()", exc_info=True)
            self._dxgi_camera = None
