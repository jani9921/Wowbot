"""Flight route: around tall terrain like walking, or over it when faster.

User 2026-10-20: "kitudja kerülni jobbról balról is, nem kell neki fölé
repülni, ugyanúgy mint gyalog, csak kevesebb elakadás" and "de hát fölé is
repülhet, ha úgy gyorsabb".  In the air the only obstacles are terrain and
models that reach the cruise height, and both are known offline: TrinityCore
MAPS (terrain and liquid heights) and VMAPS (buildings, bridges, trees).

Each candidate cruise height gets a grid A* at that height (weighted
SEARCH_WEIGHT for speed, so a detour may be up to that much longer than the
shortest one): a cell is
blocked when anything there rises to within CLEARANCE_YARDS of it, or when
its height is unknown (fail closed), and one cell of margin is kept around
blocked cells.  The search uses MAPS only; models are checked along the
string-pulled legs and a hit blocks those cells and re-plans.  Candidates
are scored as flight time in level-flight yards: horizontal length plus
CLIMB_COST per yard climbed and DESCENT_COST per yard descended.  Heights
are a low one above the higher endpoint, a few steps above it, and the one
that clears everything on the straight line; the cheapest wins, and a
search is cut off as soon as it can no longer beat the best so far.

Take-off and landing are vertical: nothing (a roof, a cave ceiling) may lie
between the ground and the cruise height above the start or the target.
Planning only: no input. ``flight_travel`` adapts these ordered bends for
the common NavigationService and existing Steady/Skyriding controllers.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

CELL_YARDS = 8.
CRUISE_ABOVE_YARDS = 30.     # lowest cruise height above the higher endpoint
CLEARANCE_YARDS = 10.        # nothing may reach this close below the cruise height
CLIMB_STEPS = (0., 40., 80., 160.)
CLIMB_COST = 2.              # one yard up costs two yards of level flight
DESCENT_COST = 1.
LINE_STEP_YARDS = 4.
SEARCH_MARGIN_YARDS = 250.   # sideways room around the start-target box
MAX_EXPANSIONS = 40_000      # per cruise height, all re-plans together
SEARCH_WEIGHT = 1.3
MODEL_REPLANS = 6
NO_LIQUID_BELOW = -1000.     # MAPS writes -2000 for "no liquid surface"


class MapHeightSource:
    """Heights at (x, y) from MAPS, with VMAPS models when configured."""

    def __init__(self, terrain, vmaps, instance_id: int):
        self.terrain, self.vmaps, self.instance_id = terrain, vmaps, int(instance_id)

    def _sample(self, x: float, y: float):
        return self.terrain.sample(self.instance_id, x, y) if self.terrain is not None else None

    def reaches(self, x: float, y: float, ceiling: float) -> bool | None:
        """Terrain or liquid at/above ``ceiling``; None when nothing is known."""
        sample = self._sample(x, y)
        if sample is None:
            return None
        if sample.terrain_z is not None and not sample.is_hole and sample.terrain_z >= ceiling:
            return True
        if sample.has_liquid and NO_LIQUID_BELOW < sample.liquid_z and sample.liquid_z >= ceiling:
            return True
        if sample.is_hole and self.vmaps is None:
            return None       # a model stands there and its height is unknown
        return False

    def model_reaches(self, x: float, y: float, ceiling: float) -> bool:
        return bool(self.vmaps is not None
                    and self.vmaps.surfaces_above(self.instance_id, x, y, ceiling))

    def top(self, x: float, y: float) -> float | None:
        """Highest terrain, liquid or model surface; None when unknown."""
        sample = self._sample(x, y)
        if sample is None:
            return None
        heights = []
        if sample.terrain_z is not None and not sample.is_hole:
            heights.append(sample.terrain_z)
        if sample.has_liquid and sample.liquid_z > NO_LIQUID_BELOW:
            heights.append(sample.liquid_z)
        if self.vmaps is not None:
            heights.extend(self.vmaps.surfaces_at(self.instance_id, x, y)[:1])
        elif sample.is_hole:
            return None
        return max(heights) if heights else None

    def covered(self, x: float, y: float, low: float, high: float) -> bool:
        """A roof or ceiling between ``low`` and ``high`` above this point."""
        return bool(self.vmaps is not None
                    and self.vmaps.surfaces_at(self.instance_id, x, y, top=high, bottom=low))


@dataclass(frozen=True)
class FlightRoute:
    cruise_z: float
    waypoints: tuple[tuple[float, float, float], ...]
    horizontal_yards: float
    cost: float
    expanded: int


@dataclass
class FlightPlanResult:
    route: FlightRoute | None
    reason: str
    attempts: list[dict] = field(default_factory=list)


class _Grid:
    def __init__(self, source, ceiling: float, origin: tuple[float, float],
                 size: tuple[int, int]) -> None:
        self.source, self.ceiling = source, ceiling
        self.ox, self.oy = origin
        self.width, self.height = size
        self.margin = max(1, int(math.ceil(getattr(source, 'margin_yards', CELL_YARDS)/CELL_YARDS)))
        self._raw: dict[tuple[int, int], bool] = {}
        self._model: dict[tuple[int, int], bool] = {}
        self._free: dict[tuple[int, int], bool] = {}
        self.endpoints: set[tuple[int, int]] = set()   # take-off / landing: no margin

    def cell(self, x: float, y: float) -> tuple[int, int]:
        return int(round((x-self.ox)/CELL_YARDS)), int(round((y-self.oy)/CELL_YARDS))

    def centre(self, cell: tuple[int, int]) -> tuple[float, float]:
        return self.ox + cell[0]*CELL_YARDS, self.oy + cell[1]*CELL_YARDS

    def inside(self, cell: tuple[int, int]) -> bool:
        return 0 <= cell[0] < self.width and 0 <= cell[1] < self.height

    def raw_blocked(self, cell: tuple[int, int]) -> bool:
        value = self._raw.get(cell)
        if value is None:
            value = self._raw[cell] = (
                self.source.reaches(*self.centre(cell), self.ceiling) is not False
                or self._model.get(cell, False))
        return value

    def check_models(self, cell: tuple[int, int]) -> bool:
        """Query VMAPS once for a cell and its margin; True if any model hit."""
        hit = False
        for dx in range(-self.margin, self.margin+1):
            for dy in range(-self.margin, self.margin+1):
                near = (cell[0]+dx, cell[1]+dy)
                if near not in self._model:
                    self._model[near] = self.source.model_reaches(*self.centre(near), self.ceiling)
                    if self._model[near]:
                        self._raw[near] = True
                        for fx in range(-self.margin, self.margin+1):
                            for fy in range(-self.margin, self.margin+1):
                                self._free.pop((near[0]+fx, near[1]+fy), None)
                        hit = True
        return hit

    def free(self, cell: tuple[int, int]) -> bool:
        value = self._free.get(cell)
        if value is None:
            if cell in self.endpoints:
                value = not self.raw_blocked(cell)
            else:
                value = self.inside(cell) and not any(
                    self.raw_blocked((cell[0]+dx, cell[1]+dy))
                    for dx in range(-self.margin, self.margin+1) for dy in range(-self.margin, self.margin+1))
            self._free[cell] = value
        return value

    def line_cells(self, a: tuple[float, float], b: tuple[float, float]) -> list[tuple[int, int]]:
        steps = max(1, int(math.ceil(math.dist(a, b) / (CELL_YARDS/2))))
        cells: list[tuple[int, int]] = []
        for i in range(steps+1):
            cell = self.cell(a[0] + (b[0]-a[0])*i/steps, a[1] + (b[1]-a[1])*i/steps)
            if not cells or cells[-1] != cell:
                cells.append(cell)
        return cells

    def line_free(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        return all(self.free(cell) for cell in self.line_cells(a, b))


def _a_star(grid: _Grid, start: tuple[int, int], goal: tuple[int, int], cap: float,
            budget: int) -> tuple[list[tuple[int, int]] | None, int, str]:
    """8-connected cell path no longer than ``cap`` cells, or None.

    Ordered by a SEARCH_WEIGHT-inflated estimate (a route at most that much
    longer than the shortest, found far faster); ``cap`` prunes with the
    true lower bound, so a route that could still beat the best is kept.
    """
    moves = [(dx, dy, math.hypot(dx, dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
    frontier = [(SEARCH_WEIGHT*math.dist(start, goal), 0., start)]
    best, parent, expanded, pruned = {start: 0.}, {start: None}, 0, False
    while frontier:
        _, cost, cell = heapq.heappop(frontier)
        if cell == goal:
            path = []
            while cell is not None:
                path.append(cell)
                cell = parent[cell]
            return path[::-1], expanded, "routed"
        if cost > best.get(cell, math.inf):
            continue
        expanded += 1
        if expanded > budget:
            return None, expanded, "search_limit"
        for dx, dy, step in moves:
            nxt = (cell[0]+dx, cell[1]+dy)
            new = cost + step
            if new >= best.get(nxt, math.inf) or not grid.free(nxt):
                continue
            remaining = math.dist(nxt, goal)
            if new + remaining >= cap:
                pruned = True
                continue
            best[nxt], parent[nxt] = new, cell
            heapq.heappush(frontier, (new + SEARCH_WEIGHT*remaining, new, nxt))
    return None, expanded, "slower_than_best" if pruned else "no_route"


def _pull(grid: _Grid, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Keep only the turns: skip every point the line of flight clears."""
    result, index = [points[0]], 0
    while index < len(points)-1:
        far = index+1
        while far < len(points)-1 and grid.line_free(points[index], points[far+1]):
            far += 1
        result.append(points[far])
        index = far
    return result


