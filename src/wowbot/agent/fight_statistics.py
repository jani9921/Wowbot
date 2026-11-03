"""This character's own fight lengths (design spec 31.4).

The TravelCostModel prices a hostile on the route by the expected fight
seconds; a strong character clears a mob faster than a weak one.  Only
verified won fights (COMBAT/DEFEND SUCCESS) are counted, bounded and per
WorldModel (a new session starts empty).  Fewer than MIN_FIGHTS keeps the
declared default.
"""
from __future__ import annotations

from collections import deque
from statistics import median

MIN_FIGHTS = 3
WINDOW = 20


def record_fight(world, seconds) -> None:
    if type(seconds) not in {int, float} or not 0 < seconds < 600:
        return
    world.__dict__.setdefault("fight_durations", deque(maxlen=WINDOW)).append(float(seconds))


def expected_fight_seconds(world) -> float | None:
    values = world.__dict__.get("fight_durations") or ()
    return round(median(values), 1) if len(values) >= MIN_FIGHTS else None
