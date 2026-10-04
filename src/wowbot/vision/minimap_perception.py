"""Minimap detector, temporal association, and evidence resolution seams."""
from __future__ import annotations

import math
from typing import Any

from .adapters.minimap import detect_minimap


class MinimapDetector:
    def detect(self, buffer: bytes, width: int, height: int, **kwargs):
        return detect_minimap(buffer, width, height, **kwargs)


class MinimapTracker:
    """Uses the shared visual track authority; it never invents another ID."""

    def __init__(self, track_manager) -> None:
        self.track_manager = track_manager

    def update_markers(self, markers: list[dict], observed_at: float) -> list[dict]:
        return self.track_manager.update("MINIMAP_CV", markers, observed_at)

    def associate_across_frames(self, markers: list[dict], observed_at: float) -> list[dict]:
        return self.update_markers(markers, observed_at)

    @staticmethod
    def trend(marker: dict) -> str:
        positions = marker.get("position_history") or marker.get("positions") or []
        if len(positions) < 2:
            return "UNKNOWN"
        def distance(value):
            if isinstance(value, dict):
                local = value.get("local_position") or value
                return float(local.get("distance", math.inf))
            return math.inf
        first, last = distance(positions[0]), distance(positions[-1])
        if not math.isfinite(first) or not math.isfinite(last):
            return "UNKNOWN"
        return "APPROACHING" if last < first else "RECEDING" if last > first else "STABLE"

    def invalidate_on_context_change(self) -> None:
        # Reset the shared authority, exactly as a full capture-context change
        # already does.  There is intentionally no private marker identity.
        self.track_manager.reset()


class MinimapResolver:
    @staticmethod
    def _best(markers: list[dict], labels: tuple[str, ...]) -> dict | None:
        candidates = [m for m in markers
                      if any(wanted in str(actual)
                             for actual in (m.get("candidate_labels") or ())
                             for wanted in labels)]
        return max(candidates, key=lambda m: float(m.get("confidence", 0)), default=None)

    def best_quest_cue(self, markers: list[dict], objective=None) -> dict | None:
        return self._best(markers, ("quest", "objective", "direction_arrow_like"))

    def best_turnin_cue(self, markers: list[dict], quest=None) -> dict | None:
        return self._best(markers, ("turn_in", "question_mark_like"))

    @staticmethod
    def local_direction(cue: dict | None) -> dict | None:
        return dict(cue.get("local_position") or {}) if cue else None

    @staticmethod
    def cue_progress(cue: dict | None) -> str:
        return MinimapTracker.trend(cue or {})

    @staticmethod
    def cue_disappeared_interpretation(*, recent: bool, context_changed: bool) -> str:
        if context_changed:
            return "CONTEXT_INVALIDATED"
        return "TEMPORARILY_OCCLUDED" if recent else "UNRESOLVED_ABSENCE"
