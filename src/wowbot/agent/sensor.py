"""Foreground client-area pixels only. No handles to process memory are opened."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import time
import threading
from collections import deque
from .coordinates import pixel_context
from .runtime_scheduler import RateMeter, RuntimeCadenceScheduler
from wowbot.runtime.backpressure import bound_queue, coalesce_latest, drop_stale


class ClientCapture:
    def __init__(self, pid: int, backend):
        self.pid, self.backend = pid, backend
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        self.g = ctypes.WinDLL("gdi32", use_last_error=True)
        self.u.GetForegroundWindow.restype = w.HWND
        self.u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        self.u.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
        self.u.GetDC.argtypes, self.u.GetDC.restype = [w.HWND], w.HDC
        self.u.ReleaseDC.argtypes = [w.HWND, w.HDC]
        self.g.CreateCompatibleDC.argtypes, self.g.CreateCompatibleDC.restype = [w.HDC], w.HDC
        self.g.CreateCompatibleBitmap.argtypes, self.g.CreateCompatibleBitmap.restype = [w.HDC, ctypes.c_int, ctypes.c_int], w.HBITMAP
        self.g.SelectObject.argtypes, self.g.SelectObject.restype = [w.HDC, w.HANDLE], w.HANDLE
        self.g.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HDC, ctypes.c_int, ctypes.c_int, w.DWORD]
        self.g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, ctypes.c_void_p, ctypes.c_void_p, w.UINT]
        self.g.DeleteObject.argtypes = [w.HANDLE]
        self.g.DeleteDC.argtypes = [w.HDC]
        self.last_capture_status = "waiting"

    @pixel_context("u")
    def capture(self):
        from adapters.pixel_bridge import BITMAPINFO, BITMAPINFOHEADER
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
        screen = self.u.GetDC(None)
        dc = self.g.CreateCompatibleDC(screen)
        bitmap = self.g.CreateCompatibleBitmap(screen, width, height)
        old = self.g.SelectObject(dc, bitmap)
        try:
            if not screen or not dc or not bitmap or not old:
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.g.BitBlt(dc, 0, 0, width, height, screen, origin.x, origin.y, 0x00CC0020):
                raise ctypes.WinError(ctypes.get_last_error())
            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth, info.bmiHeader.biHeight = width, -height
            info.bmiHeader.biPlanes, info.bmiHeader.biBitCount = 1, 32
            raw = ctypes.create_string_buffer(width * height * 4)
            if self.g.GetDIBits(dc, bitmap, 0, height, raw, ctypes.byref(info), 0) != height:
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.backend.is_selected_foreground() or self.u.GetForegroundWindow() != hwnd:
                self.last_capture_status = "selected_PID_not_foreground"
                return None
            # "backend" lets the live debugger (and agent_status.json /
            # sensor_diagnostics.capture_geometry) show which capture path is
            # actually active -- added 2026-09-14 alongside the opt-in DXGI
            # backend so a bad AIPC_CAPTURE_BACKEND=dxgi run is distinguishable
            # from this default GDI path at a glance, not just inferred.
            self.geometry = {"width": width, "height": height, "origin": [origin.x, origin.y],
                             "dpi_context": "PER_MONITOR_AWARE_V2", "backend": "gdi"}
            self.last_capture_status = "captured"
            return raw.raw, width, height
        finally:
            if old and dc:
                self.g.SelectObject(dc, old)
            if bitmap:
                self.g.DeleteObject(bitmap)
            if dc:
                self.g.DeleteDC(dc)
            if screen:
                self.u.ReleaseDC(None, screen)


class PixelSensor:
    def __init__(self, capture):
        from adapters.telemetry_packets import PacketAssembler
        self.capture = capture
        self.assembler = PacketAssembler()
        self.next_discovery = 0.
        self.last_payload = None
        self.frame = None
        self.last_frame_at = 0.
        self.health = "waiting_for_AIPC5"
        self.started_at = time.monotonic()
        self.capture_attempts = 0
        self.captured_frames = 0
        self.decoded_packets = 0
        self.fast_packets = 0
        self.state_pages = 0
        self.published_updates = 0
        self.fresh_fast_packets = 0
        self.completed_full_states = 0
        self.last_decoded_at = None
        self.last_published_at = None
        self.last_packet_identity = None
        self.last_packet_changed_at = None
        self.repeated_packet_frames = 0
        self.capture_attempt_rate = RateMeter(10.)
        self.captured_frame_rate = RateMeter(10.)
        self.decoded_packet_rate = RateMeter(10.)
        self.fast_packet_rate = RateMeter(10.)
        self.state_page_rate = RateMeter(10.)
        self.publish_rate = RateMeter(10.)
        self.fresh_fast_rate = RateMeter(10.)
        self.completed_full_rate = RateMeter(30.)

    def poll(self, now: float):
        from adapters.pixel_bridge import (decode_payload_from_bgra, pixel_strip_diagnostics,
                                           _GRID_CACHE)
        decoded_remotely = hasattr(self.capture, "last_decoded")
        if not decoded_remotely and not _GRID_CACHE and now < self.next_discovery:
            return None
        self.capture_attempts += 1
        self.capture_attempt_rate.mark(now)
        frame = self.capture.capture()
        if frame is None:
            capture_status = getattr(self.capture, "last_capture_status", None)
            # DXGI returns None normally when polled between two compositor
            # presents. That is not a focus loss and must not erase the latest
            # usable frame or flap sensor health every other 120 Hz poll.
            if capture_status != "no_new_frame":
                self.health = capture_status or "selected_PID_not_foreground"
                self.frame = None
            return None
        self.captured_frames += 1
        self.captured_frame_rate.mark(now)
        self.frame, self.last_frame_at = frame, now
        raw, width, height = frame
        remote = getattr(self.capture, "last_decoded", None)
        if remote is not None:
            # Decoded by the capture process (off this process's GIL).
            from .shared_frame_buffer import PAYLOAD_DECODED
            text, state = remote
            if state != PAYLOAD_DECODED:
                self.health = f"pixel_strip_not_visible:{text or f'{width}x{height}:fallback'}"
                return None
            payload = text
        else:
            payload = decode_payload_from_bgra(raw, width, height)
        if payload is None:
            self.next_discovery = now + 1.
            diagnostic = pixel_strip_diagnostics()
            self.health = ("pixel_strip_not_visible:"
                           f"{diagnostic.get('resolution', f'{width}x{height}')}:"
                           f"{diagnostic.get('profile', 'fallback')}")
            return None
        if not payload.startswith("AIPC5|"):
            self.health = "old_addon_install_0.8.0"
            return None
        self.decoded_packets += 1
        self.last_decoded_at = now
        self.decoded_packet_rate.mark(now)
        parts = payload.split("|", 6)
        packet_identity = tuple(parts[1:6]) if len(parts) == 7 else None
        if packet_identity != self.last_packet_identity:
            self.last_packet_identity = packet_identity
            self.last_packet_changed_at = now
            self.repeated_packet_frames = 0
        else:
            self.repeated_packet_frames += 1
        if len(parts) == 7 and parts[5] == "FAST":
            self.fast_packets += 1
            self.fast_packet_rate.mark(now)
        elif len(parts) == 7 and parts[5] in {"STATE", "STATE_Z"}:
            self.state_pages += 1
            self.state_page_rate.mark(now)
        result = self.assembler.feed(payload, now)
        if result is not None:
            self.last_published_at = now
            self.published_updates += 1
            self.publish_rate.mark(now)
            if result.get("transport_kind") == "FAST":
                self.fresh_fast_packets += 1
                self.fresh_fast_rate.mark(now)
            else:
                self.completed_full_states += 1
                self.completed_full_rate.mark(now)
        packet_frozen_for = (None if self.last_packet_changed_at is None else
                             max(0., now-self.last_packet_changed_at))
        if self.assembler.full and packet_frozen_for is not None and packet_frozen_for > 2.:
            self.health = "pixelstrip_packet_frozen"
        elif (self.assembler.full and self.last_published_at is not None
                and now-self.last_published_at > 2.):
            self.health = "telemetry_packet_assembly_stalled"
        else:
            self.health = "streaming" if self.assembler.full else "assembling_initial_snapshot"
        return result

    @property
    def diagnostics(self):
        now = time.monotonic()
        return {
            "capture_attempts": self.capture_attempts,
            "capture_attempt_hz": self.capture_attempt_rate.hz(now),
            "captured_frames": self.captured_frames,
            "captured_frame_hz": self.captured_frame_rate.hz(now),
            "decoded_packets": self.decoded_packets,
            "decoded_packet_hz": self.decoded_packet_rate.hz(now),
            "fast_packets": self.fast_packets,
            "decoded_fast_frame_hz": self.fast_packet_rate.hz(now),
            "fresh_fast_packets": self.fresh_fast_packets,
            "source_fast_hz": self.fresh_fast_rate.hz(now),
            "state_pages": self.state_pages,
            "source_state_page_hz": self.state_page_rate.hz(now),
            "published_updates": self.published_updates,
            "source_publish_hz": self.publish_rate.hz(now),
            "completed_full_states": self.completed_full_states,
            "completed_full_state_hz": self.completed_full_rate.hz(now),
            "last_decoded_age": (None if self.last_decoded_at is None
                                 else round(max(0., now-self.last_decoded_at), 3)),
            "last_published_age": (None if self.last_published_at is None
                                   else round(max(0., now-self.last_published_at), 3)),
            "last_packet_identity": list(self.last_packet_identity or ()),
            "last_packet_changed_age": (
                None if self.last_packet_changed_at is None
                else round(max(0., now-self.last_packet_changed_at), 3)),
            "repeated_packet_frames": self.repeated_packet_frames,
        }


class BufferedPixelSensor:
    """Continuously assemble pages while execution is holding a movement key.

    Only complete, timestamped observations cross the single-reader boundary.
    This is a sensor worker, not a second planner or input authority.
    """

    def __init__(self, source, interval=.025):
        self.source, self.interval = source, interval
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.pending = None
        self.transitions = deque(maxlen=16)
        self._last_transition_key = None
        self.frame = None
        # Called (outside the lock) whenever a new capture frame object is
        # published, so frame consumers can wake immediately instead of
        # polling on Windows' ~15.6 ms timer granularity.
        self.frame_listeners: list = []
        self.health = "waiting_for_AIPC5"
        self.polls = self.updates = self.coalesced = 0
        self.poll_ms = 0.
        self.started_at = time.monotonic()
        self.poll_rate = RateMeter(10.)
        self.update_rate = RateMeter(10.)
        self.coalesced_rate = RateMeter(10.)
        self.scheduler = RuntimeCadenceScheduler()

    def start(self):
        if self.thread is not None:
            raise RuntimeError("Sensor worker already started")
        self.thread = threading.Thread(target=self._run, name="aipc-pixel-sensor", daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            started = time.monotonic()
            if not self.scheduler.should_capture(started, interval=self.interval):
                self.stop_event.wait(min(.005, self.interval))
                continue
            try:
                value = self.source.poll(started)
                finished = time.monotonic()
                with self.lock:
                    self.polls += 1
                    self.poll_rate.mark(finished)
                    self.poll_ms = (finished-started)*1000
                    self.health = self.source.health
                    new_frame = (self.source.frame is not None
                                 and self.source.frame is not self.frame)
                    self.frame = self.source.frame
                    if value is not None:
                        self.updates += 1
                        self.update_rate.mark(finished)
                        self.pending, was_coalesced = coalesce_latest(
                            self.pending, (value, finished))
                        if was_coalesced:
                            self.coalesced += 1
                            self.coalesced_rate.mark(finished)
                        # Preserve short-lived ground-truth edges (especially
                        # mouseover/tooltips) separately from the coalesced
                        # latest-state mailbox.  This is still bounded and the
                        # single runtime consumer remains authoritative.
                        transition_key = self._transition_key(value)
                        if transition_key != self._last_transition_key:
                            bound_queue(self.transitions, (value, finished), max_size=16)
                            self._last_transition_key = transition_key
                if new_frame:
                    for listener in list(self.frame_listeners):
                        try:
                            listener()
                        except Exception:
                            pass
            except Exception as error:
                with self.lock:
                    self.health = f"sensor_error:{type(error).__name__}:{error}"
                    self.pending = self.frame = None
                self.stop_event.wait(.25)
            self.stop_event.wait(max(0., self.interval-(time.monotonic()-started)))

    def poll(self, now):
        with self.lock:
            retained, _ = drop_stale(
                tuple(self.transitions), now=now, max_age=.5,
                timestamp=lambda item: item[1])
            self.transitions = deque(retained, maxlen=16)
            pending = self.transitions.popleft() if self.transitions else self.pending
            if pending is self.pending:
                self.pending = None
            elif self.pending and pending[0].get("frame_id") == self.pending[0].get("frame_id"):
                self.pending = None
        if pending is None:
            return None
        value, received = pending
        lag = max(0., now-received)
        if lag > .5:
            return None  # A stopped sensor cannot refresh the world with its mailbox.
        return {**value, "state_age": float(value.get("state_age") or 0)+lag}

    @staticmethod
    def _transition_key(value):
        def identity(unit):
            unit = unit if isinstance(unit, dict) else {}
            return (unit.get("guid"), unit.get("npc_id"), unit.get("name"),
                    unit.get("tooltip_text"), unit.get("dead", unit.get("is_dead")))
        quest_ui = value.get("quest_ui") if isinstance(value.get("quest_ui"), dict) else {}
        gossip_ui = value.get("gossip_ui") if isinstance(value.get("gossip_ui"), dict) else {}
        return (identity(value.get("mouseover")), identity(value.get("target")),
                value.get("quest_state_revision"), bool(quest_ui.get("open")),
                quest_ui.get("quest_id"), bool(gossip_ui.get("open")),
                value.get("event_sequence"))

    @property
    def diagnostics(self):
        with self.lock:
            now = time.monotonic()
            return {"polls": self.polls, "poll_hz": self.poll_rate.hz(now),
                    "updates": self.updates, "update_hz": self.update_rate.hz(now),
                    "coalesced": self.coalesced, "poll_ms": round(self.poll_ms, 2),
                    "coalesced_hz": self.coalesced_rate.hz(now),
                    "interval_ms": round(self.interval*1000, 3),
                    "transition_backlog": len(self.transitions),
                    "capture_geometry": getattr(getattr(self.source, "capture", None), "geometry", None),
                    "source": getattr(self.source, "diagnostics", {})}

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        with self.lock:
            self.pending = self.frame = None
            self.transitions.clear()
