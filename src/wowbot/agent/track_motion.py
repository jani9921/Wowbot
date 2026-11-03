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
        self.context = None
        self.models = {}

    def observe(self, state: dict) -> None:
        """Measure every World3D box's velocity and attach it (``screen_velocity``)."""
        now = number(state.get("monotonic_time"))
        context = (state.get("session_id"), state.get("character_guid"), state.get("map_id"), state.get("phase"))
        if context != self.context:
            self.history.clear()
            self.orientation.clear()
            self.models.clear()
            self.context = context
        facing = number(state.get("orientation"))
        if now is not None and facing is not None and (
                not self.orientation or now > self.orientation[-1][0]):
            self.orientation.append((now, facing))
        camera = state.get("camera_state") or {}
        evidence = camera.get("camera_motion_evidence") or {}
        rotation = str(evidence.get("kind") or "").upper() in {"ROTATION", "LEFT_ROTATION", "RIGHT_ROTATION"}
        turning = (self._turning(now) or rotation and (number(evidence.get("confidence")) or 0.) >= .45
                   or camera.get("zoom_change") is True)
        if turning:
            self.history.clear()             # do not extrapolate a camera turn as NPC travel
            self.models.clear()
        newest = None
        for item in state.get("visual_candidates") or ():
            if not isinstance(item, dict) or item.get("source") != "WORLD3D":
                continue
            track, at = item.get("track_id"), number(item.get("observed_at"))
            x, y = number(item.get("x")), number(item.get("y"))
            if track is None or None in (at, x, y):
                continue
            if (any(not math.isfinite(v) for v in (at, x, y))
                    or now is not None and not 0 <= now-at <= .45
                    or item.get("coasting") or str(item.get("lifecycle") or "ACTIVE").upper()
                    in {"LOST_TEMPORARY", "LOST", "OCCLUDED", "EXPIRED"}):
                item.pop("screen_velocity", None)
                item.pop("screen_motion", None)
                self.history.pop(str(track), None)
                self.models.pop(str(track), None)
                continue
            samples = self.history.setdefault(str(track), deque(maxlen=12))
            if not samples or at > samples[-1][0]:
                if samples and (at-samples[-1][0] > FORGET_SECONDS
                                or math.hypot(x-samples[-1][1], y-samples[-1][2]) > .25):
                    samples.clear()         # discontinuity is not a fast walking NPC
                samples.append((at, x, y))
            newest = at if newest is None else max(newest, at)
            velocity = None if turning else self._velocity(samples)
            if velocity is not None:
                item["screen_velocity"] = {"x": velocity[0], "y": velocity[1]}
                model = {"sampled_at": at, "span": at-samples[0][0], "samples": len(samples),
                         "model": "BOUNDED_SCREEN_VELOCITY", "identity_proof": False}
                item["screen_motion"] = model
                self.models[str(track)] = {**model, "vx": velocity[0], "vy": velocity[1]}
            else:
                item.pop("screen_velocity", None)
                item.pop("screen_motion", None)
                self.models.pop(str(track), None)
        if newest is not None:
            for track in [key for key, samples in self.history.items()
                          if newest - samples[-1][0] > FORGET_SECONDS]:
                del self.history[track]
                self.models.pop(track, None)
        while len(self.history) > 256:
            oldest = min(self.history, key=lambda key: self.history[key][-1][0])
            self.history.pop(oldest)
            self.models.pop(oldest, None)

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
        times = [sample[0]-last[0] for sample in window]
        mean = sum(times)/len(times)
        variance = sum((t-mean)**2 for t in times)
        if variance <= 1e-12:
            return None
        means = [sum(sample[axis] for sample in window)/len(window) for axis in (1, 2)]
        velocity = tuple(sum((t-mean)*(sample[axis]-average)
                             for t, sample in zip(times, window))/variance
                         for axis, average in zip((1, 2), means))
        residual = max(math.hypot(sample[1]-(means[0]+velocity[0]*(t-mean)),
                                 sample[2]-(means[1]+velocity[1]*(t-mean)))
                       for t, sample in zip(times, window))
        # Reversal, erratic association or a turn must not predict a second
        # NPC's box. Rebuild from fresh motion instead of forcing a lead.
        if residual > .015:
            return None
        if len(window) >= 3:
            dt = last[0]-window[-2][0]
            recent = ((last[1]-window[-2][1])/dt, (last[2]-window[-2][2])/dt) if dt > 0 else (0., 0.)
            if sum(a*b for a, b in zip(recent, velocity)) < -.001:
                return None
        return velocity

    def snapshot(self, track_id=None):
        return {"implementation": "bounded-target-motion-v1", "tracked": len(self.history),
                "target_track_id": track_id, "prediction": dict(self.models.get(str(track_id)) or {})}


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
    if not all(math.isfinite(v) for v in (x0, y0, vx, vy, at, now)) or not 0 <= now-at <= .5:
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