def _straight_line_top(source, start: tuple[float, float], target: tuple[float, float]
                       ) -> float | None:
    """Highest surface under the direct line and one cell to either side."""
    length = math.dist(start, target)
    steps = max(1, int(math.ceil(length / LINE_STEP_YARDS)))
    nx, ny = ((start[1]-target[1])/length, (target[0]-start[0])/length) if length else (0., 0.)
    highest = -math.inf
    for i in range(steps+1):
        x = start[0] + (target[0]-start[0])*i/steps
        y = start[1] + (target[1]-start[1])*i/steps
        for side in (-CELL_YARDS, 0., CELL_YARDS):
            top = source.top(x + nx*side, y + ny*side)
            if top is None:
                return None
            highest = max(highest, top)
    return highest


def _route_at(source, cruise: float, start, target, origin, size, cap_yards: float
              ) -> tuple[list[tuple[float, float]] | None, dict]:
    sx, sy, sz = start
    tx, ty, tz = target
    if source.covered(sx, sy, sz + 3., cruise):
        return None, {"reason": "start_covered"}
    if source.covered(tx, ty, tz + 3., cruise):
        return None, {"reason": "landing_covered"}
    grid = _Grid(source, cruise - CLEARANCE_YARDS, origin, size)
    first, last = grid.cell(sx, sy), grid.cell(tx, ty)
    if grid.raw_blocked(first) or grid.raw_blocked(last):
        return None, {"reason": "endpoint_blocked"}
    grid.endpoints = {first, last}
    expanded = 0
    for _ in range(MODEL_REPLANS):
        cells, used, reason = _a_star(grid, first, last, cap_yards / CELL_YARDS,
                                      MAX_EXPANSIONS - expanded)
        expanded += used
        if cells is None:
            return None, {"reason": reason, "expanded": expanded}
        legs = _pull(grid, [(sx, sy), *(grid.centre(c) for c in cells[1:-1]), (tx, ty)])
        hit = False
        for a, b in zip(legs, legs[1:]):
            for cell in grid.line_cells(a, b):
                hit = grid.check_models(cell) or hit
        if not hit:
            return legs, {"reason": "routed", "expanded": expanded}
    return None, {"reason": "models_in_the_way", "expanded": expanded}


