"""Typed search capability/context/result contract (V4-036).

``SearchSkill`` (search.py) already delegates the mechanical camera-sweep /
scan / visual-servo loop to ``SeekVisualCueController``. This module adds
the spec's missing named surface -- the four supported capabilities, the
``SearchContext`` coverage record, and the four typed result outcomes --
plus a bounded coverage tracker so a caller can enforce "do not spin 360
degrees forever" without re-deriving that budget logic ad hoc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SearchCapability(StrEnum):
    SEARCH_LOCAL_ENTITY = "SEARCH_LOCAL_ENTITY"
    SEARCH_LOCAL_OBJECT = "SEARCH_LOCAL_OBJECT"
    SEARCH_ENTRANCE = "SEARCH_ENTRANCE"
    REACQUIRE_TARGET = "REACQUIRE_TARGET"


class SearchOutcome(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND_WITHIN_BUDGET = "NOT_FOUND_WITHIN_BUDGET"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    BLOCKED = "BLOCKED"


@dataclass
class SearchContext:
    """One bounded search attempt's coverage state.

    ``sectors_scanned`` and ``visited_search_points`` accumulate as the
    caller performs its own camera sweep/move/scan loop; this object only
    tracks the budget, it never issues camera or movement commands itself.
    """

    origin: tuple[float, float] | None
    radius: float
    query: str
    scan_budget: int
    time_budget_seconds: float
    sectors_scanned: list[str] = field(default_factory=list)
    visited_search_points: list[tuple[float, float]] = field(default_factory=list)
    started_at: float = 0.0

    def record_sector_scanned(self, sector: str) -> None:
        if sector not in self.sectors_scanned:
            self.sectors_scanned.append(sector)

    def record_search_point_visited(self, point: tuple[float, float]) -> None:
        self.visited_search_points.append(point)

    def scans_remaining(self) -> int:
        return max(0, self.scan_budget - len(self.sectors_scanned))

    def is_budget_exhausted(self, *, now: float) -> bool:
        """Return whether either the scan or the time budget has run out.

        This is what actually prevents spinning 360 degrees forever: once
        either budget is spent, the caller must stop scanning and report
        ``NOT_FOUND_WITHIN_BUDGET`` rather than continuing indefinitely.
        """
        if self.scans_remaining() <= 0:
            return True
        elapsed = max(0.0, now - self.started_at)
        return elapsed >= self.time_budget_seconds
