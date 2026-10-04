"""Heuristic re-tagging of already-tracked World3D candidates as obstacles.

Audit 2026-09-14: movement_controller.py, navigation.py and
visual_approach.py all already filter `visual_candidates` for
`detector_kind == "obstacle_candidate"` (stuck-evidence aggregation,
blocked-corridor memory, approach-abort checks) -- but nothing in the
vision pipeline (world3d/probe.py, normalization.py, local_world.py) ever
sets that label; `probe.py` hardcodes `"obstacles": []`. That whole
consumer side was dead code in practice. This reuses signals World3D
already computes for every tracked candidate -- no new detector, no new
CV -- to make it real: a candidate counts as an obstacle proxy when it is
static relative to camera-compensated motion (`static_scene_score`, from
WorldCandidateTracker), fills a meaningful share of the frame height (close,
not a distant speck), sits in the lower/near part of the view (the ground
path, not the sky), and has been tracked continuously for a few frames.
"""
from __future__ import annotations

from .models import number

STATIC_SCORE_MIN = .18
HEIGHT_FRACTION_MIN = .18
MAX_SCREEN_Y = .6
MIN_STABLE_FRAMES = 3


def _looks_like_obstacle(item: dict) -> bool:
    appearance = item.get("appearance") or {}
    static_score = number(appearance.get("static_scene_score")) or 0.
    height_fraction = number(item.get("bbox_height_fraction")) or 0.
    y = number(item.get("y"))
    stable = number(item.get("stable_frames")) or 0.
    return (static_score >= STATIC_SCORE_MIN and height_fraction >= HEIGHT_FRACTION_MIN
            and y is not None and y <= MAX_SCREEN_Y and stable >= MIN_STABLE_FRAMES)


def tag_obstacle_candidates(items: list[dict]) -> list[dict]:
    """Return `items` with `detector_kind` added where the heuristic fires.

    Never mutates the input; qualifying items are replaced with a shallow
    copy carrying the extra key. `kind` (e.g. "unknown_subject_candidate")
    is left untouched, since other consumers still rely on its real value.
    """
    return [{**item, "detector_kind": "obstacle_candidate"} if _looks_like_obstacle(item) else item
            for item in items]


def obstacle_bearing(state: dict) -> float | None:
    """Average normalized screen-x (0=left, 1=right) of tagged obstacles.

    None when nothing currently looks like an obstacle -- callers should
    fall back to their own default behavior in that case.
    """
    xs = [number(item.get("x")) for item in state.get("visual_candidates", [])
          if item.get("detector_kind") == "obstacle_candidate" and number(item.get("x")) is not None]
    return sum(xs)/len(xs) if xs else None
