"""Semantic trip lifecycle above the existing single navigation controller.

The executor verifies legs and transitions. It never creates key commands,
holds an input lease, or substitutes a second ground/flight navigator.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import math


class TripStatus(StrEnum):
    RUNNING = 'RUNNING'
    SUCCEEDED = 'SUCCEEDED'
    CANCELLED = 'CANCELLED'
    FAILED = 'FAILED'
    LEG_COMPLETE = 'LEG_COMPLETE'


class LegKind(StrEnum):
    GROUND = 'GROUND'
    RIDE = 'RIDE'
    MOUNT = 'MOUNT'
    TAKEOFF = 'TAKEOFF'
    FLIGHT = 'FLIGHT'
    LAND = 'LAND'
    DISMOUNT = 'DISMOUNT'


@dataclass(frozen=True, slots=True)
class TravelRequest:
    request_id: str
    correlation_id: str
    goal_id: str
    destination_json: str
    target_reference: str | None
    radius: float
    require_ground: bool
    face_on_arrival: bool
    timeout: float
    arrival_semantics: str = 'FINAL_POINT'

    @classmethod
    def from_navigation(cls, request):
        point = request.destination
        if (point.get('coordinate_space') != 'WORLD_YARDS'
                or type(point.get('instance_id')) is not int
                or point['instance_id'] < 0
                or any(type(point.get(k)) not in {int, float} or not math.isfinite(point[k]) for k in ('x', 'y'))):
            return None  # legacy normalized points never become world destinations
        radius = next((v for v in (request.arrival.desired_range, request.arrival.radius,
                                  point.get('stop_distance'), point.get('arrival_radius'))
                       if type(v) in {int, float} and math.isfinite(v) and v >= 0), 5.)
        return cls(request.request_id, request.correlation_id,
                   str(point.get('goal_id') or point.get('objective_id') or point.get('quest_id') or request.request_id),
                   json.dumps(point, sort_keys=True, allow_nan=False), request.target_entity_id,
                   float(radius), not bool((point.get('flight_path') or {}).get('end_in_air') or point.get('hover_point')),
                   point.get('face_on_arrival') is True, float(request.timeout or 90.),
                   'SEARCH_PROGRESS' if point.get('location_source') == 'QUEST_ZONE_SWEEP' else 'FINAL_POINT')

    @property
    def destination(self):
        return json.loads(self.destination_json)


@dataclass(frozen=True, slots=True)
class TripLeg:
    leg_id: str
    kind: LegKind
    route_id: str
    final_goal: bool
    expected_evidence: str


@dataclass(frozen=True, slots=True)
class TripPlan:
    request: TravelRequest
    legs: tuple[TripLeg, ...]
    geometry_revision: str | int | None
    risk_revision: int


class TransitionSystem:
    """Observe actual transitions, not command ACKs; bounded history."""
    def __init__(self):
        self.previous = {}
        self.events = []

    def observe(self, state, now):
        flight = state.get('packet_flight') or {}
        sample = flight.get('sample_time', state.get('monotonic_time'))
        if type(sample) not in {int, float} or not 0 <= now-sample <= 2.:
            return
        movement = state.get('movement') or {}
        current = {'mounted': state.get('is_mounted'),
                   'flying': flight.get('flying', movement.get('flying'))}
        for field, enter, leave in (('mounted', LegKind.MOUNT, LegKind.DISMOUNT),
                                    ('flying', LegKind.TAKEOFF, LegKind.LAND)):
            value, previous = current[field], self.previous.get(field)
            if type(value) is bool and type(previous) is bool and value != previous:
                self.events.append({'kind': (enter if value else leave).value, 'observed_at': sample,
                                    'verified': True, 'evidence': 'observed_state_transition'})
        self.events = self.events[-16:]
        self.previous = {k: v for k, v in current.items() if type(v) is bool}


class TripExecutor:
    def __init__(self):
        self.request = None
        self.plan = None
        self.status = TripStatus.CANCELLED
        self.started_at = None
        self.reason = 'no_trip'
        self.transitions = TransitionSystem()
        self.route_id = None
        self.waypoint_index = None

    def start(self, request, now, *, continuing=False):
        adapted = TravelRequest.from_navigation(request)
        if adapted is None:
            self.cancel('legacy_non_world_request')
            return
        same = bool(self.request and self.status is TripStatus.RUNNING and (request.request_id == self.request.request_id
                    or continuing and request.correlation_id == self.request.correlation_id))
        if same:
            return  # a landing/horizon/localization leg cannot replace the original goal
        self.request, self.started_at = adapted, now
        self.plan, self.route_id, self.waypoint_index = None, None, None
        self.status, self.reason = TripStatus.RUNNING, 'trip_started'
        self.transitions = TransitionSystem()

    EVIDENCE = {'MOUNT': 'mounted_state_observed', 'DISMOUNT': 'unmounted_state_observed',
                'TAKEOFF': 'fresh_flying_state', 'LAND': 'grounded_on_resolved_floor'}

    def route(self, route, request, *, geometry_revision=None, risk_revision=0, state=None):
        """Spec 30.1: explicit legs, including the mount and the walk to open
        sky (MIXED) -- GroundLeg, MountTransition, Takeoff, Flight, Landing,
        GroundLeg -- from the planned route and the current mode."""
        if self.request is None or route is None:
            return
        state = state or {}
        flight = any(a.get('flight_plan') for a in route.anchors) or bool(request.destination.get('flight_path'))
        departure = bool(request.destination.get('flight_departure')) or any(
            r.get('partial_flight_departure') for r in route.regions)
        partial = any(r.get('partial_flight_departure') or r.get('partial_localization')
                      or r.get('partial_localization_probe') or r.get('partial_localization_leg') for r in route.regions)
        mounted = state.get('is_mounted') is True
        airborne = (state.get('movement') or {}).get('flying') is True or (state.get('packet_flight') or {}).get('flying') is True
        if flight or departure:
            kinds = [*([LegKind.GROUND] if departure else []), *([] if mounted or airborne else [LegKind.MOUNT]),
                     *([] if airborne else [LegKind.TAKEOFF]), LegKind.FLIGHT, LegKind.LAND, LegKind.GROUND]
        else:
            kinds = [LegKind.RIDE if mounted else LegKind.GROUND]
        self.plan = TripPlan(self.request, tuple(TripLeg(
            f'{route.route_id}:{i}', kind, route.route_id, i == len(kinds)-1 and not partial
            and self.request.arrival_semantics == 'FINAL_POINT',
            self.EVIDENCE.get(kind.value, 'verified_progress'))
            for i, kind in enumerate(kinds)), geometry_revision, risk_revision)
        self.route_id = route.route_id

    def observe(self, state, now, *, waypoint_index=None, terminal=False, success=False,
                reason='', resolved_destination=None):
        if self.request is None or self.status is not TripStatus.RUNNING:
            return self.status
        self.transitions.observe(state, now)
        self.waypoint_index = waypoint_index
        if terminal and not success:
            self.status, self.reason = TripStatus.FAILED, reason
        elif terminal and success:
            if self.request.arrival_semantics == 'SEARCH_PROGRESS':
                self.status, self.reason = TripStatus.LEG_COMPLETE, 'search_progress_leg_verified'
                return self.status
            failure = self.final_arrival_problem(state, now, resolved_destination=resolved_destination)
            if failure is None:
                self.status, self.reason = TripStatus.SUCCEEDED, 'original_goal_arrival_verified'
            elif now-self.started_at >= self.request.timeout:
                self.status, self.reason = TripStatus.FAILED, 'trip_arrival_evidence_timeout:'+failure
            else:
                self.reason = failure
        return self.status

    def final_arrival_problem(self, state, now, *, resolved_destination=None):
        request, destination = self.request, self.request.destination
        if destination.get('entity_goal') is True:
            from .entity_goal import resolve
            guid = destination.get('interaction_recipient_guid') or destination.get('target_guid')
            if not guid or str(guid) != str(request.target_reference):
                return 'trip_entity_identity_unknown'
            destination = resolve(destination, state, now)
            if destination is None:
                return 'trip_entity_identity_or_position_lost'
        player = state.get('player_world_position') or {}
        if (player.get('coordinate_space') != 'WORLD_YARDS'
                or player.get('instance_id') != destination['instance_id']
                or any(type(player.get(k)) not in {int, float} or not math.isfinite(player[k]) for k in ('x', 'y'))):
            return 'trip_position_unknown_or_wrong_map'
        sample = player.get('sample_time', state.get('monotonic_time'))
        if type(sample) not in {int, float} or not 0 <= now-sample <= 2.:
            return 'trip_position_stale'
        if math.hypot(player['x']-destination['x'], player['y']-destination['y']) > request.radius:
            return 'trip_original_goal_not_reached'
        resolved = resolved_destination or destination
        target_z = destination.get('z') if destination.get('z_known') is True else resolved.get('layer_z', resolved.get('z'))
        if not request.require_ground and type(target_z) in {int, float}:
            own_z = player.get('z')
            if (type(own_z) not in {int, float} or not math.isfinite(own_z)
                    or math.dist((player['x'], player['y'], own_z),
                                 (destination['x'], destination['y'], target_z)) > request.radius):
                return 'trip_air_arrival_not_verified'
            target_z = None
        if target_z is not None and resolved.get('z_known', destination.get('z_known')) is not False:
            own_z = player.get('observed_z', player.get('z'))
            if (type(own_z) not in {int, float} or not math.isfinite(own_z)
                    or abs(own_z-target_z) > max(3., min(request.radius, 6.))):
                return 'trip_final_floor_not_verified'
        movement = state.get('movement') or {}
        flight = state.get('packet_flight') or {}
        if request.require_ground and (movement.get('flying') is True or flight.get('flying') is True
                                       or movement.get('falling') is True):
            return 'trip_touchdown_not_verified'
        if request.face_on_arrival:
            face = destination.get('face_towards') or destination
            dx, dy = face.get('x', destination['x'])-player['x'], face.get('y', destination['y'])-player['y']
            heading = state.get('orientation')
            if math.hypot(dx, dy) > .1 and (type(heading) not in {int, float} or not math.isfinite(heading)
                    or abs(math.atan2(math.sin(math.atan2(dy, dx)-heading), math.cos(math.atan2(dy, dx)-heading))) > .6):
                return 'trip_facing_not_verified'
        return None

    def cancel(self, reason='cancelled'):
        if self.status is TripStatus.RUNNING:
            self.status, self.reason = TripStatus.CANCELLED, reason

    def snapshot(self):
        return {'status': self.status.value, 'reason': self.reason,
                'request_id': self.request.request_id if self.request else None,
                'correlation_id': self.request.correlation_id if self.request else None,
                'goal_id': self.request.goal_id if self.request else None,
                'arrival_semantics': self.request.arrival_semantics if self.request else None,
                'original_destination': self.request.destination if self.request else None,
                'route_id': self.route_id, 'waypoint_index': self.waypoint_index,
                'legs': [{'leg_id': l.leg_id, 'kind': l.kind.value, 'final_goal': l.final_goal,
                          'expected_evidence': l.expected_evidence} for l in self.plan.legs] if self.plan else [],
                'transitions': list(self.transitions.events)}
