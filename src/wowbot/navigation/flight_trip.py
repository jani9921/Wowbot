"""Walk to open sky, fly, walk from open sky: one trip to a ground target.

User 2026-10-20 ("joo", after the comparison with PixelBuddy's remote
PlanLanding service): a flight needs a place to take off and land.  Take-off
and landing are vertical, so a spot under a roof, a tent, a tree or a cave
ceiling is no good -- live 2026-10-20 18:43-19:07 the character stood with a
VMAPS surface 15 yd overhead, and some quest targets are indoors.

``open_sky_spot`` keeps the point itself when nothing (VMAPS) is above it;
otherwise it tests rings of walkable points around it (MMAPS layer within
LAYER_YARDS of its height, open sky above) nearest first, and walks the
navmesh to the best few: the shortest walk wins, within MAX_WALK_YARDS and
WALK_DETOUR times the straight distance.  ``plan_trip`` chains walk, flight
(``flight_planner.plan_flight``) and walk.  Planning only: no input.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .flight_planner import FlightRoute, plan_flight

SKY_TOP = 2000.               # open sky: no model surface anywhere above
HEAD_ROOM_YARDS = 3.          # the floor itself and the character's height
RING_YARDS = (6., 10., 15., 20., 30., 40., 55., 70.)
RING_POINTS = 16
LAYER_YARDS = 15.             # a spot on another floor/terrace is not "here"
PATH_CHECKS = 8               # walk paths tried among the nearest open spots
MAX_WALK_YARDS = 120.
WALK_DETOUR = 3.


@dataclass(frozen=True)
class SkySpot:
    point: tuple[float, float, float]
    walk: tuple[tuple[float, float, float], ...]   # spot -> anchor (landing) / anchor -> spot (take-off)
    walk_yards: float
    tested: int


@dataclass
class TripPlan:
    reason: str
    take_off: SkySpot | None = None
    flight: FlightRoute | None = None
    landing: SkySpot | None = None
    attempts: list[dict] = field(default_factory=list)


def open_sky(source, x: float, y: float, z: float) -> bool:
    return not source.covered(x, y, z + HEAD_ROOM_YARDS, SKY_TOP)


def _point(x: float, y: float, z: float, instance_id: int) -> dict:
    return {"x": x, "y": y, "z": z, "z_known": True, "instance_id": instance_id}


def open_sky_spot(source, navmesh, instance_id: int, anchor: tuple[float, float, float], *,
                  landing: bool) -> SkySpot | None:
    """Nearest open-sky walkable spot connected to ``anchor`` by a walk."""
    ax, ay, az = map(float, anchor)
    if open_sky(source, ax, ay, az):
        return SkySpot((ax, ay, az), ((ax, ay, az),), 0., 0)
    candidates, tested = [], 0
    for radius in RING_YARDS:
        for index in range(RING_POINTS):
            angle = math.tau * index / RING_POINTS
            x, y = ax + radius*math.cos(angle), ay + radius*math.sin(angle)
            tested += 1
            heights = [h for h in navmesh.walkable_heights_at(instance_id, {"x": x, "y": y}, 1.5)
                       if abs(h - az) <= LAYER_YARDS]
            if not heights:
                continue
            z = min(heights, key=lambda h: abs(h - az))
            if open_sky(source, x, y, z):
                candidates.append((radius, (x, y, z)))
        if len(candidates) >= PATH_CHECKS:
            break
    best: SkySpot | None = None
    for radius, spot in candidates[:PATH_CHECKS]:
        here, there = _point(*spot, instance_id), _point(ax, ay, az, instance_id)
        path = navmesh.find_path(instance_id, here, there) if landing else \
            navmesh.find_path(instance_id, there, here)
        if path is None or path.cost > min(MAX_WALK_YARDS, WALK_DETOUR*radius + 15.):
            continue
        expected = (here, there) if landing else (there, here)
        if not path.anchors or any(
                math.hypot(actual['x']-wanted['x'], actual['y']-wanted['y']) > 2.5
                or abs(actual['z']-wanted['z']) > 2.5
                for actual, wanted in zip((path.anchors[0], path.anchors[-1]), expected)):
            continue  # Detour may clip a path to a disconnected/other-floor edge
        if best is None or path.cost < best.walk_yards:
            walk = tuple((float(a["x"]), float(a["y"]), float(a["z"])) for a in path.anchors)
            best = SkySpot(spot, walk, float(path.cost), tested)
    return best


def plan_trip(source, navmesh, instance_id: int, start: tuple[float, float, float],
              target: tuple[float, float, float]) -> TripPlan:
    """Walk to open sky, fly the cheapest route, land in open sky, walk on."""
    take_off = open_sky_spot(source, navmesh, instance_id, start, landing=False)
    if take_off is None:
        return TripPlan("no_take_off_spot")
    landing = open_sky_spot(source, navmesh, instance_id, target, landing=True)
    if landing is None:
        return TripPlan("no_landing_spot", take_off=take_off)
    result = plan_flight(source, take_off.point, landing.point)
    return TripPlan(result.reason, take_off, result.route, landing, result.attempts)