def plan_flight(source, start: tuple[float, float, float],
                target: tuple[float, float, float]) -> FlightPlanResult:
    """Take-off above ``start``, fly the fastest way, land on ``target``."""
    start = tuple(map(float, start))
    target = tuple(map(float, target))
    (sx, sy, sz), (tx, ty, tz) = start, target
    straight = math.dist((sx, sy), (tx, ty))
    base = max(sz, tz) + CRUISE_ABOVE_YARDS
    heights = {round(base + climb, 1) for climb in CLIMB_STEPS}
    line_top = _straight_line_top(source, (sx, sy), (tx, ty))
    if line_top is not None and line_top + CLEARANCE_YARDS + 2. > base:
        heights.add(round(line_top + CLEARANCE_YARDS + 2., 1))
    margin = max(SEARCH_MARGIN_YARDS, .5*straight)
    origin = (min(sx, tx) - margin, min(sy, ty) - margin)
    size = (int((abs(tx-sx) + 2*margin)/CELL_YARDS) + 2, int((abs(ty-sy) + 2*margin)/CELL_YARDS) + 2)

    def vertical(cruise: float) -> float:
        return CLIMB_COST*max(0., cruise-sz) + DESCENT_COST*max(0., cruise-tz)

    best: FlightRoute | None = None
    attempts: list[dict] = []
    # Over-the-top first: usually a straight line, and its cost bounds the
    # detours the lower heights may search.
    for cruise in sorted(heights, key=lambda h: (h != max(heights), h)):
        cap = math.inf if best is None else best.cost - vertical(cruise)
        if cap <= straight:
            attempts.append({"cruise_z": cruise, "reason": "slower_than_best"})
            continue
        legs, info = _route_at(source, cruise, start, target, origin, size, cap)
        attempts.append({"cruise_z": cruise, **info})
        if legs is None:
            continue
        horizontal = sum(math.dist(a, b) for a, b in zip(legs, legs[1:]))
        cost = horizontal + vertical(cruise)
        if best is None or cost < best.cost:
            waypoints = ((sx, sy, cruise), *((x, y, cruise) for x, y in legs[1:]), (tx, ty, tz))
            best = FlightRoute(cruise, waypoints, horizontal, cost, info.get("expanded", 0))
    if best is not None:
        return FlightPlanResult(best, "routed", attempts)
    return FlightPlanResult(None, attempts[-1]["reason"] if attempts else "no_attempt", attempts)
