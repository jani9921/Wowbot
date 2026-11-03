"""Flight departure and ground-leg transitions (REV4 NavigationService split).

Moved out of ``NavigationService`` (SRC_MELY_AUDIT 4.3: TravelTransitionSystem,
flight / departure / ground leg).  Decisions only; the service still owns the
request, starts every leg through its single movement controller and checks
the deadlines:

* ``departure_active`` -- the route is the walk out to a take-off spot,
* ``departure_flight_ready`` -- mounted and nothing blocks the flight style,
* ``flight_destination`` -- the original goal as a flight from here,
* ``after_departure_walk`` -- at the take-off spot: fly, continue the original
  goal on the ground when the zone cannot fly, or wait (``None``),
* ``ground_request`` -- the final ground leg of a flight (same owner),
* ``departure_walk`` -- the planning-only take-off walk oracle (cached; a
  cancel or navigation reset clears it).
"""
from __future__ import annotations

from dataclasses import replace
import math

from wowbot.agent.movement_controller import ReachMovementController
from .contracts import ArrivalEnvelope


class TravelTransitionPolicy:
    def __init__(self, navmesh) -> None:
        self._navmesh = navmesh               # () -> the owner's navmesh
        self.departures: dict = {}

    def reset(self) -> None:
        self.departures.clear()

    @staticmethod
    def departure_active(route) -> bool:
        return bool(route and any(region.get('partial_flight_departure') for region in route.regions))

    @staticmethod
    def departure_flight_ready(state, style):
        if state.get('is_mounted') is not True:
            return False
        from wowbot.agent.flight_capability import flight_blockers, skyriding_blockers
        return not (skyriding_blockers(state) if style == 'SKYRIDING' else flight_blockers(state))

    @staticmethod
    def flight_destination(destination: dict, style) -> dict:
        destination = {key: value for key, value in destination.items() if key != 'flight_departure'}
        return {**destination, 'flight': True, 'flight_style': style}

    @classmethod
    def after_departure_walk(cls, destination: dict, state: dict) -> dict | None:
        style = (destination.get('flight_departure') or {}).get(
            'flight_style', destination.get('flight_style', 'STEADY'))
        if cls.departure_flight_ready(state, style):
            return cls.flight_destination(destination, style)
        if (state.get('movement') or {}).get('indoors') is False:
            # A usable mount is a normal planner prerequisite. If the
            # zone cannot fly, continue the original goal on MMAP.
            from wowbot.agent.flight_capability import skyriding_blockers, flight_blockers
            blocked = skyriding_blockers(state) if style == 'SKYRIDING' else flight_blockers(state)
            if blocked:
                return {key: value for key, value in destination.items()
                        if key not in {'flight_departure', 'flight'}}
        return None

    @staticmethod
    def ground_request(request, path=None):
        destination = {key: value for key, value in request.destination.items()
                       if key not in {"flight_path", "flight", "flight_plan"}}
        radius = request.arrival.desired_range or request.arrival.radius or ReachMovementController.world_arrival_tolerance
        if path is not None:
            destination.update(path.landing, arrival_condition=path.arrival_condition)
            radius = path.radius
        destination.update(require_navmesh=True, stop_distance=radius, arrival_radius=radius)
        return replace(request, request_id=request.request_id + ":ground",
                       destination=destination, arrival=ArrivalEnvelope(radius=radius, desired_range=radius))

    def departure_walk(self, parameters, state):
        """Planning-only oracle: a real MMAP walk from a covered start to sky."""
        from .flight_travel import GeometryHeightSource, departure_walk, supports_trip
        from wowbot.agent.destination_distance import observed_height
        geometry = self._navmesh()
        player = state.get('player_world_position') or {}
        instance, z = player.get('instance_id'), observed_height(player)
        if (not supports_trip(geometry) or instance is None or z is None
                or str(parameters.get('instance_id')) != str(instance)):
            return None
        start = {**player, 'z': z}
        source = GeometryHeightSource(geometry, instance)
        if not source.covered(start['x'], start['y'], z+3., 2000.):
            return None
        key = (state.get('session_id'), instance, round(start['x']/20), round(start['y']/20), round(z/3),
               parameters.get('x'), parameters.get('y'))
        cache = self.departures
        if key not in cache:
            cache[key] = departure_walk(geometry, instance, start)
            while len(cache) > 8:
                cache.pop(next(iter(cache)))
        spot = cache[key]
        if spot is None or spot.walk_yards <= 0 or math.hypot(spot.point[0]-start['x'], spot.point[1]-start['y']) <= 2.:
            return None
        return {'anchors': [dict(zip(('x', 'y', 'z'), point)) for point in spot.walk],
                'point': dict(zip(('x', 'y', 'z'), spot.point))}
