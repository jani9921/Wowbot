"""Learned quest objective areas in WORLD_YARDS (user 2026-10-03).

The minimap shows the active quest's objective area as a light-blue outline;
``vision.minimap_quest_area`` finds it in minimap-local units.  This memory
converts every observation to world cells around the player and attaches it
to the unfinished quest whose API POI lies in/near that area.  Planning then
knows where the quest area really is (arrival, roaming inside its shape)
instead of assuming a circle around the POI.
"""
from __future__ import annotations

import math

from .models import number
from .planning_types import world_point
from wowbot.vision.minimap_quest_area import offsets_to_world


class QuestAreaMemory:
    CELL_YARDS = 4.
    # Measured offline 2026-10-03 at the default minimap zoom (3.58 yd/px at a
    # 44.7 px disc radius).  The addon's C_Minimap.GetViewRadius() wins.
    DEFAULT_VIEW_RADIUS_YARDS = 160.
    ASSOCIATION_YARDS = 40.
    MAX_CELLS_PER_QUEST = 8000

    def __init__(self) -> None:
        self.cells: dict[str, set[tuple[int, int]]] = {}
        # Instance the cells were learned in (issue #96): the same X/Y in
        # another instance is a different place.
        self.instances: dict[str, str] = {}
        self.closed_seen: dict[str, bool] = {}
        self._last_observed_at = None

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return (int(math.floor(x / self.CELL_YARDS)), int(math.floor(y / self.CELL_YARDS)))

    def _centre(self, cell: tuple[int, int]) -> tuple[float, float]:
        return ((cell[0]+.5)*self.CELL_YARDS, (cell[1]+.5)*self.CELL_YARDS)

    @staticmethod
    def _candidate(state: dict) -> dict | None:
        return next((item for item in state.get("visual_candidates") or ()
                     if isinstance(item, dict) and item.get("kind") == "minimap_quest_area"
                     and isinstance(item.get("quest_area"), dict)), None)

    @staticmethod
    def _quest_pois(state: dict) -> list[tuple[str, float, float]]:
        unfinished = {str(quest.get("quest_id")) for quest in state.get("active_quests") or ()
                      if isinstance(quest, dict) and quest.get("is_complete") is not True}
        result = []
        for location in state.get("quest_locations") or ():
            point = world_point(location) if isinstance(location, dict) else None
            if point is not None and str(location.get("quest_id")) in unfinished:
                result.append((str(location["quest_id"]), float(point["x"]), float(point["y"])))
        return result

    def observe(self, state: dict) -> str | None:
        """Ingest the newest minimap quest-area candidate; return its quest id."""
        candidate = self._candidate(state)
        if candidate is None or candidate.get("observed_at") == self._last_observed_at:
            return None
        self._last_observed_at = candidate.get("observed_at")
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if px is None or py is None:
            return None
        geometry = state.get("minimap_geometry") or {}
        view = (number(candidate.get("view_radius_yards"))
                or number(geometry.get("view_radius_yards")) or self.DEFAULT_VIEW_RADIUS_YARDS)
        rotate = bool(candidate.get("rotate_minimap", geometry.get("rotate_minimap")))
        area = candidate["quest_area"]
        points = offsets_to_world(area.get("offsets") or (), player_x=px, player_y=py,
                                  view_radius_yards=view, rotate=rotate,
                                  facing=number(state.get("orientation")))
        if not points:
            return None
        best = None
        for quest_id, qx, qy in self._quest_pois(state):
            distance = min(math.hypot(x-qx, y-qy) for x, y in points)
            if distance <= self.ASSOCIATION_YARDS and (best is None or distance < best[0]):
                best = (distance, quest_id)
        if best is None:
            return None
        quest_id = best[1]
        instance = position.get("instance_id")
        if instance is not None:
            if self.instances.get(quest_id) not in (None, str(instance)):
                # Re-learn in the new instance instead of merging two places.
                self.cells.pop(quest_id, None)
                self.closed_seen.pop(quest_id, None)
            self.instances[quest_id] = str(instance)
        cells = self.cells.setdefault(quest_id, set())
        for x, y in points:
            if len(cells) >= self.MAX_CELLS_PER_QUEST:
                break
            cells.add(self._cell(x, y))
        if area.get("closed"):
            self.closed_seen[quest_id] = True
        return quest_id

    def contains(self, quest_id, x: float, y: float, instance_id=None) -> bool:
        cells = self.cells.get(str(quest_id))
        if not cells:
            return False
        learned = self.instances.get(str(quest_id))
        if instance_id is not None and learned is not None and learned != str(instance_id):
            return False
        cx, cy = self._cell(x, y)
        return any((cx+dx, cy+dy) in cells for dx in (-1, 0, 1) for dy in (-1, 0, 1))

    def coverage_points(self, quest_id, maximum: int = 12) -> list[dict]:
        """Spread-out cell centres of the learned area (farthest-point sampling)."""
        cells = self.cells.get(str(quest_id))
        if not cells or not self.closed_seen.get(str(quest_id)):
            return []
        centres = [self._centre(cell) for cell in sorted(cells)]
        mx = sum(x for x, _ in centres)/len(centres)
        my = sum(y for _, y in centres)/len(centres)
        chosen = [min(centres, key=lambda point: math.hypot(point[0]-mx, point[1]-my))]
        while len(chosen) < min(maximum, len(centres)):
            far = max(centres, key=lambda point: min(math.hypot(point[0]-c[0], point[1]-c[1])
                                                     for c in chosen))
            if min(math.hypot(far[0]-c[0], far[1]-c[1]) for c in chosen) < self.CELL_YARDS*2:
                break
            chosen.append(far)
        return [{"x": x, "y": y} for x, y in chosen]

    def extent(self, quest_id) -> tuple[float, float, float] | None:
        """(centre x, centre y, radius) of the learned area."""
        cells = self.cells.get(str(quest_id))
        if not cells:
            return None
        centres = [self._centre(cell) for cell in cells]
        mx = sum(x for x, _ in centres)/len(centres)
        my = sum(y for _, y in centres)/len(centres)
        return mx, my, max(math.hypot(x-mx, y-my) for x, y in centres) + self.CELL_YARDS
