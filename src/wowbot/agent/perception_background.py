"""PerceptionWorker background pump: latest-frame submission, adaptive cadence, cycle timing.

Split out of perception.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import threading
import time
from wowbot.vision.world3d.profiles import resolve_world3d_profile


class PerceptionBackgroundMixin:
    """Methods of PerceptionWorker (perception.py); moved verbatim."""

    @property
    def background_active(self) -> bool:
        return self._background_thread is not None and self._background_thread.is_alive()

    def start_background(self, frame_provider, *, hz: float = 40.) -> None:
        """Start the single live perception owner over a latest-frame source."""
        if self.background_active:
            return
        self._background_frame_provider = frame_provider
        # The pump must sample faster than the 30 Hz tracker gate. At exactly
        # 60 Hz, collecting an async result on one tick and narrowly missing
        # the 33.3 ms gate on the next quantized publication to ~20-24 Hz.
        # 90 Hz gives the gate a third sampling point without queueing frames;
        # update() still submits detector/tracker work only when its own
        # cadence gate is due.
        self._background_interval = 1. / max(30., min(120., float(hz)))
        self._background_stop.clear()
        self._background_thread = threading.Thread(
            target=self._background_loop, name="aipc-perception-pump", daemon=True)
        self._background_thread.start()

    def submit_latest(self, *, allow=True, geometry=None, context=None,
                      world_map_open=False) -> list[dict]:
        """Replace live perception context without ever queueing stale work."""
        with self._background_lock:
            self._background_request = {
                "allow": allow, "geometry": dict(geometry or {}),
                "context": context, "world_map_open": world_map_open,
            }
            result = list(self._background_result)
        self._background_wake.set()
        return result

    def _background_loop(self) -> None:
        next_tick = time.monotonic()
        while not self._background_stop.is_set():
            now = time.monotonic()
            if now < next_tick:
                woken = self._background_wake.wait(min(next_tick-now, self._background_interval))
                self._background_wake.clear()
                # A finished vision job, a new capture frame or a new request
                # is served now; a plain timeout re-checks the tick deadline.
                if not woken:
                    continue
            with self._background_lock:
                request = dict(self._background_request or {})
            provider = self._background_frame_provider
            frame = provider() if callable(provider) else None
            if request and frame is not None:
                try:
                    result = self.update(frame, now, **request)
                    with self._background_lock:
                        self._background_result = result
                        self._background_error = None
                except Exception as error:  # passive perception must fail closed
                    with self._background_lock:
                        self._background_error = f"{type(error).__name__}:{error}"
            next_tick = max(next_tick + self._background_interval,
                            time.monotonic() + .001)

    def _robust_propagation_ms(self) -> float | None:
        if self._propagate_duration_window_ms:
            ordered = sorted(self._propagate_duration_window_ms)
            return float(ordered[len(ordered)//2])
        return self._propagate_duration_ms

    def _dynamic_interval(self, name: str, geometry: dict) -> float:
        lane = self.lanes[name]
        duration = (float(lane["duration_ms"])/1000
                    if lane.get("duration_ms") is not None else 0.)
        if name == "world":
            profile = resolve_world3d_profile(geometry)
            has_tracks = self._has_active_tracks()
            # Every context gets tracker/control feedback at a nominal 30 Hz.
            # World3DPerceptionV3 owns one continuous, single-in-flight
            # latest-frame detector stream; intermediate jobs propagate the
            # last boxes while inference is busy. Measured execution time
            # remains the hard lower bound, so slower hosts never accumulate a
            # stale frame queue.
            # Schedule active tracking with enough headroom to absorb the
            # periodic canonical/minimap publication ticks. The tracker-only
            # job costs about 0.6-1.0 ms; its 40 Hz admission is independent
            # from the 4 Hz canonical evidence layer and targets at least 30
            # completed projections per second under live scheduler jitter.
            active_schedule_hz = 45.
            desired = min(1./profile.tracker_hz,
                          1./active_schedule_hz if geometry.get("fast_visual_servo") else
                          1./active_schedule_hz if geometry.get("tooltip_probe") or has_tracks else 1./24)
            # A full V2 refresh can take 400-800 ms on the live CPU, while
            # propagation of its existing tracks is cheap.  Using the last
            # full-refresh cost as back-pressure delayed the *next tracker*
            # by another 500 ms; by then V3's detector deadline had elapsed,
            # so nearly every job became another full refresh.  During a
            # committed visual servo, schedule from the measured propagation
            # cost instead. V3 independently rate-limits heavy refreshes.
            # Once a real propagation cost exists, it is the scheduler cost
            # for every tracker tick. A slow periodic detector refresh must
            # not hold the complete lane at detector latency (live example:
            # 131 ms detector versus 4 ms propagation). V3 independently
            # decides when the next heavy refresh is due.
            robust_propagation_ms = self._robust_propagation_ms()
            if robust_propagation_ms is not None:
                # Compatibility for restored diagnostics and focused tests
                # which seed only the last measurement.
                duration = robust_propagation_ms/1000
        else:
            desired = .10 if geometry.get("visible") else .50
        # Never queue work faster than this CPU has demonstrated it can finish.
        return min(.50, max(desired, duration*1.10))

    def notify_new_frame(self) -> None:
        """Wake the background pump for a newly captured frame."""
        self._background_wake.set()

    def _cycle_summary(self) -> dict:
        """Median world-lane cycle parts (ms): where published Hz is lost."""
        now = time.monotonic()
        if now < getattr(self, "_cycle_summary_until", 0.):
            return self._cycle_summary_cache
        self._cycle_summary_until = now + .5
        summary = {}
        for key in ("queue", "process", "harvest_latency", "post"):
            values = sorted(float(row[key]) for row in self._world_cycle_ms
                            if row.get(key) is not None)
            if values:
                summary[key] = round(values[len(values)//2], 2)
        periods = sorted(self._world_submit_periods_ms)
        if periods:
            summary["submit_period"] = round(periods[len(periods)//2], 2)
        self._cycle_summary_cache = summary
        return summary
