"""Slow, evidence-bounded global route construction for Navigation V5.

The planner deliberately produces data only.  It does not know about key
bindings, schedules no input and is allowed to run only at request/replan
boundaries.  The service remains the sole owner that can hand a plan to the
movement controller.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
from typing import Any, Iterable

from wowbot.agent.models import number

from .contracts import GlobalRoute, NavigationRequest
from .spawn_threats import SEVERE_KINDS


@dataclass(frozen=True, slots=True)
class GlobalPlannerPolicy:
    route_ttl_seconds: float = 20.0
    direct_route_confidence: float = 0.45
    measured_route_confidence: float = 0.80
    local_failure_replan_threshold: int = 3
    danger_clearance: float = 2.0
    danger_route_confidence: float = 0.65
    # Spec 31.2: this many ordinary hostiles on a non-combat route already
    # make the planner try a detour (kept only when cheaper with danger).
    hostile_detour_count: int = 2


class GlobalNavigator:
    """Build a stable route envelope from already validated world knowledge."""

    def __init__(self, policy: GlobalPlannerPolicy | None = None, *, navmesh=None,
                 walkable=None) -> None:
        self.policy = policy or GlobalPlannerPolicy()
        self.navmesh = navmesh
        # walkable(instance_id, point) -> surface | None.  Detours around a
        # learned obstacle must land on the mmap, not in a wall or the sea.
        self.walkable = walkable

    def plan(self, request: NavigationRequest, state: dict[str, Any], now: float,
             *, measured_anchors: Iterable[dict[str, Any]] = (), danger_map=None) -> GlobalRoute:
        primary = self._plan_route(request, state, now, measured_anchors=measured_anchors, danger_map=danger_map)
        from .route_score import RouteRiskEvaluator
        evaluator = RouteRiskEvaluator()
        candidates = [(primary, request)]
        if (request.destination.get('flight') is True and primary.anchors
                and request.destination.get('travel_mode_policy') == 'AUTO'
                and not request.destination.get('flight_path') and not request.destination.get('hover_point')
                and not any(r.get('partial_flight_departure') or r.get('partial_localization_leg') for r in primary.regions)
                and (state.get('movement') or {}).get('flying') is not True):
            ground_request = replace(request, destination={k: v for k, v in request.destination.items()
                                                          if k not in {'flight', 'flight_style', 'flight_plan'}})
            ground = self._plan_route(ground_request, state, now, measured_anchors=measured_anchors, danger_map=danger_map)
            # Only a proved connected corridor may compete with a planned
            # flight; a direct fallback is not a cheaper route through walls.
            if ground.anchors and any(r.get('route_source') == 'TRINITYCORE_MMAP' for r in ground.regions):
                candidates.append((ground, ground_request))
        scored = [(route, evaluator.evaluate(route, candidate_request, state, now, danger_map=danger_map,
                   geometry_revision=getattr(self.navmesh, 'revision', None))) for route, candidate_request in candidates]
        selected, score = min(scored, key=lambda item: item[1].total_seconds
                             if item[1].total_seconds is not None else math.inf)
        self.last_route_scores = {'selected_route_id': selected.route_id,
                                  'candidates': [s.diagnostic() for _, s in scored]}
        return selected

    def _plan_route(self, request: NavigationRequest, state: dict[str, Any], now: float,
                    *, measured_anchors: Iterable[dict[str, Any]] = (), danger_map=None) -> GlobalRoute:
        destination = self._point(request.destination)
        player = self._point(state.get("player_world_position") or state.get("position") or {})
        if destination is None:
            raise ValueError("navigation request destination requires finite x/y coordinates")
        if request.destination.get('flight_departure'):
            self.last_flight_planning = {'phase': 'WALK_TO_TAKEOFF', 'planner': 'MMAP', 'reason': 'verified_departure'}
            return self._departure_route(request, request.destination['flight_departure'], state, now)
        if request.destination.get("flight") is True:
            flight = self._flight_route(request, state, player, now)
            if flight is not None:
                return flight
        if (request.destination.get("flight_path") or request.destination.get("hover_point")) and player is not None:
            # Explicit ordered air geometry is task-independent.
            from .flight_path import FlightPath
            identity = (FlightPath.from_dict(request.destination["flight_path"]).identity
                        if request.destination.get("flight_path") else repr(request.destination.get("hover_point")))
            anchors = (dict(player), dict(destination))
            return GlobalRoute(
                route_id="route:" + hashlib.sha256(repr((request.request_id, identity)).encode()).hexdigest()[:20],
                anchors=anchors, regions=({"kind": "DESTINATION_REGION", "fact": False,
                                           "route_source": "ORDERED_FLIGHT_PATH"},),
                cost=round(self._distance(anchors[0], anchors[1]), 5), confidence=.8,
                created_at=float(now), valid_until=float(now) + 300.)
        navmesh_path = self._navmesh_path(request, state, player, destination)
        wrong_endpoint_level = False
        probe_endpoint_mismatch = False
        if navmesh_path is not None and navmesh_path.anchors:
            # A complete Detour path can still end on another floor when the
            # requested surface is disconnected. Do not replace a known upper
            # landing with the courtyard under it (East Arbalest, 2026-10-27).
            from wowbot.agent.destination_distance import OTHER_LEVEL_YARDS
            target_z = number(request.destination.get("z"))
            endpoint_z = number(navmesh_path.anchors[-1].get("z"))
            if (request.destination.get("z_known") is True
                    and (request.destination.get("z_estimated") is not True
                         or request.destination.get('z_knowledge_priority', request.destination.get("knowledge_priority")) == "PRIMARY_STATIC"
                         and (number(request.destination.get("z_confidence")) or 0.) >= .7)
                    and target_z is not None and endpoint_z is not None
                    and abs(endpoint_z-target_z) > OTHER_LEVEL_YARDS):
                navmesh_path = None
                wrong_endpoint_level = True
            if navmesh_path is not None and request.destination.get("object_approach_probe"):
                endpoint = navmesh_path.anchors[-1]
                # A local side-step probe must actually reach that sector,
                # not Detour's clipped endpoint back at the rejected edge.
                if (math.hypot(endpoint["x"]-destination["x"], endpoint["y"]-destination["y"]) > 2.
                        or target_z is not None and endpoint_z is not None and abs(endpoint_z-target_z) > 3.):
                    navmesh_path = None
                    probe_endpoint_mismatch = True
        navmesh_required = bool(request.destination.get("require_navmesh") or wrong_endpoint_level
                                or probe_endpoint_mismatch)
        if navmesh_path is not None:
            anchors = tuple(dict(point) for point in navmesh_path.anchors)
        elif navmesh_required:
            anchors = ()
        else:
            anchors = tuple(self._normalise_anchors(player, measured_anchors, destination))
        measured = len(anchors) > 2
        danger_adapted = False
        # Elites, rares and mob clusters (TDB / live spawns) are avoided on any
        # trip that is not for combat (user 2026-10-20).
        severe = (danger_map is not None and not request.allow_combat
                  and danger_map.has_kinds(now, SEVERE_KINDS, exempt_entity_id=request.target_entity_id))
        exposed = (danger_map is not None and not request.allow_combat and len(anchors) >= 2
                   and len(danger_map.corridor_hostiles(anchors, now, exempt_entity_id=request.target_entity_id))
                   >= self.policy.hostile_detour_count)
        use_danger_cost = (danger_map is not None and
                           (request.avoid_combat or danger_map.has_navigation_failures(now) or severe or exposed))
        if use_danger_cost and len(anchors) >= 2:
            adapted = danger_map.avoidance_anchors(
                anchors, now, exempt_entity_id=request.target_entity_id,
                clearance=self.policy.danger_clearance,
                walkable=self._detour_validator(state))
            if adapted != anchors and navmesh_path is not None:
                # Detour points are joined by navmesh paths (never a straight
                # line through a wall), and kept only when the whole route is
                # cheaper with its danger counted.
                rerouted = self._through_detours(request, state, anchors, adapted)
                cost_of = lambda points: danger_map.route_cost(
                    points, now, exempt_entity_id=request.target_entity_id)
                adapted = (rerouted if rerouted is not None and cost_of(rerouted) < cost_of(anchors)
                           else anchors)
            danger_adapted = adapted != anchors
            anchors = adapted
        cost = (danger_map.route_cost(anchors, now, exempt_entity_id=request.target_entity_id)
                if use_danger_cost
                else sum(self._distance(left, right) for left, right in zip(anchors, anchors[1:])))
        map_id = (request.destination.get("map_id") or request.destination.get("ui_map_id")
                  or request.destination.get("world_map_id")
                  or state.get("map_id"))
        context_map = (state.get('map_id') if request.destination.get('coordinate_space') == 'WORLD_YARDS'
                       else map_id)
        regions = ({"map_id": context_map or map_id, "destination_ui_map_id": map_id,
                    "kind": "DESTINATION_REGION", "fact": False,
                    "danger_adapted": danger_adapted,
                    # The mmap route ends on Detour's float32 polygon point,
                    # never exactly on the requested destination.
                    "requested_destination": {"x": destination["x"], "y": destination["y"]},
                    "route_source": ("TRINITYCORE_MMAP" if navmesh_path is not None
                                     else "MMAP_REQUIRED_UNAVAILABLE" if navmesh_required
                                     else "MEASURED_OR_DIRECT"),
                    **({"navmesh_tile_count": navmesh_path.tile_count,
                        "navmesh_polygon_count": navmesh_path.polygon_count}
                       if navmesh_path is not None else {})},)
        fingerprint = repr((request.request_id, request.correlation_id, map_id, anchors))
        route_id = "route:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20]
        return GlobalRoute(
            route_id=route_id,
            anchors=anchors,
            regions=regions,
            cost=round(cost, 5),
            confidence=(0. if navmesh_required and navmesh_path is None
                        else self.policy.danger_route_confidence if danger_adapted
                        else .95 if navmesh_path is not None
                        else self.policy.measured_route_confidence if measured
                        else self.policy.direct_route_confidence),
            created_at=float(now),
            # Static mmap corridors do not expire every 20 seconds while a
            # key may be held. Destination/map/danger/corridor/failure events
            # still trigger immediate replanning through needs_replan().
            valid_until=float(now) + (300. if navmesh_path is not None
                                      else self.policy.route_ttl_seconds),
        )

    def _flight_route(self, request: NavigationRequest, state: dict[str, Any],
                      player: dict[str, float] | None, now: float) -> GlobalRoute | None:
        """Start -> landing, retaining explicit flights between known floors.

        An ordinary short trip may walk. An airborne/relaunch request or an
        observed change of level needs a flight plan or an empty failed route;
        silently walking under its landing cannot satisfy that request.
        """
        from .flight_route import plan_flight
        from .flight_path import airborne as currently_airborne
        from wowbot.agent.death_recovery_planning import corpse_run_matches
        from wowbot.agent.flight_capability import ghost_steady_flight_available
        from wowbot.agent.destination_distance import observed_height, OTHER_LEVEL_YARDS
        geometry = self.navmesh
        raw = state.get("player_world_position") or {}
        # Airborne it has to land however short the way; a relaunch (landing
        # not reachable on foot) flies the last stretch too.
        airborne = (currently_airborne(state, now)
                    or request.destination.get("flight_relaunch") is True)
        ghost_landing = (request.destination.get('flight_style') == 'STEADY'
                         and ghost_steady_flight_available(state)
                         and corpse_run_matches(state, request.destination))
        measured_z = observed_height(raw)
        target_z = number(request.destination.get("z"))
        other_level = (request.destination.get("z_known") is True
                       and (request.destination.get("z_estimated") is not True
                            or request.destination.get('z_knowledge_priority', request.destination.get("knowledge_priority")) == "PRIMARY_STATIC"
                            and (number(request.destination.get("z_confidence")) or 0.) >= .7)
                       and measured_z is not None and target_z is not None
                       and abs(target_z-measured_z) > OTHER_LEVEL_YARDS)
        flight_required = airborne or other_level
        travel = None
        if player is None or not callable(getattr(geometry, "terrain_height", None)):
            plan, reason = None, "no_world_geometry"
        else:
            try:
                instance = int(raw.get("instance_id"))
            except (TypeError, ValueError):
                instance = None
            start = {"x": player["x"], "y": player["y"],
                     "z": measured_z}
            minimum = 0. if flight_required or ghost_landing else 40.
            if instance is not None:
                from .flight_travel import plan_travel_flight
                travel = plan_travel_flight(geometry, instance, start, request.destination,
                    min_distance=minimum, flight_style=request.destination.get('flight_style', 'STEADY'))
            if travel is not None and travel.reason != 'trip_geometry_unavailable':
                plan, reason = travel.plan, travel.reason
                self.last_flight_planning = {'planner': 'LATERAL_ASTAR', 'reason': reason,
                    'attempts': travel.trip.attempts if travel.trip else [],
                    'takeoff_walk_yards': travel.trip.take_off.walk_yards if travel.trip and travel.trip.take_off else 0.,
                    'landing_walk_yards': travel.trip.landing.walk_yards if travel.trip and travel.trip.landing else 0.}
                if plan and travel.trip and travel.trip.take_off.walk_yards > 0:
                    return self._departure_route(request, {
                        'anchors': [dict(zip(('x', 'y', 'z'), point)) for point in travel.trip.take_off.walk],
                        'point': dict(zip(('x', 'y', 'z'), travel.trip.take_off.point)),
                        'flight_style': request.destination.get('flight_style', 'STEADY')}, state, now)
            else:
                plan, reason = ((None, "no_instance") if instance is None else
                                plan_flight(geometry, instance, start, request.destination,
                                            min_distance=minimum))
        if plan is None and not flight_required:
            return None
        anchors = (() if plan is None else
                   ({"x": plan.start["x"], "y": plan.start["y"], "source": "FLIGHT_PLAN"},
                    {**plan.landing, "source": "FLIGHT_PLAN", "flight_plan": plan.to_dict()}))
        fingerprint = repr((request.request_id, request.correlation_id, "flight", anchors and plan.landing))
        return GlobalRoute(
            route_id="route:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20],
            anchors=anchors,
            regions=({"kind": "DESTINATION_REGION", "fact": False, "route_source": "FLIGHT_PLAN",
                      "flight_plan_status": reason,
                      'flight_planner': ('LATERAL_ASTAR' if travel and travel.reason != 'trip_geometry_unavailable'
                                         else 'TERRAIN_PROFILE'),
                      'landing_walk_yards': (travel.trip.landing.walk_yards
                                             if travel and travel.trip and travel.trip.landing else 0.),
                      'air_route_truncated': bool(plan and plan.truncated),
                      "requested_destination": {"x": request.destination.get("x"),
                                                "y": request.destination.get("y")}},),
            cost=round(plan.distance, 5) if plan is not None else 0.,
            confidence=.8 if plan is not None else 0.,
            created_at=float(now), valid_until=float(now) + 300.)

    def _departure_route(self, request, departure, state, now):
        # Proposal metadata names a candidate exit, not an authoritative path.
        # Re-prove its MMAP walk from the CURRENT pose on each request boundary.
        from .flight_trip import MAX_WALK_YARDS, WALK_DETOUR
        player = state.get('player_world_position') or {}
        point = departure.get('point') or {}
        instance = player.get('instance_id')
        finder = getattr(self.navmesh, 'find_path', None)
        path = None
        if (callable(finder) and instance is not None
                and request.destination.get('instance_id') == instance
                and all(type(row.get(k)) in (int, float) and math.isfinite(row[k])
                        for row in (point, player) for k in ('x', 'y', 'z'))):
            path = finder(instance, player, {**point, 'z_known': True, 'instance_id': instance})
            flat = math.hypot(point['x']-player['x'], point['y']-player['y'])
            if path is not None and (not path.anchors or path.cost > min(MAX_WALK_YARDS, WALK_DETOUR*flat+15.)
                    or any(math.hypot(actual['x']-wanted['x'], actual['y']-wanted['y']) > 2.5
                           or abs(actual['z']-wanted['z']) > 2.5
                           for actual, wanted in zip((path.anchors[0], path.anchors[-1]), (player, point)))):
                path = None
        anchors = tuple({**anchor, 'source': 'TRINITYCORE_MMAP'} for anchor in path.anchors) if path else ()
        identity = repr((request.request_id, request.correlation_id, 'flight_departure', anchors))
        return GlobalRoute(
            route_id='route:'+hashlib.sha256(identity.encode()).hexdigest()[:20],
            anchors=anchors, regions=({'kind': 'DEPARTURE_REGION', 'fact': False,
                'route_source': 'FLIGHT_DEPARTURE_WALK', 'partial_flight_departure': True},),
            cost=sum(math.hypot(b['x']-a['x'], b['y']-a['y']) for a, b in zip(anchors, anchors[1:])),
            confidence=.9 if anchors else 0., created_at=float(now), valid_until=float(now)+300.)

    def _through_detours(self, request: NavigationRequest, state: dict[str, Any],
                         anchors: tuple[dict, ...], adapted: tuple[dict, ...]) -> tuple[dict, ...] | None:
        via = [point for point in adapted if point.get("danger_detour")]
        instance = (state.get("player_world_position") or {}).get("instance_id")
        if not via or instance is None:
            return None
        stops = [anchors[0], *({"x": point["x"], "y": point["y"], "z_known": False} for point in via),
                 anchors[-1]]
        result: list[dict] = [dict(anchors[0])]
        for left, right in zip(stops, stops[1:]):
            start = {**left, "z": number(result[-1].get("z")) or 0., "z_known": True}
            end = {**right, "z": number(right.get("z")) or 0.}
            path = self.navmesh.find_path(int(instance), start, end)
            if path is None or not path.anchors:
                return None
            result.extend(dict(point) for point in path.anchors[1:])
        return tuple(result)

    def _detour_validator(self, state: dict[str, Any]):
        # Without a configured mmap there is nothing to validate against;
        # keep the plain geometric detour rather than refusing every side.
        if (not callable(self.walkable)
                or not callable(getattr(self.navmesh, "project_position", None))):
            return None
        instance = (state.get("player_world_position") or {}).get("instance_id")
        if instance is None:
            return None
        return lambda point: self.walkable(instance, {"x": point["x"], "y": point["y"]}) is not None

    def resolve_global_route(self, request: NavigationRequest, state: dict[str, Any], now: float,
                             **kwargs) -> GlobalRoute:
        return self.plan(request, state, now, **kwargs)

    @staticmethod
    def choose_waypoint(route: GlobalRoute, index: int = 0) -> dict[str, Any] | None:
        if not route.anchors:
            return None
        return dict(route.anchors[min(max(0, int(index)), len(route.anchors)-1)])

    @classmethod
    def advance_waypoint(cls, route: GlobalRoute, index: int,
                         player: dict[str, Any], *, radius: float = 2.5) -> int:
        current = cls.choose_waypoint(route, index)
        point = cls._point(player)
        if current is None or point is None:
            return int(index)
        return (min(int(index)+1, len(route.anchors)-1)
                if cls._distance(point, current) <= max(.1, float(radius)) else int(index))

    def replan_if_required(self, route: GlobalRoute | None, request: NavigationRequest,
                           state: dict[str, Any], now: float, **kwargs) -> bool:
        return self.needs_replan(route, request, state, now, **kwargs)

    @staticmethod
    def detect_map_context_change(route: GlobalRoute | None, state: dict[str, Any]) -> bool:
        if route is None:
            return False
        expected = {item.get("map_id") for item in route.regions
                    if item.get("map_id") is not None}
        actual = state.get("map_id")
        return bool(expected and actual is not None and actual not in expected)

    def _navmesh_path(self, request: NavigationRequest, state: dict[str, Any],
                      player: dict[str, float] | None,
                      destination: dict[str, float]):
        if self.navmesh is None or player is None:
            return None
        raw_player = state.get("player_world_position") or {}
        raw_destination = request.destination
        if (raw_player.get("coordinate_space") not in {None, "WORLD_YARDS"}
                or raw_destination.get("coordinate_space") != "WORLD_YARDS"):
            return None
        player_instance = raw_player.get("instance_id")
        destination_instance = raw_destination.get("instance_id", player_instance)
        try:
            player_instance = int(player_instance)
            destination_instance = int(destination_instance)
        except (TypeError, ValueError):
            return None
        if player_instance != destination_instance:
            return None
        # The z flags travel with the point: an *estimated* height (terrain,
        # layer continuity, a lower quest layer) lets the navmesh probe the
        # other layers when it has no complete path (Torgok/Wrathion fix).
        flags = ("z_estimated", "z_observed", "z_source")
        start = {**player, "z": raw_player.get("z", player.get("z", 0.)),
                 "z_known": raw_player.get("z_known", raw_player.get("z") is not None),
                 **{key: raw_player[key] for key in flags if key in raw_player}}
        end = {**destination, "z": raw_destination.get("z", destination.get("z", 0.)),
               "z_known": raw_destination.get("z_known", raw_destination.get("z") is not None),
               **{key: raw_destination[key] for key in flags if key in raw_destination}}
        from wowbot.geometry_contracts import query_path
        result = query_path(self.navmesh, player_instance, start, end)
        self.last_geometry_query = result.diagnostic()
        return result.value if result.ready else None

    def needs_replan(self, route: GlobalRoute | None, request: NavigationRequest, state: dict[str, Any],
                     now: float, *, corridor_invalid: bool = False, local_failures: int = 0,
                     danger_changed: bool = False) -> bool:
        if route is None or now > route.valid_until or corridor_invalid or danger_changed:
            return True
        if local_failures >= self.policy.local_failure_replan_threshold:
            return True
        destination = self._point(request.destination)
        if destination is None or not route.anchors:
            return True
        # Compare with what the route was planned for.  Live 2026-10-05
        # (Hrun's pit): the Detour end differed from the request by 7.5e-5 yd,
        # so every command() replanned and restarted the controller, which
        # reset an ARRIVED phase to MOVING -- the agent turned on the spot on
        # top of its zone-sweep hop for 30 s.
        end = next((item["requested_destination"] for item in route.regions
                    if isinstance(item.get("requested_destination"), dict)), route.anchors[-1])
        if self._distance(end, destination) > 1e-5:
            return True
        route_maps = {item.get("map_id") for item in route.regions if item.get("map_id") is not None}
        current_map = state.get("map_id")
        return bool(route_maps and current_map is not None and current_map not in route_maps)

    @staticmethod
    def _point(value: Any) -> dict[str, float] | None:
        if not isinstance(value, dict):
            return None
        try:
            x, y = float(value["x"]), float(value["y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        point = {"x": x, "y": y}
        if isinstance(value.get("z"), (int, float)) and math.isfinite(float(value["z"])):
            point["z"] = float(value["z"])
        return point

    def _normalise_anchors(self, player: dict[str, float] | None, measured: Iterable[dict[str, Any]],
                           destination: dict[str, float]) -> list[dict[str, float]]:
        anchors: list[dict[str, float]] = [player] if player is not None else []
        for raw in measured:
            point = self._point(raw)
            if point is not None and (not anchors or self._distance(anchors[-1], point) > 1e-5):
                anchors.append(point)
        if not anchors or self._distance(anchors[-1], destination) > 1e-5:
            anchors.append(destination)
        return anchors

    @staticmethod
    def _distance(left: dict[str, float], right: dict[str, float]) -> float:
        return math.hypot(right["x"] - left["x"], right["y"] - left["y"])


# Source-compatible import name; both names refer to the same class/authority.
GlobalPlanner = GlobalNavigator
