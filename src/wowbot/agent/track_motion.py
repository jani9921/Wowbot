"""Where a moving World3D box will be when the pointer gets there.

User 2026-10-05: "gyorsabban kéne vigye az egeret a mozgó trackre, mert
sokszor lemarad a trackről, mire odateszi az egeret már máshol van".  A box
position is a capture-time measurement; by the time a hover lands the unit
has moved on.  Each tick the box's screen velocity is measured from its last
positions; a hover aims at position + velocity x (age + pointer latency),
bounded.  While the player turns the whole picture moves and a stopped turn
would make the lead overshoot, so no lead is applied then.
"""
from __future__ import annotations

import math
from collections import deque

from .models import number

WINDOW_SECONDS = .6
MIN_SPAN_SECONDS = .1
POINTER_LATENCY_SECONDS = .06
MAX_LEAD_SECONDS = .5
MAX_SHIFT = .12
TURNING_RADIANS = .05
FORGET_SECONDS = 2.


class TrackMotion:
    def __init__(self) -> None:
        self.history: dict[str, deque] = {}
        self.orientation: deque = deque(maxlen=40)

    def observe(self, state: dict) -> None:
        """Measure every World3D box's velocity and attach it (``screen_velocity``)."""
        now = number(state.get("monotonic_time"))
        facing = number(state.get("orientation"))
        if now is not None and facing is not None and (
                not self.orientation or now > self.orientation[-1][0]):
            self.orientation.append((now, facing))
        turning = self._turning(now)
        newest = None
        for item in state.get("visual_candidates") or ():
            if not isinstance(item, dict) or item.get("source") != "WORLD3D":
                continue
            track, at = item.get("track_id"), number(item.get("observed_at"))
            x, y = number(item.get("x")), number(item.get("y"))
            if track is None or None in (at, x, y):
                continue
            samples = self.history.setdefault(str(track), deque(maxlen=12))
            if not samples or at > samples[-1][0]:
                samples.append((at, x, y))
            newest = at if newest is None else max(newest, at)
            velocity = None if turning else self._velocity(samples)
            if velocity is not None:
                item["screen_velocity"] = {"x": velocity[0], "y": velocity[1]}
            else:
                item.pop("screen_velocity", None)
        if newest is not None:
            for track in [key for key, samples in self.history.items()
                          if newest - samples[-1][0] > FORGET_SECONDS]:
                del self.history[track]

    def _turning(self, now) -> bool:
        if now is None:
            return False
        recent = [facing for at, facing in self.orientation if now - at <= WINDOW_SECONDS]
        if len(recent) < 2:
            return False
        return any(abs((b-a+math.pi) % math.tau - math.pi) > TURNING_RADIANS
                   for a, b in zip(recent, recent[1:])) or abs(
            (recent[-1]-recent[0]+math.pi) % math.tau - math.pi) > TURNING_RADIANS

    @staticmethod
    def _velocity(samples) -> tuple[float, float] | None:
        last = samples[-1]
        window = [sample for sample in samples if last[0] - sample[0] <= WINDOW_SECONDS]
        first = window[0]
        span = last[0] - first[0]
        if span < MIN_SPAN_SECONDS:
            return None
        return (last[1]-first[1])/span, (last[2]-first[2])/span


def predicted_point(candidate: dict, state: dict, now: float | None = None,
                    *, y: float | None = None) -> tuple[float, float] | None:
    """The box point (``y`` overrides its centre height) led by its velocity."""
    x0 = number(candidate.get("x"))
    y0 = number(candidate.get("y")) if y is None else y
    if x0 is None or y0 is None:
        return None
    velocity = candidate.get("screen_velocity") or {}
    vx, vy = number(velocity.get("x")), number(velocity.get("y"))
    at = number(candidate.get("observed_at"))
    now = number(state.get("monotonic_time")) if now is None else now
    if None in (vx, vy, at, now):
        return x0, y0
    lead = min(MAX_LEAD_SECONDS, max(0., now - at) + POINTER_LATENCY_SECONDS)
    dx, dy = vx*lead, vy*lead
    shift = math.hypot(dx, dy)
    if shift > MAX_SHIFT:
        dx, dy = dx*MAX_SHIFT/shift, dy*MAX_SHIFT/shift
    return min(.99, max(.01, x0+dx)), min(.99, max(.01, y0+dy))


def candidate_for_track(state: dict, track_id) -> dict | None:
    if track_id is None:
        return None
    return next((item for item in state.get("visual_candidates") or ()
                 if isinstance(item, dict) and item.get("source") == "WORLD3D"
                 and str(item.get("track_id")) == str(track_id)), None)
