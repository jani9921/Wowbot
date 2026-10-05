"""Slow, evidence-bounded global route construction for Navigation V5.

The planner deliberately produces data only.  It does not know about key
bindings, schedules no input and is allowed to run only at request/replan
boundaries.  The service remains the sole owner that can hand a plan to the
movement controller.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Iterable

from .contracts import GlobalRoute, NavigationRequest


@dataclass(frozen=True, slots=True)
class GlobalPlannerPolicy:
    route_ttl_seconds: float = 20.0
    direct_route_confidence: float = 0.45
    measured_route_confidence: float = 0.80
    local_failure_replan_threshold: int = 3
    danger_clearance: float = 2.0
    danger_route_confidence: float = 0.65


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
        destination = self._point(request.destination)
        player = self._point(state.get("player_world_position") or state.get("position") or {})
        if destination is None:
            raise ValueError("navigation request destination requires finite x/y coordinates")
        navmesh_path = self._navmesh_path(request, state, player, destination)
        navmesh_required = bool(request.destination.get("require_navmesh"))
        if navmesh_path is not None:
            anchors = tuple(dict(point) for point in navmesh_path.anchors)
        elif navmesh_required:
            anchors = ()
        else:
            anchors = tuple(self._normalise_anchors(player, measured_anchors, destination))
        measured = len(anchors) > 2
        danger_adapted = False
        use_danger_cost = (danger_map is not None and
                           (request.avoid_combat or danger_map.has_navigation_failures(now)))
        if use_danger_cost and len(anchors) >= 2:
            adapted = danger_map.avoidance_anchors(
                anchors, now, exempt_entity_id=request.target_entity_id,
                clearance=self.policy.danger_clearance,
                walkable=self._detour_validator(state))
            danger_adapted = adapted != anchors
            anchors = adapted
        cost = (danger_map.route_cost(anchors, now, exempt_entity_id=request.target_entity_id)
                if use_danger_cost
                else sum(self._distance(left, right) for left, right in zip(anchors, anchors[1:])))
        map_id = (request.destination.get("map_id") or request.destination.get("ui_map_id")
                  or request.destination.get("world_map_id")
                  or state.get("map_id"))
        regions = ({"map_id": map_id, "kind": "DESTINATION_REGION", "fact": False,
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
        return self.navmesh.find_path(player_instance, start, end)

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
