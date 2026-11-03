"""Adapt the shared A* / walk-fly-walk geometry to canonical flight control.

Planning data only. NavigationService still owns the MOVE, phase changes,
controller and input lease. No capability or binding is inferred here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import time

from .flight_planner import plan_flight
from .flight_trip import TripPlan, open_sky_spot, plan_trip
from .flight_route import FlightPlan, landing_candidates

HORIZON_YARDS = 1024.
PLAN_SECONDS = 2.


class PlanningDeadline(Exception):
    pass


class GeometryHeightSource:
    """Current geometry API, including cosmetic-map conversion, for old A*."""

    def __init__(self, geometry, instance_id):
        self.geometry, self.instance_id = geometry, instance_id
        self._terrain, self._models = {}, {}
        self._liquid = {}
        self.deadline = None

    def _budget(self, *, start=False):
        if self.deadline is None and start:
            self.deadline = time.perf_counter()+PLAN_SECONDS
        if self.deadline is not None and time.perf_counter() > self.deadline:
            raise PlanningDeadline

    def terrain(self, x, y):
        self._budget()
        key = (x, y)
        if key not in self._terrain:
            sampler = getattr(self.geometry, 'terrain_sample', None)
            sample = sampler(self.instance_id, {'x': x, 'y': y}) if callable(sampler) else None
            self._terrain[key] = ((None if sample.is_hole else sample.terrain_z, bool(sample.is_hole))
                                  if sample is not None else self.geometry.terrain_height(self.instance_id, x, y))
            self._liquid[key] = (sample.liquid_z if sample is not None and sample.has_liquid
                                 and sample.liquid_z > -1000. else None)
        return self._terrain[key]

    def models(self, x, y):
        self._budget()
        key = (x, y)
        if key not in self._models:
            self._models[key] = self.geometry.vmap_surfaces_at(self.instance_id, {'x': x, 'y': y})
        return self._models[key]

    def reaches(self, x, y, ceiling):
        self._budget(start=True)
        z, hole = self.terrain(x, y)
        liquid = self._liquid.get((x, y))
        if liquid is not None and liquid >= ceiling:
            return True
        if z is None and not hole:
            return None
        return not hole and z >= ceiling

    def model_reaches(self, x, y, ceiling):
        return any(z >= ceiling for z in self.models(x, y))

    def top(self, x, y):
        self._budget(start=True)
        z, hole = self.terrain(x, y)
        if z is None and not hole:
            return None
        values = [*self.models(x, y), *([z] if z is not None and not hole else [])]
        liquid = self._liquid.get((x, y))
        if liquid is not None:
            values.append(liquid)
        return max(values) if values else None

    def covered(self, x, y, low, high):
        z, hole = self.terrain(x, y)
        return (z is None and not hole or z is not None and not hole and z > low
                or any(low <= height <= high for height in self.models(x, y)))


def supports_trip(geometry):
    return all(callable(getattr(geometry, name, None)) for name in (
        'terrain_height', 'vmap_surfaces_at', 'walkable_heights_at', 'find_path',
        'project_position', 'walkable_points_near', 'supports'))


def departure_walk(geometry, instance, start):
    if not supports_trip(geometry) or any(start.get(k) is None for k in ('x', 'y', 'z')):
        return None
    return open_sky_spot(GeometryHeightSource(geometry, instance), geometry, instance,
                         tuple(start[k] for k in ('x', 'y', 'z')), landing=False)


@dataclass
class TravelFlight:
    plan: FlightPlan | None
    reason: str
    trip: TripPlan | None = None


def _adapt(source, instance, trip, *, truncated=False):
    route = trip.flight
    start = dict(zip(('x', 'y', 'z'), trip.take_off.point))
    landing = dict(zip(('x', 'y', 'z'), route.waypoints[-1]))
    corners = [dict(zip(('x', 'y', 'z'), point)) for point in route.waypoints[1:-2]]
    points = [start, *corners, landing]
    distance = sum(math.hypot(b['x']-a['x'], b['y']-a['y']) for a, b in zip(points, points[1:]))
    provisional = FlightPlan(instance, start, landing, distance, waypoints=tuple(corners))
    if distance > HORIZON_YARDS or truncated:
        cutoff = min(distance, HORIZON_YARDS)
        landing = {**provisional.point_at(cutoff), 'z': route.cruise_z}
        kept, along = [], 0.
        for left, right in zip(points, points[1:]):
            along += math.hypot(right['x']-left['x'], right['y']-left['y'])
            if along < cutoff and right is not points[-1]:
                kept.append(right)
        corners, distance, truncated = kept, cutoff, True
    provisional = FlightPlan(instance, start, landing, distance, waypoints=tuple(corners))
    steps = max(1, int(math.ceil(distance/8.)))
    profile = []
    for index in range(steps+1):
        at = min(distance, index*8.)
        point = provisional.point_at(at)
        height = source.top(point['x'], point['y'])
        if height is None:
            return TravelFlight(None, 'unknown_ground_on_air_route', trip)
        profile.append((at, height))
    plan = FlightPlan(instance, start, landing, distance, tuple(profile), truncated=truncated,
                      waypoints=tuple(corners), cruise_z=route.cruise_z)
    return TravelFlight(plan, 'planned', trip)


def plan_travel_flight(geometry, instance, start, destination, *, min_distance=40., flight_style='STEADY'):
    if not supports_trip(geometry) or start.get('z') is None:
        return TravelFlight(None, 'trip_geometry_unavailable')
    if not geometry.supports(instance):
        return TravelFlight(None, 'no_world_geometry')
    candidates = landing_candidates(geometry, instance, destination)
    if not candidates:
        return TravelFlight(None, 'no_landing_point')
    target = candidates[0]
    flat = math.hypot(target['x']-start['x'], target['y']-start['y'])
    if flat < min_distance:
        return TravelFlight(None, 'too_short')
    source = GeometryHeightSource(geometry, instance)
    source.margin_yards = 32. if flight_style == 'SKYRIDING' else 8.
    origin = tuple(float(start[k]) for k in ('x', 'y', 'z'))
    try:
        if flat > HORIZON_YARDS:
            # Bound A* to one horizon. Passing its end replans this same MOVE
            # in the air; it never proves arrival at the original destination.
            take_off = open_sky_spot(source, geometry, instance, origin, landing=False)
            if take_off is None:
                return TravelFlight(None, 'no_take_off_spot')
            fraction = HORIZON_YARDS/flat
            x, y = (start[k]+(target[k]-start[k])*fraction for k in ('x', 'y'))
            z = source.top(x, y)
            if z is None:
                return TravelFlight(None, 'unknown_horizon_ground')
            result = plan_flight(source, take_off.point, (x, y, z))
            trip = TripPlan(result.reason, take_off, result.route, attempts=result.attempts)
            return (_adapt(source, instance, trip, truncated=True) if result.route else
                    TravelFlight(None, result.reason, trip))
        trip = plan_trip(source, geometry, instance, origin, tuple(target[k] for k in ('x', 'y', 'z')))
        result = _adapt(source, instance, trip) if trip.flight else TravelFlight(None, trip.reason, trip)
        if (result.plan and not result.plan.truncated and target.get('navmesh') is False
                and trip.landing and trip.landing.walk_yards == 0):
            # A known dome/platform top may have no MMAP. Preserve the existing
            # actual-touchdown contract; do not turn it into an impossible walk.
            result.plan = replace(result.plan, landing={**result.plan.landing, 'navmesh': False})
        return result
    except PlanningDeadline:
        return TravelFlight(None, 'air_planning_budget_exhausted')
