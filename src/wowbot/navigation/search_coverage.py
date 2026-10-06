"""Deterministic, bounded region-coverage planner with no input authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass
class SearchCell:
    cell_id: str
    x: float
    y: float
    z: float | None = None
    visits: int = 0
    detections: int = 0
    last_visited: float | None = None


class SearchCoveragePlanner:
    def __init__(self) -> None:
        self._regions: dict[str, dict] = {}

    def reset(self) -> None:
        self._regions.clear()

    def begin(self, region_id: str, region: dict, *, grid: int = 3) -> None:
        key = str(region_id)
        if key in self._regions:
            return
        x, y = float(region["x"]), float(region["y"])
        world_space = region.get("coordinate_space") == "WORLD_YARDS"
        radius = max(2.0 if world_space else .001,
                     float(region.get("radius") or region.get("search_radius")
                           or (18.0 if world_space else .012)))
        cells = []
        explicit = region.get("coverage_points")
        if isinstance(explicit, list) and explicit:
            for index, point in enumerate(explicit[:25]):
                try:
                    px, py = float(point["x"]), float(point["y"])
                except (KeyError, TypeError, ValueError):
                    continue
                if math.isfinite(px) and math.isfinite(py):
                    pz = point.get("z")
                    pz = float(pz) if isinstance(pz, (int, float)) and math.isfinite(pz) else None
                    cells.append(SearchCell(f"{key}:explicit:{index}", px, py, pz))
        if not cells:
            for row in range(grid):
                for column in range(grid):
                    dx = ((column/(grid-1))-.5)*2*radius if grid > 1 else 0.
                    dy = ((row/(grid-1))-.5)*2*radius if grid > 1 else 0.
                    # A circular region cannot legitimately contain the square's
                    # four corners.  Clamp coverage to an inscribed circle so a
                    # search never walks outside its own evidence envelope.
                    distance = math.hypot(dx, dy)
                    if distance > radius:
                        scale = radius / distance
                        dx, dy = dx * scale, dy * scale
                    rz = region.get("z")
                    rz = float(rz) if isinstance(rz, (int, float)) and math.isfinite(rz) else None
                    cells.append(SearchCell(f"{key}:{row}:{column}", x+dx, y+dy, rz))
        self._regions[key] = {"region": dict(region), "radius": radius,
                              "cells": cells, "completed": False}

    def observe(self, region_id: str, *, player_x: float | None, player_y: float | None,
                target_detected: bool, now: float, player_z: float | None = None) -> None:
        data = self._regions.get(str(region_id))
        if data is None:
            return
        if target_detected:
            data["completed"] = True
            return
        if player_x is None or player_y is None:
            return
        threshold = data["radius"] / 4.
        for cell in data["cells"]:
            # A cave floor directly below a visited surface point is not
            # covered.  Unknown own Z cannot certify a Z-labelled cell.
            if (cell.z is not None and
                    (player_z is None or abs(player_z-cell.z) > 5.)):
                continue
            if math.hypot(player_x-cell.x, player_y-cell.y) <= threshold:
                cell.visits += 1
                cell.last_visited = float(now)

    def mark_visited(self, region_id: str, cell_id: str, now: float) -> None:
        """Retire a cell that could not be reached (route failure/timeout)."""
        data = self._regions.get(str(region_id))
        if data is None:
            return
        for cell in data["cells"]:
            if cell.cell_id == cell_id:
                cell.visits = max(1, cell.visits)
                cell.last_visited = float(now)

    def completed(self, region_id: str) -> bool | None:
        data = self._regions.get(str(region_id))
        if data is None:
            return None
        return bool(data["completed"] or all(cell.visits >= 1 for cell in data["cells"]))

    def next_waypoint(self, region_id: str, *, player_x: float | None, player_y: float | None,
                      player_z: float | None = None) -> dict | None:
        data = self._regions.get(str(region_id))
        if data is None or data["completed"]:
            return None
        def rank(cell: SearchCell):
            distance = (math.hypot((player_x if player_x is not None else cell.x)-cell.x,
                                   (player_y if player_y is not None else cell.y)-cell.y)
                        if player_x is not None and player_y is not None else 0.)
            if cell.z is not None and player_z is not None:
                distance = math.hypot(distance, cell.z-player_z)
            return cell.visits, distance, cell.cell_id
        chosen = min(data["cells"], key=rank)
        if chosen.visits >= 1:
            data["completed"] = True
            return None
        region = data["region"]
        result = {"x": chosen.x, "y": chosen.y, "map_id": region.get("map_id"),
                "search_region_id": str(region_id), "search_cell_id": chosen.cell_id,
                "purpose": "SEARCH_REGION_COVERAGE"}
        if chosen.z is not None:
            result.update({"z": chosen.z, "z_known": True, "z_estimated": True,
                           "z_source": "NAVMESH_SEARCH_CELL", "layer_z": chosen.z})
        if region.get("coordinate_space") == "WORLD_YARDS":
            result.update({
                "coordinate_space": "WORLD_YARDS",
                "instance_id": region.get("instance_id"),
                "world_map_id": region.get("instance_id"),
                "require_navmesh": True,
                "stop_distance": min(3.5, max(1.5, data["radius"] / 6.)),
            })
        return result

    def snapshot(self) -> dict:
        return {key: {"region": dict(value["region"]), "completed": value["completed"],
                      "cells": [asdict(cell) for cell in value["cells"]]}
                for key, value in self._regions.items()}
