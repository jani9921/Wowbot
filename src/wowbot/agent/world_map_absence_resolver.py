"""World map marker-absence resolution procedure (V4-018 section 18.1).

"Absence of a marker at the current map level does NOT prove no marker
exists." This adds the missing named 5-step procedure as a small typed
step resolver: verify tracked quest -> inspect current level -> step out
to parent zone -> inspect parent zone -> zoom into target zone if found.
It never invents an inspection result -- every ``bool | None`` input stays
``None`` until the caller has actually performed that inspection.
Complements the existing zoom-in retry logic in
``agent/visual_inspection_planning.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MapAbsenceStep(StrEnum):
    VERIFY_TRACKED_QUEST = "VERIFY_TRACKED_QUEST"
    INSPECT_CURRENT_LEVEL = "INSPECT_CURRENT_LEVEL"
    STEP_OUT_TO_PARENT = "STEP_OUT_TO_PARENT"
    INSPECT_PARENT_ZONE = "INSPECT_PARENT_ZONE"
    ZOOM_INTO_TARGET_ZONE = "ZOOM_INTO_TARGET_ZONE"
    DONE_FOUND = "DONE_FOUND"
    DONE_NOT_FOUND = "DONE_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class MapAbsenceDirective:
    step: MapAbsenceStep
    target_zone: str | None = None


class WorldMapAbsenceResolver:
    """Bounded step-out procedure for a marker absent at the current map level."""

    def __init__(self, *, max_parent_hops: int = 2) -> None:
        self.max_parent_hops = max(0, int(max_parent_hops))

    def next_step(self, *, tracked_quest_confirmed: bool,
                 marker_found_at_current_level: bool | None,
                 parent_hops_taken: int,
                 marker_found_at_parent_level: bool | None,
                 parent_zone: str | None) -> MapAbsenceDirective:
        if not tracked_quest_confirmed:
            return MapAbsenceDirective(MapAbsenceStep.VERIFY_TRACKED_QUEST)
        if marker_found_at_current_level is None:
            return MapAbsenceDirective(MapAbsenceStep.INSPECT_CURRENT_LEVEL)
        if marker_found_at_current_level:
            return MapAbsenceDirective(MapAbsenceStep.DONE_FOUND)
        if parent_zone is None or parent_hops_taken >= self.max_parent_hops:
            return MapAbsenceDirective(MapAbsenceStep.DONE_NOT_FOUND)
        if parent_hops_taken == 0:
            return MapAbsenceDirective(MapAbsenceStep.STEP_OUT_TO_PARENT, parent_zone)
        if marker_found_at_parent_level is None:
            return MapAbsenceDirective(MapAbsenceStep.INSPECT_PARENT_ZONE, parent_zone)
        if marker_found_at_parent_level:
            return MapAbsenceDirective(MapAbsenceStep.ZOOM_INTO_TARGET_ZONE, parent_zone)
        return MapAbsenceDirective(MapAbsenceStep.DONE_NOT_FOUND)
