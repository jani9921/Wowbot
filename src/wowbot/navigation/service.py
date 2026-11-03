"""Canonical telemetry-assisted movement service for the active agent path.

Route knowledge and closed-loop movement are private components.  Callers use
this service, never either component as an independent navigation authority.
"""
from __future__ import annotations

from dataclasses import replace
import math
import time
from pathlib import Path
from typing import Any

from wowbot.agent.movement_controller import (MovementAssessment, MovementPhase, ReachMovementController,
                                              corner_heading)
from wowbot.agent.models import Command, number
from wowbot.agent.navigation import AgentNavigator
from .facing import FaceController
from .navigation_context import NavigationContextAssessment, NavigationContextClassifier
from .navigation_mode import NavigationMode, NavigationModeEvidence, resolve_navigation_mode
from .progress import ProgressMonitor
from .transition_resolver import TransitionAssessment, TransitionResolver
from .stuck_resolver import StuckResolver
from .danger import DangerMap
from .reachability import ReachabilityModel
from .search_coverage import SearchCoveragePlanner
from .contracts import ArrivalEnvelope, GlobalRoute, LocalMotionPlan, NavigationRequest, PathCorridor
from .global_planner import GlobalNavigator
from .corridor import PathCorridorBuilder
from .local_planner import LocalNavigator
from .stuck_classifier import StuckClassifier
from .los_recovery import LosRecoveryPlanner
from wowbot.runtime import world_entity_id
from .navigation_recovery import NavigationRecoveryMixin
from .navigation_combat import CombatLocalPositioningAdapter
from .navigation_search import NavigationSearchMixin
from .z_resolver import ZResolver


class NavigationService(NavigationSearchMixin, NavigationRecoveryMixin):
    def __init__(self, bindings=None, *, navmesh=None) -> None:
        from .travel import TripExecutor
        self.trip = TripExecutor()
        self._routes = AgentNavigator()
        self._progress = ProgressMonitor()
        self._movement = ReachMovementController(bindings, progress_monitor=self._progress)
        self._stuck = StuckResolver()
        self._face = FaceController(bindings)
        self._danger = DangerMap()
        self._reachability = ReachabilityModel()
        self._search_coverage = SearchCoveragePlanner()
        # V4-025/V4-026: evidence-only classifiers, queried on demand.
        # Neither owns any recovery ladder state or issues input; they only
        # help a caller interpret route expectation/arrival/stuck-recovery
        # signals it already has.
        self._navigation_context_classifier = NavigationContextClassifier()
        self._transition_resolver = TransitionResolver()
        # These layers are planning-only.  They are intentionally composed by
        # this service rather than being allowed to acquire their own input
        # lease beside ReachMovementController.
        if isinstance(navmesh, (str, bytes, Path)):
            from wowbot.world_geometry import WorldGeometryService
            navmesh = WorldGeometryService.from_paths(navmesh)
        if navmesh is None:
            from wowbot.world_geometry import WorldGeometryService
            navmesh = WorldGeometryService.from_environment()
        self._navmesh = navmesh
        self._z = ZResolver(navmesh)
        from .hazard_route import HazardAwareRouteValidator
        self.hazard_route = HazardAwareRouteValidator(lambda: self._z, lambda: self._navmesh)
        from .layer_resolver import DestinationLayerResolver
        self.layer_resolver = DestinationLayerResolver(lambda: self._z)
        from .travel_cost import TravelCostQueryPort
        self.travel_cost = TravelCostQueryPort(lambda: self._z, lambda: self._navmesh)
        from .zone_sweep import ZoneSweepGeometry
        from .travel_transitions import TravelTransitionPolicy
        self.travel_transitions = TravelTransitionPolicy(lambda: self._navmesh)
        self.zone_geometry = ZoneSweepGeometry(lambda: self._z, lambda: self._navmesh,
                                               lambda: self.ZONE_SWEEP_HOP_YARDS,
                                               lambda: self.LAYER_CONTINUITY_YARDS)
        # No running jump toward a drop (the controller has no geometry).
        self._movement.__dict__["jump_guard"] = lambda state: self.recovery_step_drops(state, "JUMP_FORWARD")
        self._handled_falls = 0
        # Confirmed falling samples are unsafe route evidence, not merely a
        # 15-second skill retry failure. Keep it across same-context replans.
        from .fall_hazards import FallHazardMemory
        self.fall_hazards = FallHazardMemory()
        # First sample of the current falling episode: (monotonic time, state).
        self._falling_since: tuple[float, dict] | None = None
        self._global_planner = GlobalNavigator(navmesh=self._navmesh, walkable=self.walkable_point)
        self._corridor_builder = PathCorridorBuilder()
        self._local_planner = LocalNavigator()
        self._stuck_classifier = StuckClassifier()
        self._los_recovery = LosRecoveryPlanner()
        self.combat_positioning = CombatLocalPositioningAdapter(
            self._face, self._los_recovery, self._danger,
            lambda *args, **kwargs: self._resolve_entity_destination(*args, **kwargs),
            lambda *args, **kwargs: self._start_entity_request(*args, **kwargs))
        self._active_request: NavigationRequest | None = None
        self._request_started_at: float | None = None
        from .position_acquisition import ServerPositionWait
        self.position_wait = ServerPositionWait()
        self._deferred_request: NavigationRequest | None = None
        self._deferred_scope: tuple | None = None
        self._planning_clock = time.perf_counter
        self._route_feedback = None
        self._route_feedback_trace = None
        self._active_route: GlobalRoute | None = None
        self._active_corridor: PathCorridor | None = None
        self._latest_local_plan: LocalMotionPlan | None = None
        self._route_waypoint_index = 0
        self._route_previous_position: tuple[float, float] | None = None
        self._route_danger_revision = 0
        self._route_failure_reason: str | None = None
        self._latest_surface_projection: dict[str, Any] | None = None
        self._surface_projection_key: tuple | None = None
        self._surface_projection_value: dict[str, Any] | None = None
        # STOP_AND_OBSERVE must be completed from a *new* telemetry sample,
        # not from the progress sample that originally proved the hard stuck.
        # The movement controller is reset after its terminal result, so its
        # ProgressMonitor intentionally becomes empty at that boundary.  Keep
        # only this small recovery observation anchor here; otherwise the
        # resolver can remain in STOP_AND_OBSERVE forever while ordinary
        # visual-search proposals take the execution slot.
        self._stuck_observation_anchor: dict[str, Any] | None = None

    def reset(self, *, keep_floor: bool = False) -> None:
        """Drop route, controller and per-context navigation memory.

        Issue #84: the Z resolver's player-floor/fall/target state and the
        cave sweep/lower-layer caches used to survive session, map, death,
        phase, floor and vehicle invalidations.  ``keep_floor`` is only for a
        goal replacement in the same context, where the player's own floor
        continuity is still valid evidence.
        """
        self.trip.cancel('navigation_reset')
        if not keep_floor:
            self._z = ZResolver(self._z.geometry)
            self._fall_hazards.clear()
        for key in ("_zone_sweeps", "_lower_layer_cache", "_last_sweep_key",
                    "_ambiguous_since", '_flight_departures'):
            self.__dict__.pop(key, None)
        self.travel_transitions.reset()
        self.zone_geometry.reset()
        self._layer_probe = False
        self._routes = AgentNavigator()
        self._progress.clear()
        self._movement.reset()
        self._stuck.reset()
        self._face.reset()
        self._danger.reset()
        self._reachability.reset()
        self._search_coverage.reset()
        self._active_request = None
        self._request_started_at = None
        self._position_wait = None
        self._position_trace = None
        self._deferred_request = self._deferred_scope = None
        self._route_feedback = self._route_feedback_trace = None
        self._active_route = None
        self._active_corridor = None
        self._latest_local_plan = None
        self._route_waypoint_index = 0
        self._route_previous_position = None
        self._route_danger_revision = self._danger.revision
        self._latest_los_recovery = None
        self._route_failure_reason = None
        self._latest_surface_projection = None
        self._surface_projection_key = None
        self._surface_projection_value = None
        self._stuck_observation_anchor = None
        self._falling_since = None
        self._handled_falls = self._z.fall_count
        self.__dict__.pop("_slip_starts", None)
        self.__dict__.pop("_pending_recovery_directive", None)

    def close(self) -> None:
        if self._navmesh is not None:
            self._navmesh.close()

    def cancel_movement(self) -> None:
        self._deferred_request = self._deferred_scope = None
        self._route_feedback = None
        self.position_wait.cancel()
        self.trip.cancel('navigation_cancelled')
        self._movement.reset()
        self.travel_transitions.reset()
        # Recovery observes its own landing while this route is inactive.
        # An old airborne timer is not evidence of a new continuous fall.
        # Confirmed same-context ledge hazards remain in _fall_hazards.
        self._falling_since = None
        self._active_request = None
        self._request_started_at = None
        self._position_wait = None
        self._active_route = None
        self._active_corridor = None
        self._latest_local_plan = None
        self._route_waypoint_index = 0
        self._route_previous_position = None
        self._route_failure_reason = None
        self._latest_surface_projection = None
        self._surface_projection_key = None
        self._surface_projection_value = None

    @property
    def max_reach_seconds(self) -> float:
        return self._movement.max_reach_seconds

    @property
    def phase(self):
        return self._movement.phase

    @property
    def last_command_observation_id(self):
        return self._movement.last_command_observation_id

    def start(self, destination: dict, state: dict, observation_id: str, now: float, *,
              continuing: bool = False) -> None:
        self._movement.start(destination, state, observation_id, now, continuing=continuing)

    @staticmethod
    def _already_arrived(request: NavigationRequest, state: dict) -> bool:
        """Within arrival distance without a contradictory measured floor."""
        from wowbot.agent.destination_distance import other_level
        destination = request.destination
        if (state.get('is_ghost') is True and destination.get('purpose') == 'CORPSE_RUN'
                and destination.get('flight') is True):
            # A failed flight plan at the body's XY cannot prove touchdown.
            return False
        player = state.get("player_world_position") or {}
        if (destination.get("coordinate_space") != "WORLD_YARDS"
                or player.get("coordinate_space") != "WORLD_YARDS"
                or destination.get("instance_id") not in (None, player.get("instance_id"))
                or other_level(state, destination)):
            return False
        if (destination.get("z_known") is True
                and destination.get('z_knowledge_priority', destination.get("knowledge_priority"))
                in {"PRIMARY_STATIC", "SERVER_POI"}):
            target_z, own_z = number(destination.get("z")), number(player.get("observed_z", player.get("z")))
            if target_z is not None and (own_z is None or abs(target_z-own_z) > 12.):
                return False
        limit = next((number(value) for value in (
            request.arrival.radius, request.arrival.desired_range, destination.get("stop_distance"))
            if number(value) is not None), None)
        dx = (number(destination.get("x")) or 0.) - (number(player.get("x")) or 0.)
        dy = (number(destination.get("y")) or 0.) - (number(player.get("y")) or 0.)
        return (limit is not None and None not in (number(player.get("x")), number(destination.get("x")))
                and math.hypot(dx, dy) <= limit)

    def start_request(self, request: NavigationRequest, state: dict, now: float, *,
                      continuing: bool = False) -> None:
        started = self._planning_clock()
        self._route_feedback = None
        if self._route_feedback_trace and self._route_feedback_trace['request_id']!=request.request_id:
            self._route_feedback_trace=None
        self._start_request(request, state, now, continuing=continuing)
        self._require_post_plan_feedback(state, now, self._planning_clock()-started)

    def _start_request(self, request: NavigationRequest, state: dict, now: float, *,
                       continuing: bool = False) -> None:
        """Accept one typed request and delegate all control to the existing controller."""
        self._deferred_request = self._deferred_scope = None
        self.trip.start(request, now, continuing=continuing)
        self.trip.transitions.observe(state, now)
        self.position_wait.forget_other(request.request_id)
        from .position_acquisition import required as position_required
        floor = None
        if position_required(request.destination, state):
            # Live 2026-11-02 (Jangolode, 613-651 s): with the probe tap on
            # cooldown nothing could bring the server height, yet every MOVE
            # waited its 3 s and failed POSITION_UNCERTAIN -- ten times.  On a
            # single navmesh floor that floor is our height; a layered spot
            # (bridge, cave, wall) still waits for the server.
            point = state.get("player_world_position") or {}
            floor = (None if self._movement.height_probe_available(now) else
                     self._z.single_floor_height(point.get("instance_id"), point.get("x"), point.get("y")))
            if floor is not None:
                state = {**state, "player_world_position": {
                    **point, "z": floor, "z_known": True, "z_source": "NAVMESH_SINGLE_FLOOR"}}
        if floor is None and position_required(request.destination, state):
            same = bool(self._position_wait and self._active_request
                        and self._active_request.request_id == request.request_id)
            if not same:
                if self._active_request is None or self._active_request.request_id != request.request_id:
                    self._request_started_at = now
                self.position_wait.begin(request.request_id, state, now, min(
                    self.POSITION_ACQUISITION_SECONDS, request.timeout or self.max_reach_seconds))
                self._movement.prepare_position_probe(request.destination, now)
            self._active_request = request
            self._active_route = self._active_corridor = self._latest_local_plan = None
            self._route_waypoint_index = 0
            self._route_previous_position = None
            self._route_failure_reason = None
            return
        self._position_wait = None
        departure = request.destination.get('flight_departure')
        if departure and self._departure_flight_ready(state, departure.get('flight_style')):
            request = replace(request, destination=self.travel_transitions.flight_destination(
                request.destination, departure['flight_style']))
        if request.destination.get("flight_path"):
            from .flight_path import FlightPath, grounded
            path = FlightPath.from_dict(request.destination["flight_path"])
            if str((state.get("player_world_position") or {}).get("instance_id")) != str(path.instance_id):
                raise ValueError("Flight path belongs to another instance")
            if grounded(state, now) and path.air_segment_complete(state):
                request = self._ground_request(request, path)
        if self._active_request is None or self._active_request.request_id != request.request_id:
            self._request_started_at = now
        if (state.get("movement") or {}).get("falling") is False:
            self._falling_since = None
        self._z.observe_player(state, now)
        state = self._state_with_layer_continuity(state, now)
        # Never let a target from an earlier request authorize this route.
        self._z.last_target = None
        request = self._resolve_destination_z(request, state, now)
        if (request.destination.get("purpose") == "APPROACH_MINIMAP_OTHER_FLOOR_OBJECTIVE"
                and request.destination.get("floor_hint") == "BELOW"):
            target = self._z.last_target if request.destination.get("z_resolved_from") else None
            indoors = (state.get("movement") or {}).get("indoors")
            if self._z.bootstrap_player_from_down_cue(
                    target, observed_at=number(request.destination.get("floor_cue_observed_at")),
                    indoors=indoors if isinstance(indoors, bool) else None, now=now):
                state = self._state_with_layer_continuity(state, now)
        self._active_request = request
        player_layer = self._z.player
        self._layer_probe = False
        probe_route = None
        if (request.destination.get("coordinate_space") == "WORLD_YARDS"
                and request.destination.get("require_navmesh")
                and player_layer is not None and player_layer.confidence < .6):
            # A low-confidence player floor never seeds a full 3D route.  But
            # only motion can resolve it: walk a short leg from the likeliest
            # hypothesis that has a route; fail closed when none has.
            probe = self._ambiguous_layer_probe(request, state, player_layer, now)
            if probe is None:
                self._active_route = None
                self._route_failure_reason = "ambiguous_player_layer"
                self._movement.reset()
                return
            state, probe_route = probe
            self._layer_probe = True
        if request.destination.get("z_resolution_failed"):
            self._active_route = None
            self._route_failure_reason = str(request.destination["z_resolution_failed"])
            self._movement.reset()
            return
        self._danger.observe_hostiles(state, now)
        self._observe_spawn_threats(request, state, now)
        # Planned from a guessed floor: the first server height answers it.
        self._route_own_z_unobserved = (state.get("player_world_position") or {}).get("z_observed") is not True
        self._active_route = self._away_from_drops(
            probe_route if probe_route is not None else
            self._global_planner.plan(request, state, now, danger_map=self._danger))
        if self._fall_hazard_blocks(self._active_route, state, now):
            self._active_route = replace(self._active_route, anchors=())
            self._route_failure_reason = "fall_hazard_on_route"
            self._movement.reset()
            return
        self._active_route = self._bounded_localization_route(self._active_route)
        self.trip.route(self._active_route, request,
                        geometry_revision=getattr(self._navmesh, 'revision', None),
                        risk_revision=self._danger.revision, state=state)
        self._route_danger_revision = self._danger.revision
        self._route_waypoint_index = self._first_route_index(state)
        self._route_previous_position = self._player_route_position(state)
        self._active_corridor = self._corridor_builder.build(self._active_route)
        state = self._state_with_navmesh_surface(state)
        self._latest_local_plan = self._local_planner.plan(
            state, self._active_corridor, destination=request.destination)
        if not self._active_route.anchors:
            if self._already_arrived(request, state):
                # Standing at the destination needs no route: a missing
                # navmesh path must not turn an arrival into a failure.
                self._route_failure_reason = None
                self.start(dict(request.destination), state, request.correlation_id, now)
                return
            flight_failure = next((region.get('flight_plan_status')
                                   for region in self._active_route.regions
                                   if region.get('route_source') == 'FLIGHT_PLAN'), None)
            self._route_failure_reason = ('flight_plan_' + str(flight_failure) if flight_failure
                                          else "required_navmesh_route_unavailable")
            self._movement.reset()
            return
        self._route_failure_reason = None
        destination = self._current_route_destination()
        self.start(destination, state, request.correlation_id, now, continuing=continuing)

    # Live 2026-10-04 00:41: Detour's first corner lay 1.1 yd from the player.
    # Every replan (the danger map changes with nearby mobs) restarted the
    # route at that corner, which counted as arrived at once, so the next
    # waypoint was never steered to and the character stood still.
    ROUTE_START_SKIP_YARDS = 3.0
    WAYPOINT_LAYER_YARDS = 6.
    # User 2026-10-06: "a spirálon ... eléggé a szélén megy".  Taking a
    # waypoint 2.5 yd early cut every bend of the spiral toward the drop.
    INTERMEDIATE_PASS_YARDS = 1.5
    # FAST position samples are frequent enough to require the actual bend.
    # Looking four legs ahead allowed a spiral chord to be treated as passed
    # while the character was still cutting across the ledge (2026-10-07).
    NEXT_LEG_YARDS = 1.25
    NEXT_LEG_LOOKAHEAD = 1
    # Live 2026-10-14 13:35:16-13:35:56 (Hrun's pit): a spiral corner anchor
    # stayed 1.6-1.7 yd away for 40 s.  Something at the corner kept the
    # character just outside the 1.5 yd pass radius, the wall-contact check
    # is off that close to a destination, and position jitter kept resetting
    # the no-progress evidence.  A near intermediate anchor that stops getting
    # closer is passed -- only if the next leg is walkable from here.
    STALL_PASS_YARDS = 4.5
    STALL_PASS_SECONDS = 2.
    STALL_IMPROVEMENT_YARDS = .3
    LEG_CHECK_STEP_YARDS = 1.
    LEG_CHECK_SIDE_YARDS = 1.
    LEG_CHECK_HEIGHT_YARDS = 2.5

    def _intermediate_waypoint_stalled(self, state: dict, now: float) -> bool:
        route, index = self._active_route, self._route_waypoint_index
        if route is None or not route.anchors or index >= len(route.anchors)-1:
            self.__dict__["_waypoint_stall"] = None
            return False
        current = self._player_route_position(state)
        waypoint = route.anchors[index]
        wx, wy = number(waypoint.get("x")), number(waypoint.get("y"))
        if current is None or wx is None or wy is None:
            return False
        distance = math.hypot(current[0]-wx, current[1]-wy)
        key = (route.route_id, index)
        stall = self.__dict__.get("_waypoint_stall")
        if stall is None or stall[0] != key or distance < stall[1]-self.STALL_IMPROVEMENT_YARDS:
            self.__dict__["_waypoint_stall"] = (key, distance, now)
            return False
        if distance > self.STALL_PASS_YARDS or now-stall[2] < self.STALL_PASS_SECONDS:
            return False
        resolved, wz = self._z.player, number(waypoint.get("z"))
        if (resolved is not None and wz is not None and resolved.confidence >= .7
                and abs(resolved.z-wz) > self.WAYPOINT_LAYER_YARDS):
            return False
        following = route.anchors[index+1]
        start_z = resolved.z if resolved is not None and resolved.confidence >= .5 else wz
        instance_id = waypoint.get("instance_id") or (state.get("player_world_position") or {}).get("instance_id")
        try:
            start = (current[0], current[1], float(start_z))
            end = (float(following["x"]), float(following["y"]), float(following["z"]))
            instance_id = int(instance_id)
        except (KeyError, TypeError, ValueError):
            return False
        if not self._leg_walkable(instance_id, start, end):
            return False
        self.__dict__["_waypoint_stall"] = None
        return True

    def _leg_walkable(self, instance_id: int, start: tuple, end: tuple) -> bool:
        """A walkable surface at the leg's height along it and 1 yd to each
        side (no bend cut over a drop)."""
        (x0, y0, z0), (x1, y1, z1) = start, end
        length = math.hypot(x1-x0, y1-y0)
        if length <= 1e-6:
            return True
        nx, ny = -(y1-y0)/length, (x1-x0)/length
        steps = max(1, int(length // self.LEG_CHECK_STEP_YARDS))
        for k in range(steps+1):
            t = k/steps
            x, y, z = x0+(x1-x0)*t, y0+(y1-y0)*t, z0+(z1-z0)*t
            for side in (0., self.LEG_CHECK_SIDE_YARDS, -self.LEG_CHECK_SIDE_YARDS):
                layers = self._z._layers_at(instance_id, x+nx*side, y+ny*side)
                if not any(abs(height-z) <= self.LEG_CHECK_HEIGHT_YARDS for height in layers):
                    return False
        return True

    # User 2026-10-20 ("csináld meg mind", after PixelBuddy's controller):
    # lean toward the next waypoint before a bend (``corner_heading``), but
    # only where that very law, simulated from the window's start until the
    # bend counts as passed, stays on walkable ground at the legs' height
    # along the path and 1 yd to each side.  The pit spiral's inside is a
    # drop: there no window is granted and the bend is taken as before.
    CORNER_WINDOW_YARDS = 10.
    CORNER_MIN_YARDS = 2.
    CORNER_STEP_YARDS = .5
    MOUNTED_PASS_YARDS = 3.

    # User 2026-10-20 ("csináld meg mind", after PixelBuddy's path service):
    # hostile elites, rares and mob clusters on the way are danger for every
    # trip that is not for combat; single mobs only when it avoids combat.
    # Quest objective creatures, turn-in/objective NPCs and the trip's own
    # target are never threats.  Unknown data (no TDB / DB2) adds nothing.
    SPAWN_THREAT_TTL = 600.
    SPAWN_THREAT_MARGIN = (40., .25, 150.)   # base, share of the distance, cap

    def _observe_spawn_threats(self, request: NavigationRequest, state: dict, now: float) -> None:
        if request.allow_combat:
            return
        threats = self._spawn_threat_source()
        player = state.get("player_world_position") or {}
        destination = request.destination
        px, py = number(player.get("x")), number(player.get("y"))
        dx, dy = number(destination.get("x")), number(destination.get("y"))
        instance = destination.get("instance_id", player.get("instance_id"))
        if (threats is None or None in (px, py, dx, dy, instance)
                or str(instance) != str(player.get("instance_id"))
                or destination.get("coordinate_space") != "WORLD_YARDS"):
            return
        from wowbot.agent.packet_entity_facts import kill_objective_entries
        from wowbot.agent.server_npc_planning import objective_npc_entries, turn_in_entries
        exempt = {*kill_objective_entries(state), *objective_npc_entries(state), *turn_in_entries(state)}
        if destination.get("npc_id") is not None:
            exempt.add(str(destination["npc_id"]))
        live = self._live_units(state)
        base, share, cap = self.SPAWN_THREAT_MARGIN
        margin = min(cap, base + share*math.hypot(dx-px, dy-py))
        try:
            entries = threats.dangers(int(instance), (px, py), (dx, dy), margin=margin,
                                      race=state.get("race"), include_single=bool(request.avoid_combat),
                                      exempt_npc_ids={int(npc) for npc in exempt if str(npc).isdigit()},
                                      live_units=live)
        except Exception as error:      # a broken reference must not stop walking
            self.__dict__["spawn_threat_error"] = f"{type(error).__name__}: {error}"
            return
        for entry in entries:
            self._danger.add(**entry, now=now, ttl=self.SPAWN_THREAT_TTL)

    def _spawn_threat_source(self):
        if "_spawn_threats" not in self.__dict__:
            from .spawn_threats import SpawnThreats
            self._spawn_threats = SpawnThreats.from_environment(self.__dict__.get("learned_world_path"))
        return self._spawn_threats

    @staticmethod
    def _live_units(state: dict) -> list[tuple]:
        """(entry, x, y, z) of the living creatures the server shows."""
        from wowbot.agent.packet_entity_facts import UNIT_LOOTABLE, best_position
        live = []
        for value in (state.get("packet_entities") or {}).values():
            if (not isinstance(value, dict) or value.get("kind") != "CREATURE" or value.get("removed")
                    or int(number((value.get("dynamic_flags") or {}).get("value")) or 0) & UNIT_LOOTABLE):
                continue
            point = best_position(value)
            if point is not None and value.get("entry_id") is not None:
                live.append((value["entry_id"], point["x"], point["y"], point.get("z") or 0.))
        return live

    def hostile_units(self, state: dict, center: dict, radius: float = 60.) -> list[dict]:
        """Planning-only: hostile creatures (live, else TDB/learned spawns)
        within ``radius`` of a point -- e.g. the corpse before resurrecting."""
        from .spawn_threats import LIVE_REPLACES_YARDS, side_template
        threats = self._spawn_threat_source()
        cx, cy = number(center.get("x")), number(center.get("y"))
        instance = center.get("instance_id")
        if threats is None or None in (cx, cy, instance):
            return []
        side = side_template(state.get("race"))
        try:
            live = threats.live_threats(self._live_units(state), (cx, cy), (cx, cy), radius, side=side)
            static = [spawn for spawn in threats.near_segment(int(instance), (cx, cy), (cx, cy), radius, side=side)
                      if not any(unit.npc_id == spawn.npc_id
                                 and math.hypot(unit.x-spawn.x, unit.y-spawn.y) <= LIVE_REPLACES_YARDS
                                 for unit in live)]
        except Exception as error:      # a broken reference must not stop recovery
            self.__dict__["spawn_threat_error"] = f"{type(error).__name__}: {error}"
            return []
        return [{"x": unit.x, "y": unit.y, "npc_id": unit.npc_id, "classification": unit.classification,
                 "live": unit in live} for unit in (*live, *static)]

    def _corner_window(self, index: int) -> float:
        route, request = self._active_route, self._active_request
        if route is None or request is None or not 0 < index < len(route.anchors)-1:
            return 0.
        cache = self.__dict__.setdefault("_corner_windows", {})
        key = (route.route_id, index)
        if key not in cache:
            try:
                instance_id = int(request.destination.get("instance_id"))
                legs = tuple(self._xyz(route.anchors[k]) for k in (index-1, index, index+1))
            except (KeyError, TypeError, ValueError):
                cache[key] = 0.
            else:
                cache[key] = self._safe_corner_window(instance_id, *legs)
        return cache[key]

    def _safe_corner_window(self, instance_id: int, previous: tuple, corner: tuple,
                            following: tuple) -> float:
        incoming = math.hypot(corner[0]-previous[0], corner[1]-previous[1])
        outgoing = math.hypot(following[0]-corner[0], following[1]-corner[1])
        window = min(self.CORNER_WINDOW_YARDS, .5*incoming, .5*outgoing)
        if window < self.CORNER_MIN_YARDS:
            return 0.
        x = corner[0] + (previous[0]-corner[0])*window/incoming
        y = corner[1] + (previous[1]-corner[1])*window/incoming
        vx, vy = following[0]-corner[0], following[1]-corner[1]
        path = []
        for _ in range(int(4*window/self.CORNER_STEP_YARDS)):
            heading = corner_heading((x, y), corner[:2], following[:2], window)
            x, y = x + self.CORNER_STEP_YARDS*math.cos(heading), y + self.CORNER_STEP_YARDS*math.sin(heading)
            path.append((x, y, heading))
            t = ((x-corner[0])*vx + (y-corner[1])*vy) / (outgoing*outgoing)
            if (math.hypot(x-corner[0], y-corner[1]) <= self.INTERMEDIATE_PASS_YARDS
                    or (0. < t <= 1. and abs((x-corner[0])*vy - (y-corner[1])*vx)/outgoing
                        <= self.NEXT_LEG_YARDS)):
                break
        else:
            return 0.
        for x, y, heading in path:
            z = self._corner_height(x, y, previous, corner, following)
            nx, ny = -math.sin(heading), math.cos(heading)
            for side in (0., self.LEG_CHECK_SIDE_YARDS, -self.LEG_CHECK_SIDE_YARDS):
                layers = self._z._layers_at(instance_id, x+nx*side, y+ny*side)
                if not any(abs(height-z) <= self.LEG_CHECK_HEIGHT_YARDS for height in layers):
                    return 0.
        return window

    @staticmethod
    def _corner_height(x: float, y: float, previous: tuple, corner: tuple, following: tuple) -> float:
        """Height of the nearer leg at the point's projection onto it."""
        best = None
        for a, b in ((previous, corner), (corner, following)):
            vx, vy = b[0]-a[0], b[1]-a[1]
            t = max(0., min(1., ((x-a[0])*vx + (y-a[1])*vy) / max(1e-9, vx*vx + vy*vy)))
            gap = math.hypot(a[0]+t*vx-x, a[1]+t*vy-y)
            if best is None or gap < best[0]:
                best = (gap, a[2] + t*(b[2]-a[2]))
        return best[1]

    def _on_next_leg(self, current: tuple[float, float], wx: float, wy: float) -> bool:
        """Already walking a following leg: the waypoint was passed between
        samples (never turn back to it; live 21:29 turned back and forth).
        A leg on another floor of the spiral (same X/Y) does not count."""
        route, index = self._active_route, self._route_waypoint_index
        if route is None or index+1 >= len(route.anchors):
            return False
        resolved = self._z.player
        player_z = resolved.z if resolved is not None and resolved.confidence >= .7 else None
        anchors = route.anchors
        for k in range(index, min(len(anchors)-1, index+self.NEXT_LEG_LOOKAHEAD)):
            ax, ay = number(anchors[k].get("x")), number(anchors[k].get("y"))
            bx, by = number(anchors[k+1].get("x")), number(anchors[k+1].get("y"))
            if None in (ax, ay, bx, by):
                return False
            vx, vy = bx-ax, by-ay
            length_sq = vx*vx + vy*vy
            if length_sq <= 1e-6:
                continue
            t = ((current[0]-ax)*vx + (current[1]-ay)*vy) / length_sq
            if not (0. < t <= 1. if k == index else 0. <= t <= 1.):
                continue
            if math.hypot(ax+t*vx-current[0], ay+t*vy-current[1]) > self.NEXT_LEG_YARDS:
                continue
            az, bz = number(anchors[k].get("z")), number(anchors[k+1].get("z"))
            if (player_z is not None and az is not None and bz is not None
                    and abs(az+t*(bz-az)-player_z) > self.WAYPOINT_LAYER_YARDS):
                continue
            return True
        return False

    def _first_route_index(self, state: dict) -> int:
        """First route anchor to steer to: skip anchors under the player's feet."""
        route = self._active_route
        if route is None or len(route.anchors) <= 1:
            return 0
        final_index = len(route.anchors)-1
        index = 1
        current = self._player_route_position(state)
        while index < final_index and current is not None:
            anchor = route.anchors[index]
            ax, ay = number(anchor.get("x")), number(anchor.get("y"))
            if ax is None or ay is None or math.hypot(ax-current[0], ay-current[1]) > self.ROUTE_START_SKIP_YARDS:
                break
            index += 1
        return index

    def _current_route_destination(self) -> dict:
        request = self._active_request
        route = self._active_route
        if request is None or route is None or not route.anchors:
            return {}
        final_index = len(route.anchors)-1
        index = min(max(0, self._route_waypoint_index), final_index)
        anchor = route.anchors[index]
        # The last anchor of a localization probe is not the request's goal.
        final = (index == final_index and not self._partial_localization_route(route)
                 and not self._departure_active())
        destination = {
            **request.destination,
            "x": anchor["x"], "y": anchor["y"],
            "target_guid": request.target_entity_id if final else None,
            "avoid_combat": request.avoid_combat,
            "allow_combat": request.allow_combat,
            "route_id": route.route_id,
            "route_waypoint_index": index,
            "route_waypoint_final": final,
            # Navmesh polygon height of this anchor: the layer to arrive on.
            "layer_z": anchor.get("z") if anchor.get("source") == "TRINITYCORE_MMAP" else None,
        }
        if request.destination.get('entity_goal') is True:
            destination['entity_route_anchor'] = True
            if destination.get('layer_z') is None:
                if final and number(request.destination.get('layer_z')) is not None:
                    destination['layer_z'] = request.destination['layer_z']
                else:
                    destination.pop('layer_z', None)
            if not final:
                for key in ('server_entity_guid', 'interaction_recipient_guid', 'face_on_arrival'):
                    destination.pop(key, None)
        if anchor.get("flight_plan"):
            destination["flight_plan"] = anchor["flight_plan"]
            destination["z"] = anchor.get("z")
        anchor_z = number(anchor.get("z"))
        if anchor_z is not None and not final:
            # The waypoint's own floor, not the final target's height (live
            # 21:29: arrival measured 15.9 yd in 3D to a point 1 yd away).
            destination["z"] = anchor_z
        if not final:
            destination.pop("stop_distance", None)
            destination.pop("arrival_radius", None)
            destination["purpose"] = "ROUTE_WAYPOINT"
            destination["arrival_radius"] = self.INTERMEDIATE_PASS_YARDS
            if index < final_index:
                following = route.anchors[index+1]
                destination["corner_next"] = {"x": following["x"], "y": following["y"]}
                destination["corner_blend_yards"] = self._corner_window(index)
        else:
            if request.destination.get("face_on_arrival"):
                # The navmesh can project the endpoint beside/inside the
                # actor's interaction radius. Walk to that safe anchor but
                # face the actual NPC/mob/object, not the projected point.
                point = request.destination.get("face_towards") or request.destination
                destination["face_towards"] = {key: point[key] for key in
                    ("x", "y", "z", "instance_id") if key in point}
            if request.arrival.radius is not None:
                destination["arrival_radius"] = request.arrival.radius
            if request.arrival.desired_range is not None:
                destination["stop_distance"] = request.arrival.desired_range
            if request.destination.get('entity_goal') is True:
                from .entity_goal import anchor_tolerance
                desired=self._interaction_band(request)
                tolerance=anchor_tolerance(request.destination,anchor,desired)
                destination.update(stop_distance=tolerance,arrival_radius=tolerance)
        return destination

    @staticmethod
    def _player_route_position(state: dict) -> tuple[float, float] | None:
        position = state.get("player_world_position") or {}
        x, y = number(position.get("x")), number(position.get("y"))
        return (x, y) if x is not None and y is not None else None

    def _intermediate_waypoint_passed(self, state: dict) -> bool:
        """Accept a traversed corridor anchor even if no sample landed on it.

        Intermediate mmap anchors are routing geometry, not interaction
        destinations.  With a 3--8 Hz consumer the character can cross the
        controller's 4.5-yard arrival circle between two valid FAST samples.
        Reversing toward such an already crossed anchor creates the observed
        back-and-forth loop.  A bounded segment/circle test closes that gap;
        the final destination still uses the normal evidence-based verifier.
        """
        route = self._active_route
        if (route is None or not route.anchors
                or self._route_waypoint_index >= len(route.anchors)-1):
            return False
        current = self._player_route_position(state)
        previous = self._route_previous_position
        if current is None:
            return False
        self._route_previous_position = current
        waypoint = route.anchors[self._route_waypoint_index]
        wx, wy = number(waypoint.get("x")), number(waypoint.get("y"))
        if wx is None or wy is None:
            return False
        resolved, wz = self._z.player, number(waypoint.get("z"))
        if (resolved is not None and wz is not None and resolved.confidence >= .7
                and abs(resolved.z - wz) > self.WAYPOINT_LAYER_YARDS):
            # A waypoint above/below us on the spiral is not passed in 2D.
            return False
        # Six yards is deliberately limited to intermediate anchors.  It is
        # large enough for measured live sampling gaps while remaining much
        # smaller than ordinary mmap anchor spacing.
        # Live 2026-10-06: 6 yd made the controller aim two waypoints ahead on
        # Hrun's spiral and cut the bend over the drop.  The FAST lane samples
        # ~25 Hz and the segment test below catches a crossed waypoint.
        pass_radius = self.INTERMEDIATE_PASS_YARDS
        if state.get("is_mounted") is True and self._corner_window(self._route_waypoint_index) > 0:
            # Mounted the run is twice as fast; a safe bend may be passed wider.
            pass_radius = self.MOUNTED_PASS_YARDS
        if math.hypot(current[0]-wx, current[1]-wy) <= pass_radius:
            return True
        if self._on_next_leg(current, wx, wy):
            return True
        if previous is None or previous == current:
            return False
        vx, vy = current[0]-previous[0], current[1]-previous[1]
        length_sq = vx*vx + vy*vy
        # Do not turn a teleport/map correction into route progress.
        if length_sq <= 1e-9 or length_sq > 40.0*40.0:
            return False
        t = ((wx-previous[0])*vx + (wy-previous[1])*vy) / length_sq
        if not 0.0 <= t <= 1.0:
            return False
        closest_x, closest_y = previous[0]+t*vx, previous[1]+t*vy
        return math.hypot(closest_x-wx, closest_y-wy) <= pass_radius

    def start_skill_request(self, skill: str, destination: dict, state: dict,
                            observation_id: str, now: float) -> None:
        """Adapt a canonical MOVE/FOLLOW proposal once at skill start.

        This is a transition adapter, not a second planner.  Existing skills
        still supply the validated destination and the persistent controller
        still owns every physical movement command after this call.
        """
        modes = {"MOVE": "MOVE_TO_LOCATION", "REACH_LOCATION": "MOVE_TO_LOCATION",
                 "REACH_OBJECT": "APPROACH_ENTITY", "FOLLOW": "FOLLOW_ENTITY"}
        mode = modes.get(str(skill))
        if mode is None or number(destination.get("x")) is None or number(destination.get("y")) is None:
            self.start(destination, state, observation_id, now)
            return
        stop_distance = number(destination.get("stop_distance"))
        request = NavigationRequest(
            request_id=f"navigation:{skill}:{observation_id}",
            correlation_id=observation_id,
            mode=mode,
            destination=dict(destination),
            target_entity_id=str(destination.get("target_guid") or destination.get("follow_entity_guid") or "") or None,
            arrival=ArrivalEnvelope(radius=number(destination.get("arrival_radius")), desired_range=stop_distance),
            avoid_combat=bool(destination.get("avoid_combat", False)),
            allow_combat=bool(destination.get("allow_combat", False)),
            priority=int(destination.get("priority") or 0),
            timeout=number(destination.get("timeout")),
        )
        self.start_request(request, state, now)

    def local_plan(self, state: dict, *, now: float,
                   observation_id: str | None = None) -> LocalMotionPlan | None:
        started=self._planning_clock()
        result=self._local_plan(state,now=now,observation_id=observation_id)
        self._require_post_plan_feedback(state,now,self._planning_clock()-started)
        return result

    def _local_plan(self, state: dict, *, now: float,
                    observation_id: str | None = None) -> LocalMotionPlan | None:
        """Refresh a read-only local plan for the current route/corridor.

        This is deliberately called by the navigation owner.  The returned
        plan is not a command and cannot bypass the movement controller.
        A confirmed central obstruction asks for a local replan; it does not
        infer a fake world-space detour from screen pixels.
        """
        if (self._active_request is None or self._route_failure_reason
                or self._position_wait is not None or self._deferred_request is not None or self._route_feedback is not None):
            return None
        state = self._state_with_navmesh_surface(state)
        self._danger.observe_hostiles(state, now)
        danger_changed = self._danger.revision != self._route_danger_revision
        if self._global_planner.needs_replan(
                self._active_route, self._active_request, state, now,
                danger_changed=danger_changed):
            self._active_route = self._away_from_drops(self._global_planner.plan(
                self._active_request, state, now, danger_map=self._danger))
            self._active_route = self._bounded_localization_route(self._active_route)
            if self._fall_hazard_blocks(self._active_route, state, now):
                self._route_failure_reason = "fall_hazard_on_route"
                self._movement.reset()
                self._latest_local_plan = None
                return None
            self._route_danger_revision = self._danger.revision
            self._route_waypoint_index = self._first_route_index(state)
            self._route_previous_position = self._player_route_position(state)
            self._active_corridor = self._corridor_builder.build(self._active_route)
            if not self._active_route.anchors:
                # Issue #83: the replan may lose the navmesh route; never
                # start({}) (KeyError) -- fail closed like start_request.
                self._route_failure_reason = "required_navmesh_route_unavailable"
                self._movement.reset()
                self._latest_local_plan = None
                return None
            self.start(self._current_route_destination(), state,
                       observation_id or f"route-replan:{now:.6f}", now)
        self._latest_local_plan = self._local_planner.plan(
            state, self._active_corridor, destination=self._active_request.destination)
        return self._latest_local_plan

    def move_to_entity(self, state: dict, entity_ref: str | None, observation_id: str,
                       now: float, *, stop_distance: float = 4.5,
                       allow_dead: bool = False, recipient: str = "TARGET",
                       defer_plan: bool = False, deadline: float | None = None) -> dict | None:
        """Start or refresh one canonical reach attempt for a selected entity.

        This is intentionally the only entity-approach entry point.  It
        accepts an exact, currently selected entity plus simultaneous world
        positions; it never extrapolates a screen pixel into world space.
        Callers retain ownership of their skill FSM while this service owns
        the movement controller and route knowledge.
        """
        destination = self._resolve_entity_destination(state, entity_ref, now,
            stop_distance=stop_distance, allow_dead=allow_dead, recipient=recipient)
        if deadline is not None:
            deadline = number(deadline)
            if deadline is None:
                return None
        if destination is None or deadline is not None and now >= deadline:
            return None
        destination.update(entity_goal=True, allow_dead=allow_dead)
        self._start_entity_request(destination, state, observation_id, now,
                                   defer_plan=defer_plan, deadline=deadline)
        return destination

    def _start_entity_request(self, destination, state, observation_id, now, *,
                              defer_plan=False, deadline=None, mode='APPROACH_ENTITY'):
        allow_combat = bool(destination.get('allow_combat') or state.get('is_in_combat'))
        request = NavigationRequest(f'entity:{observation_id}', observation_id, mode,
            dict(destination), target_entity_id=str(destination.get('interaction_recipient_guid')
                or destination.get('target_guid') or '') or None,
            arrival=ArrivalEnvelope(desired_range=float(destination.get('stop_distance',4.5))),
            avoid_combat=bool(destination.get('avoid_combat')) and not allow_combat,
            allow_combat=allow_combat,
            priority=90 if mode == 'REPOSITION_FOR_LOS' else 0,
            timeout=min(self.max_reach_seconds, deadline-now) if deadline is not None else self.max_reach_seconds)
        if defer_plan:
            from .position_acquisition import scope
            self.cancel_movement()
            self.trip.start(request, now)
            self._active_request = self._deferred_request = request
            self._deferred_scope = scope(state)
            self._request_started_at = now
        else:
            self.start_request(request, state, now)

    def _resolve_entity_destination(self, state, entity_ref, now, *, stop_distance=4.5,
                                    allow_dead=False, recipient='TARGET'):
        expected = world_entity_id(entity_ref)
        target = state.get("target") or {}
        from wowbot.runtime.entity_identity import check_entity_identity
        from wowbot.agent.packet_entity_facts import interaction_position
        from wowbot.runtime.skill_identity import check_interaction_recipient, soft_interact, sample_fresh
        packet_point = interaction_position(state, expected, allow_dead=allow_dead)
        soft = recipient == "SOFT_INTERACT"
        # The selected Retail UnitPosition may contain a plausible XY but a
        # frozen/zero height. A current exact same-world server actor supplies
        # the approach pose even when the addon position is nonempty.
        server_target = recipient == "TARGET" and packet_point is not None
        if soft or server_target:
            if not expected or packet_point is None or not self._reachability.permits(expected, now):
                return None
            if soft:
                if (soft_interact(state) is None
                        or not check_interaction_recipient({"guid": expected}, state, now)):
                    return None
            elif (not check_entity_identity({"guid": expected}, target)
                  or not sample_fresh(state, "target", now)):
                return None
            destination = {
                **{key: packet_point[key] for key in ("x", "y", "z", "instance_id", "coordinate_space")},
                "z_known": True, "z_source": "PACKET_ENTITY", "layer_z": packet_point["z"],
                "purpose": "INTERACT", "face_on_arrival": True,
                "server_entity_guid": str(expected), "interaction_recipient_guid": str(expected),
                "interaction_identity_source": recipient, "require_navmesh": True,
                "stop_distance": float(stop_distance),
            }
            return destination
        if recipient != "TARGET":
            return None
        if not expected or not check_entity_identity({"guid": expected}, target):
            return None
        if not self._reachability.permits(expected, now):
            return None
        if target.get("dead", target.get("is_dead")) and not allow_dead:
            return None
        player = state.get("player_world_position") or {}
        position = target.get("world_position") or {}
        # Transport publishes this alongside the target projection.  When it
        # is available, a coordinate is actionable only within the same short
        # telemetry window; a retained target position must never launch a
        # fresh reach attempt after the target has moved or disappeared.
        sample_at = number(position.get("sample_time", target.get("sample_time", state.get("target_sample_time"))))
        state_at = number(state.get("monotonic_time"))
        state_at = now if state_at is None else state_at
        if sample_at is not None and not (0. <= state_at-sample_at <= 1.5):
            return None
        px, py = number(player.get("x")), number(player.get("y"))
        tx, ty = number(position.get("x")), number(position.get("y"))
        if None in {px, py, tx, ty}:
            return None
        player_instance = player.get("instance_id")
        target_instance = position.get("instance_id")
        if (player_instance is not None and target_instance is not None
                and player_instance != target_instance):
            return None
        # Issue #101: a trusted target height becomes the arrival layer, so
        # the controller's vertical check refuses "ARRIVED" one floor away
        # (same X/Y).  An untrusted height is never turned into z=0.
        target_z = number(position.get("z"))
        trusted_z = target_z if (target_z is not None
                                 and position.get("z_known") is not False
                                 and position.get("source") != "UNIT_POSITION") else None
        destination = {
            "target_guid": expected,
            "purpose": "INTERACT",
            "face_on_arrival": True,
            "coordinate_space": "WORLD_YARDS",
            "x": tx,
            "y": ty,
            **({"z": trusted_z, "layer_z": trusted_z} if trusted_z is not None
               else {"z_known": False}),
            "instance_id": target_instance,
            "world_map_id": target_instance,
            "stop_distance": float(stop_distance),
            "avoid_combat": bool(target.get("avoid_combat", False)),
            "allow_combat": bool(target.get("allow_combat", False)),
        }
        return destination

    def _entity_route_identity_matches(self, state: dict, now: float) -> bool:
        """Keep a selected-unit contract through every intermediate waypoint.

        Intermediate anchors intentionally omit target_guid so the movement
        controller does not replace the corridor waypoint with the mob's XYZ.
        That must not drop the original request's identity/freshness gate.
        Coordinate-only and explicitly entity-list/group FOLLOW requests keep
        their separate contracts; a numeric NPC ID alone is not a selected GUID.
        """
        request = self._active_request
        destination = request.destination if request is not None else (self._movement.destination or {})
        server_guid = destination.get("interaction_recipient_guid")
        if server_guid:
            from wowbot.agent.packet_entity_facts import interaction_position
            from wowbot.runtime.entity_identity import check_entity_identity
            from wowbot.runtime.skill_identity import sample_fresh
            if interaction_position(state, server_guid, allow_dead=destination.get('allow_dead') is True) is None:
                return False
            # A soft hint may disappear while turning/walking, but the exact
            # live server actor still owns the route. F7 is checked again on
            # resume. Selected-target approaches retain their selected pin.
            return (destination.get("interaction_identity_source") == "SOFT_INTERACT"
                    or (check_entity_identity({"guid": server_guid}, state.get("target") or {})
                        and sample_fresh(state, "target", now)))
        guid = destination.get("target_guid")
        if not guid:
            return True
        from wowbot.runtime.skill_identity import check_command_identity, expected_identity
        return bool(check_command_identity(
            "APPROACH_TARGET", destination,
            expected_identity({**destination, "guid": guid}), state,
            (Command("BIND", "MOVEFORWARD"),), now))

    def observe(self, state: dict, observation_id: str, now: float, *, commanded: bool = True):
        assessment = self._observe_control(state, observation_id, now, commanded=commanded)
        from .travel import TripStatus
        status = self.trip.observe(state, now, waypoint_index=self._route_waypoint_index,
            terminal=assessment.terminal, success=assessment.success, reason=assessment.reason,
            resolved_destination=self._active_request.destination if self._active_request else None)
        if assessment.terminal and assessment.success and self.trip.request is not None:
            if status is TripStatus.RUNNING:
                return MovementAssessment(MovementPhase.MOVING, False, False, self.trip.reason)
            if status is TripStatus.FAILED:
                return MovementAssessment(MovementPhase.FAILED, True, False, self.trip.reason)
        return assessment

    POSITION_ACQUISITION_SECONDS = 3.

    def owned_route_plan_pending(self, state, now):
        if self._route_feedback is not None or self._deferred_request is not None or self.position_plan_pending(state, now):
            return True
        request = self._active_request
        if request is None or request.destination.get('entity_goal') is not True or self._route_failure_reason:
            return False
        from .entity_goal import resolve
        point = resolve(request.destination, state, now)
        if point is None:
            return False
        changed=math.hypot(point['x']-request.destination['x'],
            point['y']-request.destination['y'], (number(point.get('z')) or 0.)-
            (number(request.destination.get('z')) or 0.))
        if changed>2.:
            return True
        if changed>.05 and self._movement.phase is MovementPhase.ARRIVED:
            player=state.get('player_world_position') or {}
            px,py=number(player.get('x')),number(player.get('y'))
            radius=self._interaction_band(request)
            return None not in (px,py) and math.hypot(point['x']-px,point['y']-py)>radius
        return False

    def resume_owned_route(self, state, now, *, allow_route_queries=True):
        """The same owned subflow yields heavy planning from FAST to medium."""
        if self._owned_route_expired(now):
            self._route_failure_reason = 'movement_safety_deadline'
            self._deferred_request = self._deferred_scope = None
            return True
        if self._route_feedback is not None:
            feedback=self._route_feedback
            status=feedback.assess(state,self._active_request.destination,now)
            if status=='WAITING':
                return False
            if status=='REPLAN' and not allow_route_queries:
                return False
            self._route_feedback_trace={**feedback.snapshot(),'status':status,'resolved_at':now}
            self._route_feedback=None
            if status not in {'READY','REPLAN'}:
                self._route_failure_reason=status
                return True
            if status=='REPLAN':
                from .position_acquisition import scope
                self._deferred_request=self._active_request
                self._deferred_scope=scope(state)
        pending = self.owned_route_plan_pending(state, now)
        if pending and not allow_route_queries:
            return False
        if self._deferred_request is not None:
            from .position_acquisition import scope
            if scope(state) != self._deferred_scope:
                self._route_failure_reason = 'server_position_probe_context_changed'
            elif now-self._request_started_at >= self._deferred_request.timeout:
                self._route_failure_reason = 'movement_safety_deadline'
            elif not self._entity_route_identity_matches(state, now):
                self._route_failure_reason = 'target_identity_changed'
            elif (state.get('loading') or state.get('input_blocked') or state.get('player_present') is False
                    or state.get('is_dead') or state.get('is_ghost') or state.get('on_taxi')
                    or state.get('quest_ui_open') or state.get('gossip_open') or state.get('world_map_open')):
                self._route_failure_reason = 'navigation_plan_interrupted'
            if self._route_failure_reason:
                self._deferred_request = self._deferred_scope = None
                return True
        request = self._deferred_request or self._active_request
        if pending and request is not None and not self.position_plan_pending(state, now):
            from .entity_goal import resolve
            destination = resolve(request.destination, state, now)
            if destination is None:
                self._route_failure_reason = 'target_identity_changed'
                self._deferred_request = self._deferred_scope = None
            else:
                self.start_request(replace(request, destination=destination), state, now, continuing=True)
        self.resume_position_request(state, now)
        return True

    def _owned_route_expired(self, now):
        request = self._active_request
        return bool(request is not None and request.timeout is not None
            and self._request_started_at is not None
            and now-self._request_started_at >= (request.timeout or self.max_reach_seconds))

    def _interaction_band(self, request):
        """The request's own positive range/radius; 0/None are not a band."""
        for value in (request.arrival.desired_range, request.arrival.radius):
            value = number(value)
            if value is not None and value > 0:
                return value
        return self._movement.world_arrival_tolerance

    SLOW_PLAN_SECONDS = .6

    def _require_post_plan_feedback(self,state,now,elapsed):
        if (elapsed<=self.SLOW_PLAN_SECONDS or self._active_request is None
                or self._route_failure_reason or self._movement.destination is None):
            return
        from .route_feedback import RouteFeedback,feedback_scope,position
        request=self._active_request
        self._route_feedback=RouteFeedback(request.request_id,now+elapsed,elapsed,
            position(state,request.destination),feedback_scope(state))
        self._route_feedback_trace={**self._route_feedback.snapshot(),'status':'WAITING'}

    def _position_wait_status(self, state: dict, now: float) -> str | None:
        request = self._active_request
        if self._position_wait is None:
            return None
        return self.position_wait.status(
            state, now, min(self.POSITION_ACQUISITION_SECONDS, request.timeout or self.max_reach_seconds),
            self._request_started_at, request.timeout or self.max_reach_seconds)

    # REV4 split: the wait's state lives in position_acquisition.ServerPositionWait.
    @property
    def _position_wait(self) -> dict | None:
        return self.position_wait.wait

    @_position_wait.setter
    def _position_wait(self, value) -> None:
        self.position_wait.wait = value

    @property
    def _position_trace(self) -> dict | None:
        return self.position_wait.trace

    @_position_trace.setter
    def _position_trace(self, value) -> None:
        self.position_wait.trace = value

    def position_plan_pending(self, state: dict, now: float) -> bool:
        """FAST may request a handoff; it must never run this route query."""
        return (not self._route_failure_reason and self._position_wait_status(state, now) == 'READY'
                and self._entity_route_identity_matches(state, now))

    def resume_position_request(self, state: dict, now: float) -> None:
        """Medium owner resumes the same request from the actual measured Z."""
        if self.position_plan_pending(state, now):
            from .position_acquisition import observed_height
            point = state.get('player_world_position') or {}
            self._position_trace.update(phase='PLAN_PENDING', acquired_at=now,
                acquired_z=observed_height(state), z_source=point.get('z_source'),
                position_sample_time=point.get('sample_time'))
            self.start_request(self._active_request, state, now, continuing=True)
            self._position_trace.update(phase='PLAN_FAILED' if self._route_failure_reason else 'PLANNED',
                                        plan_at=now, plan_failure=self._route_failure_reason)

    def _observe_control(self, state: dict, observation_id: str, now: float, *, commanded: bool = True):
        if self._owned_route_expired(now):
            self._route_failure_reason = 'movement_safety_deadline'
        if self._route_failure_reason in {'server_position_probe_context_changed', 'movement_safety_deadline',
                                          'navigation_plan_interrupted','post_plan_feedback_context_changed',
                                          'post_plan_feedback_interrupted','post_plan_feedback_timeout'}:
            return MovementAssessment(MovementPhase.FAILED, True, False, self._route_failure_reason)
        if self._route_feedback is not None:
            return MovementAssessment(MovementPhase.NO_PROGRESS_YET,False,False,'awaiting_post_plan_feedback')
        if not self._entity_route_identity_matches(state, now):
            self._route_failure_reason = "target_identity_changed"
            self._movement.reset()
            return MovementAssessment(MovementPhase.FAILED, True, False,
                                      self._route_failure_reason)
        if self._deferred_request is not None:
            return MovementAssessment(MovementPhase.NO_PROGRESS_YET, False, False, 'owned_route_plan_pending')
        position_status = self._position_wait_status(state, now)
        if position_status is not None:
            if position_status not in {'READY', 'WAITING'}:
                self._route_failure_reason = position_status
                self._position_trace.update(phase='FAILED', failure_reason=position_status, ended_at=now)
                if position_status == 'server_position_probe_timeout':
                    self._position_trace['probe_released'] = self._movement.release_height_probe(now)
                self._position_wait = None
                self._movement.reset()
                return MovementAssessment(MovementPhase.FAILED, True, False, position_status)
            return MovementAssessment(MovementPhase.NO_PROGRESS_YET, False, False,
                'server_position_acquired_plan_pending' if position_status == 'READY'
                else 'awaiting_server_position')
        if (self._route_failure_reason in {"ambiguous_player_layer", "ambiguous_player_layer_after_fall"}
                and self._active_request is not None):
            from wowbot.agent.destination_distance import observed_height
            player = state.get("player_world_position") or {}
            sampled = number(player.get("sample_time"))
            started = self._request_started_at
            budget = self._active_request.timeout or self.max_reach_seconds
            if (observed_height(player) is not None and sampled is not None and started is not None
                    and sampled > started and 0 <= now-sampled <= self.layer_resolver.OBSERVED_Z_MAX_AGE
                    and now-started < budget):
                # The fast lane already received our real Z, but an earlier
                # first-fix failure was still latched (forge 18:51:47). Replan
                # this same owned request from that measurement, not the old
                # floor hypothesis. Identity and normal route checks remain.
                self.start_request(self._active_request, state, now, continuing=True)
                if not self._route_failure_reason:
                    return MovementAssessment(MovementPhase.MOVING, False, False,
                                              "route_replanned_from_observed_position")
        if self._route_failure_reason:
            return MovementAssessment(MovementPhase.FAILED, True, False,
                                      self._route_failure_reason)
        from .flight_path import rooted
        if not self._airborne_route() and state.get("in_vehicle") is not True and rooted(state, now):
            # (A vehicle's passenger is always rooted: the vehicle moves.)
            # Live 2026-10-25 21:05:51 / 21:09:38: a race start line roots the
            # rider; a walk there only gathered stuck evidence and a recovery
            # while the race scene waited.  A flight waits for the start.
            return MovementAssessment(MovementPhase.FAILED, True, False, "player_rooted")
        if self._airborne_route():
            # Steady Flight / Skyriding (2026-10-25): a glide is a "fall" to
            # the client and there is no floor or route layer in the air; the
            # movement controller's flight loop owns progress and arrival.
            if self.needs_ground_approach(state, now):
                self._start_ground_approach(state, now)
                if self._route_failure_reason:
                    return MovementAssessment(MovementPhase.FAILED, True, False, self._route_failure_reason)
            else:
                assessment = self._movement.observe(state, observation_id, now, commanded=commanded)
                route = self._active_route
                plan = route.anchors[-1].get('flight_plan', {}) if route and route.anchors else {}
                if assessment.terminal and assessment.success and plan.get('truncated'):
                    return self._continue_flight_trip(state, now)
                return assessment
        if (state.get("movement") or {}).get("falling") is True:
            # Live 2026-10-11 14:25: every small step off a ledge/slope in the
            # camp reported a falling sample (0-1 s FALL_STARTED/ENDED pairs);
            # failing the MOVE and quarantining 8 yd for 10 min on each one
            # blocked the turn-in route ("fall_hazard_on_route").  A falling
            # sample now only pauses steering; a fall still in progress after
            # FALL_CONFIRM_SECONDS (longer than a jump) is a real drop: stop
            # the route at the ledge where it started.  Shorter real drops are
            # confirmed on landing by the navmesh layer check (``fell`` below).
            # Duration on the addon's sample clock: a repeated FAST packet
            # (no new sample) must not age the fall (live 2026-10-11 15:15).
            sample_time = number(state.get("monotonic_time"))
            clock = sample_time if sample_time is not None else now
            if self._falling_since is None:
                self._falling_since = (clock, state)
                if self._slipping_in_place(state, clock):
                    self._route_failure_reason = "supported_stuck"
                    self._movement.reset()
                    return MovementAssessment(MovementPhase.FAILED, True, False,
                                              self._route_failure_reason)
            started, ledge_state = self._falling_since
            if clock - started < self.FALL_CONFIRM_SECONDS:
                return MovementAssessment(MovementPhase.MOVING, False, False, "fall_pending")
            self._remember_fall_hazard(ledge_state, now)
            self._route_failure_reason = "fall_in_progress"
            self._movement.reset()
            return MovementAssessment(MovementPhase.FAILED, True, False,
                                      self._route_failure_reason)
        landed = self._falling_since is not None
        self._falling_since = None
        self._z.observe_player(state, now, route_z=self._route_hint_z(state))
        fell = self._z.fall_count > self._handled_falls
        self._handled_falls = self._z.fall_count
        if (landed and not fell and self._active_request is not None
                and self._off_route_yards(state) > self.LANDED_OFF_ROUTE_YARDS):
            # Live 2026-10-13 17:57: a 1.7 s drop off the spiral's edge was
            # below FALL_CONFIRM_SECONDS and the floor check called it a hop;
            # the old route was steered from the landing spot into the wall
            # for 25 s.  A landing off the route plans from where we are now
            # toward the same goal (user: "after a fall, a new route toward
            # the objective / the dot / the quest ender").
            self._replan_from_tracked_layer(state, observation_id, now)
            if self._route_failure_reason:
                return MovementAssessment(MovementPhase.FAILED, True, False,
                                          self._route_failure_reason)
            return MovementAssessment(MovementPhase.MOVING, False, False, "route_replanned_after_landing")
        passed = self._sweep_hop_passed()
        if passed is not None:
            return passed
        if fell and self._active_request is not None:
            self._remember_fall_hazard(state, now)
            self._replan_from_tracked_layer(state, observation_id, now)
            if self._route_failure_reason:
                return MovementAssessment(MovementPhase.FAILED, True, False,
                                          self._route_failure_reason)
            return MovementAssessment(MovementPhase.MOVING, False, False, "route_replanned_after_fall")
        player_layer = self._z.player
        ambiguous = (self._active_request is not None
                     and self._active_request.destination.get("require_navmesh")
                     and player_layer is not None and player_layer.confidence < .6
                     and not self.__dict__.get("_layer_probe"))
        if not ambiguous:
            self._ambiguous_since = None
        elif self.__dict__.get("_ambiguous_since") is None:
            self._ambiguous_since = now
        # Live 2026-10-06 21:44-21:52: seven MOVEs failed at once on a brief
        # ambiguity (polygon edges, after combat).  A route planned from a
        # confident floor is still the best hypothesis: keep following it
        # (the route tie-breaks the floor) and give up only if it persists.
        if ambiguous and now - self._ambiguous_since > self.AMBIGUOUS_ROUTE_GRACE_SECONDS:
            self._route_failure_reason = "ambiguous_player_layer"
            self._movement.reset()
            return MovementAssessment(MovementPhase.FAILED, True, False, "ambiguous_player_layer")
        observed = state
        state = self._state_with_navmesh_surface(state)
        if self._intermediate_waypoint_passed(state) or self._intermediate_waypoint_stalled(state, now):
            self._route_waypoint_index += 1
            self.start(self._current_route_destination(), state,
                       f"{observation_id}:route:{self._route_waypoint_index}", now, continuing=True)
            return MovementAssessment(MovementPhase.MOVING, False, False,
                                      "route_waypoint_advanced")
        assessment = self._movement.observe(state, observation_id, now, commanded=commanded)
        if assessment.terminal and assessment.reason == "supported_stuck":
            self._note_offset_stuck(state)
        wrong_layer = (self._destination_on_other_layer(state, assessment)
                       or self._route_on_observed_other_layer(observed, assessment, now))
        if wrong_layer is not None:
            return wrong_layer
        route = self._active_route
        if (assessment.terminal and assessment.success and route is not None
                and self._route_waypoint_index < len(route.anchors)-1
                and assessment.reason == "reach_arrival_verified"):
            self._route_waypoint_index += 1
            self._route_previous_position = self._player_route_position(state)
            self.start(self._current_route_destination(), state,
                       f"{observation_id}:route:{self._route_waypoint_index}", now, continuing=True)
            return MovementAssessment(MovementPhase.MOVING, False, False,
                                      "route_waypoint_advanced")
        if (assessment.terminal and assessment.success and route is not None
                and self._route_waypoint_index == len(route.anchors)-1
                and assessment.reason == "reach_arrival_verified"):
            request = self._active_request
            if request is not None and self._departure_active():
                started = self._request_started_at if self._request_started_at is not None else now
                if now-started >= (request.timeout or self.max_reach_seconds):
                    self._route_failure_reason = 'movement_safety_deadline'
                    return MovementAssessment(MovementPhase.FAILED, True, False, self._route_failure_reason)
                destination = self.travel_transitions.after_departure_walk(request.destination, state)
                if destination is not None:
                    self.start_request(replace(request, destination=destination), state, now, continuing=True)
                return MovementAssessment(MovementPhase.MOVING, False, False, 'flight_departure_ready')
            if request is not None and self._partial_localization_route(route):
                # Live 2026-10-22 11:33: a 30-yard Z check was recorded as
                # arrival 307 yards from the quest POI. Retain this very MOVE
                # and its original destination; resolve the layer again.
                deadline = request.timeout or self.max_reach_seconds
                if self._request_started_at is not None and now-self._request_started_at >= deadline:
                    self._route_failure_reason = "movement_safety_deadline"
                else:
                    self.start_request(request, state, now, continuing=True)
                if self._route_failure_reason:
                    self._movement.reset()
                    return MovementAssessment(MovementPhase.FAILED, True, False,
                                              self._route_failure_reason)
                return MovementAssessment(MovementPhase.MOVING, False, False,
                                          "route_localization_leg_advanced")
            if request is not None and not self._original_goal_within_arrival(state, now):
                self._route_failure_reason = "route_endpoint_outside_arrival_envelope"
                self._movement.reset()
                return MovementAssessment(MovementPhase.FAILED, True, False,
                                          self._route_failure_reason)
        return self._verify_arrival_condition(assessment, state, now)

    def _continue_flight_trip(self, state, now):
        request = self._active_request
        started = self._request_started_at if self._request_started_at is not None else now
        if now-started >= (request.timeout or self._movement.max_flight_seconds):
            self._route_failure_reason = 'movement_safety_deadline'
        else:
            self.start_request(request, state, now, continuing=True)
        if self._route_failure_reason:
            return MovementAssessment(MovementPhase.FAILED, True, False, self._route_failure_reason)
        return MovementAssessment(MovementPhase.MOVING, False, False, 'flight_horizon_replanned')

    # REV4 split: the flight-departure / ground-leg transition decisions and
    # the take-off walk oracle live in travel_transitions.TravelTransitionPolicy.
    def _departure_active(self):
        return self.travel_transitions.departure_active(self._active_route)

    @staticmethod
    def _departure_flight_ready(state, style):
        from .travel_transitions import TravelTransitionPolicy
        return TravelTransitionPolicy.departure_flight_ready(state, style)

    def flight_departure_walk(self, parameters, state):
        """Planning-only oracle: a real MMAP walk from a covered start to sky."""
        return self.travel_transitions.departure_walk(parameters, state)

    def _verify_arrival_condition(self, assessment, state, now):
        request = self._active_request
        condition = request.destination.get("arrival_condition") if request is not None else None
        if condition is None or not assessment.terminal or not assessment.success:
            return assessment
        from wowbot.verification.conditions import evaluate_condition
        if evaluate_condition(condition, state) is True:
            return assessment
        if self._request_started_at is not None and now-self._request_started_at >= (request.timeout or self.max_reach_seconds):
            return MovementAssessment(MovementPhase.FAILED, True, False, "arrival_evidence_timeout")
        # Geometry is reached: retain the same movement owner with no new
        # key lease until the declarative postcondition is actually observed.
        return MovementAssessment(MovementPhase.MOVING, False, False, "awaiting_arrival_evidence")

    def _original_goal_within_arrival(self, state: dict, now: float | None = None) -> bool:
        """A projected/cropped route endpoint cannot certify a distant POI."""
        from wowbot.agent.destination_distance import other_level
        request = self._active_request
        destination = request.destination
        if destination.get('entity_goal') is True:
            from .entity_goal import resolve
            destination = resolve(destination, state, now if now is not None else number(state.get('monotonic_time')) or 0.)
            if destination is None:
                return False
        if destination.get("coordinate_space") != "WORLD_YARDS":
            return True
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        dx, dy = number(destination.get("x")), number(destination.get("y"))
        if (None in (px, py, dx, dy)
                or destination.get("instance_id") not in (None, player.get("instance_id"))
                or other_level(state, destination)):
            return False
        tolerance = next((number(value) for value in (
            request.arrival.desired_range, destination.get("stop_distance"),
            request.arrival.radius, destination.get("arrival_radius"))
            if number(value) is not None), self._movement.world_arrival_tolerance)
        return math.hypot(px-dx, py-dy) <= tolerance

    def current_navigation_mode(self, state: dict, *,
                                vision_evidence: NavigationModeEvidence | None = None) -> NavigationMode:
        """V4-023: report which of the two navigation modes applies right now.

        Read-only classification; it does not change movement behavior, and
        both modes still go through this one service (V4-023.3 "One API").
        Reliable world position is derived directly from ``state`` here,
        since that is this service's own signal. Vision-only cue
        availability (minimap direction, landmarks, ...) is supplied by the
        caller via ``vision_evidence`` -- those adapters are vision-package
        concerns this service does not own.
        """
        position = state.get("player_world_position") or {}
        has_position = number(position.get("x")) is not None and number(position.get("y")) is not None
        evidence = replace(vision_evidence or NavigationModeEvidence(),
                           has_reliable_player_world_position=has_position)
        return resolve_navigation_mode(evidence)

    def current_navigation_context(self, state: dict) -> NavigationContextAssessment:
        """V4-025: classify OUTDOOR/INDOOR/CAVE/MULTI_FLOOR/TRANSITION/VEHICLE.

        Read-only; influences how a caller should interpret route
        expectation, map interpretation, arrival verification and stuck
        recovery, but this call itself never changes any of them.
        """
        return self._navigation_context_classifier.classify(state)

    def resolve_transition(self, signals: dict) -> TransitionAssessment:
        """V4-026: propose ENTER_BUILDING/FIND_CAVE_ENTRANCE/CHANGE_FLOOR/etc.

        Read-only evidence resolution for a stuck-at-the-boundary situation;
        it never triggers the existing StuckResolver ladder itself, it only
        answers "what kind of transition might this be" from caller-supplied
        signals (repeated local blockage, map-distance-vs-3D-absence, ...).
        """
        return self._transition_resolver.resolve(signals)

    def command(self, state: dict, observation_id: str, now: float):
        if self._owned_route_expired(now) or self._deferred_request is not None or self.owned_route_plan_pending(state, now):
            return ()
        if self._route_failure_reason or ((state.get("movement") or {}).get("falling") is True
                                          and not self.flight_controls_allowed(state)):
            return ()
        if (state.get('is_ghost') is True and self._airborne_route()
                and not self.flight_controls_allowed(state)):
            return ()
        if not self._entity_route_identity_matches(state, now):
            return ()
        if self._position_wait is not None:
            if self._position_wait_status(state, now) != 'WAITING':
                return ()
            commands = self._movement.position_probe_command(state, observation_id, now)
            if commands:
                self._position_trace['proposed_probe'] = {'binding': commands[0].binding,
                    'duration': commands[0].duration, 'at': now, 'observation_id': observation_id}
            return commands
        state = self._state_with_navmesh_surface(state)
        self.local_plan(state, now=now, observation_id=observation_id)
        if self._route_feedback is not None:
            return ()
        return self._movement.command(state, observation_id, now)

    def _airborne_route(self) -> bool:
        request, route = self._active_request, self._active_route
        return bool((request is not None and (request.destination.get("flight_path")
                                              or request.destination.get("hover_point")))
                    or (route is not None and route.anchors and route.anchors[-1].get("flight_plan")))

    def airborne_route_active(self) -> bool:
        """The active MOVE follows an explicit flight path or flight plan."""
        return self._airborne_route()

    def flight_controls_allowed(self, state: dict) -> bool:
        """Only an existing mounted flight controller owns takeoff/glide falls
        (or a flying vehicle's hover controller)."""
        if (self._airborne_route() and getattr(self._movement.flight, "vehicle", False)
                and state.get("in_vehicle") is True and not state.get("loading") and not state.get("is_dead")):
            return True
        from wowbot.agent.death_recovery_planning import corpse_run_matches
        from wowbot.agent.flight_capability import ghost_steady_flight_available
        destination = self._active_request.destination if self._active_request is not None else {}
        ghost_corpse = (destination.get('flight_style') == 'STEADY'
                        and not destination.get('flight_path')
                        and ghost_steady_flight_available(state)
                        and corpse_run_matches(state, destination))
        return bool(self._airborne_route() and self._movement.flight is not None
                    and state.get("is_mounted") is True
                    and state.get("in_vehicle") is not True and state.get("on_taxi") is not True
                    and not state.get("loading") and not state.get("is_dead")
                    and (not state.get("is_ghost") or ghost_corpse))

    def needs_ground_approach(self, state: dict, now: float) -> bool:
        return bool(self._airborne_route() and self._movement.ground_transition_required(state, now))

    @staticmethod
    def _ground_request(request, path=None):
        from .travel_transitions import TravelTransitionPolicy
        return TravelTransitionPolicy.ground_request(request, path)

    FLIGHT_RELAUNCHES = 2

    def _start_ground_approach(self, state: dict, now: float) -> None:
        """Medium-lane phase handoff, retaining the same action/correlation owner.

        A mounted player can walk. Removing only the explicit flight route
        makes the existing ground planner prove the final path normally.
        A travel flight (no server checkpoint signals) whose landing cannot be
        walked to takes off again for the landing point (user 2026-10-25:
        "ha nem érhető el, akkor repül"), at most FLIGHT_RELAUNCHES times; an
        explicit course keeps failing closed (its target must be walkable).
        """
        request = self._active_request
        path = getattr(self._movement.flight, "path", None)
        self.start_request(self._ground_request(request, path), state, now)
        travel = path is not None and path.arrival_condition is None and not any(path.checkpoint_conditions)
        launches = self.__dict__.get("_flight_relaunches") or {}
        count = launches.get(request.request_id, 0)
        if (travel and self._route_failure_reason == "required_navmesh_route_unavailable"
                and count < self.FLIGHT_RELAUNCHES):
            self.__dict__["_flight_relaunches"] = {request.request_id: count + 1}
            self.start_request(replace(request, destination={**request.destination, "flight_relaunch": True}),
                               state, now)

    def _state_with_navmesh_surface(self, state: dict) -> dict:
        """Refresh player Z from the active mmap corridor without mutating WorldModel."""
        route, navmesh = self._active_route, self._navmesh
        projector = getattr(navmesh, "project_position", None)
        player = state.get("player_world_position") or {}
        if route is None or not route.anchors or not callable(projector):
            return state
        if (self._airborne_route()
                or (state.get("movement") or {}).get("flying") is True):
            # In the air the measured (packet) height is the flight's input;
            # a navmesh floor under the player is not where the player is.
            return state
        # command() passes its already projected state into local_plan().  Do
        # not perform the same 3x3-tile surface query twice for one telemetry
        # sample.
        if (player.get("source") == "TRINITYCORE_MMAP_SURFACE"
                and player.get("z_source") == "NAVMESH_SURFACE"):
            return state
        try:
            instance_id = int(player.get("instance_id"))
            px, py = float(player["x"]), float(player["y"])
        except (KeyError, TypeError, ValueError):
            return state
        nearest = min(route.anchors, key=lambda anchor:
                      (float(anchor["x"])-px)**2 + (float(anchor["y"])-py)**2)
        resolved = self._z.player
        z_hint = (resolved.z if resolved is not None and resolved.instance_id == instance_id
                  and math.hypot(resolved.x-px, resolved.y-py) <= 3. else number(nearest.get("z")))
        projection_key = (instance_id, px, py, z_hint)
        # The projection is a new dict: keep the measurement time, or every
        # repeated FAST sample would look like a fresh position (2026-10-02).
        measured = ({"sample_time": player["sample_time"]}
                    if player.get("sample_time") is not None else {})
        # ... and the server-measured own height: the other-level arrival
        # checks need it (live 2026-10-27 17:03: under the bridge, z 201
        # observed, the projection dropped z_observed and the 44 yd to the
        # arbalest deck went unseen; the walk "arrived" and facing failed).
        if player.get("z_observed") is True and number(player.get("z")) is not None:
            measured["observed_z"] = number(player.get("z"))
        if (projection_key == self._surface_projection_key
                and self._surface_projection_value is not None):
            return {**state, "player_world_position": {**self._surface_projection_value, **measured}}
        projected = projector(instance_id, player, z_hint=z_hint)
        if not isinstance(projected, dict):
            return state
        self._surface_projection_key = projection_key
        self._surface_projection_value = dict(projected)
        self._latest_surface_projection = dict(projected)
        return {**state, "player_world_position": {**projected, **measured}}

    OBSTACLE_AHEAD_YARDS = 2.0

    def snapshot(self, now: float) -> dict[str, Any]:
        snapshot = {"trip": self.trip.snapshot(), "route": self._routes.snapshot(now), "movement": self._movement.snapshot(),
                    "stuck_resolver": self._stuck.snapshot(), "authority": "NavigationService",
                    "danger_map": self._danger.snapshot(now),
                    "reachability": self._reachability.snapshot(),
                    "search_coverage": self._search_coverage.snapshot(),
                    "active_request": ({"request_id": self._active_request.request_id,
                                        "mode": self._active_request.mode,
                                        "correlation_id": self._active_request.correlation_id}
                                       if self._active_request else None)}
        snapshot["navmesh"] = ({"configured": True,
                                 **dict(getattr(self._navmesh, "last_diagnostics", {}))}
                                if self._navmesh is not None else {"configured": False})
        snapshot["route_waypoint_index"] = self._route_waypoint_index
        snapshot['travel_phase'] = ('WALK_TO_TAKEOFF' if self._departure_active() else
                                     'FLIGHT' if self._airborne_route() else
                                     'GROUND_APPROACH' if self._active_request and
                                         self._active_request.request_id.endswith(':ground') else 'GROUND')
        snapshot['flight_planning'] = dict(getattr(self._global_planner, 'last_flight_planning', {}))
        snapshot['route_scores'] = dict(getattr(self._global_planner, 'last_route_scores', {}))
        snapshot["z_resolver"] = self._z.snapshot()
        snapshot["route_danger_revision"] = self._route_danger_revision
        snapshot["route_failure_reason"] = self._route_failure_reason
        snapshot['owned_route_plan_pending'] = self._deferred_request is not None
        snapshot['route_feedback'] = self._route_feedback_snapshot()
        snapshot['position_acquisition'] = self._position_acquisition_snapshot()
        snapshot["player_surface_projection"] = (dict(self._latest_surface_projection)
                                                   if self._latest_surface_projection else None)
        snapshot["global_route"] = ({"route_id": self._active_route.route_id,
                                     "anchors": list(self._active_route.anchors),
                                     "route_source": next((
                                         region.get("route_source")
                                         for region in self._active_route.regions
                                         if region.get("route_source")), "UNKNOWN"),
                                     "regions": list(self._active_route.regions),
                                     "cost": self._active_route.cost,
                                     "confidence": self._active_route.confidence,
                                     "valid_until": self._active_route.valid_until}
                                    if self._active_route else None)
        snapshot["path_corridor"] = ({"corridor_id": self._active_corridor.corridor_id,
                                       "route_id": self._active_corridor.route_id,
                                       "segments": list(self._active_corridor.segments),
                                       "confidence": self._active_corridor.confidence}
                                      if self._active_corridor else None)
        snapshot["local_motion_plan"] = ({"desired_heading": self._latest_local_plan.desired_heading,
                                           "local_waypoint": self._latest_local_plan.local_waypoint,
                                           "motion_mode": self._latest_local_plan.motion_mode,
                                           "expected_progress_vector": self._latest_local_plan.expected_progress_vector,
                                           "valid_for_ms": self._latest_local_plan.valid_for_ms,
                                           "source": self._latest_local_plan.source}
                                          if self._latest_local_plan else None)
        snapshot["los_recovery"] = (dict(self._latest_los_recovery)
                                    if self._latest_los_recovery else None)
        return snapshot

    def _position_acquisition_snapshot(self) -> dict | None:
        return self.position_wait.snapshot()

    def movement_snapshot(self) -> dict[str, Any]:
        return {**self._movement.snapshot(), 'position_acquisition': self._position_acquisition_snapshot(),
                'route_feedback':self._route_feedback_snapshot()}

    def _route_feedback_snapshot(self):
        if self._route_feedback_trace is None:
            return None
        return {**self._route_feedback_trace,'active':self._route_feedback is not None}

    def route_feedback_pending(self):
        return self._route_feedback is not None

    # Own-layer tracking (design doc §4.3).  Live 2026-10-05 12:55: after a
    # spider fight halfway down Hrun's pit the new route started from the
    # terrain height -- the rim 30 yd above the player -- and the agent
    # walked on the spot under its first waypoint.  The terrain height stays
    # the fallback (and the start-layer probe for an incomplete path, the
    # Torgok/Wrathion fix, still runs because the height is only estimated).
    LAYER_TRACK_SECONDS = .5
    LAYER_CONTINUITY_YARDS = 40.
    LAYER_CONTINUITY_SECONDS = 180.

    @property
    def _player_layer(self) -> tuple | None:
        """(instance, x, y, z, at) of the player's resolved layer (ZResolver)."""
        player = self._z.player
        return (None if player is None else
                (player.instance_id, player.x, player.y, player.z, player.at))

    @_player_layer.setter
    def _player_layer(self, value) -> None:
        if value is None:
            self._z.player = None
        else:
            self._z.seed_player(value[0], value[1], value[2], value[3],
                                value[4] if value[4] is not None else 0.)

    # Live 2026-10-06: right above the cocoon's ledge (0.4 yd away in X/Y, 35 yd
    # in height) the controller turned left and right for 35 s.  Turning
    # cannot fix a height difference: the MOVE ends and the planner decides.
    WRONG_LAYER_HORIZONTAL_YARDS = 3.
    WRONG_LAYER_VERTICAL_YARDS = 4.

    def _route_on_observed_other_layer(self, state: dict, assessment, now: float) -> MovementAssessment | None:
        """A route from the wrong floor fails so the next plan starts from the
        observed height (layer_resolver.DestinationLayerResolver.observed_layer)."""
        destination = self._movement.destination or {}
        skip = bool(assessment.terminal or destination.get("coordinate_space") != "WORLD_YARDS"
                    or destination.get("target_guid") or destination.get("follow_group_leader")
                    or self._airborne_route() or (state.get("movement") or {}).get("falling") is True)
        verdict = self.layer_resolver.observed_layer(
            state, destination, skip,
            bool(self.__dict__.get("_layer_probe") or self.__dict__.get("_route_own_z_unobserved")), now)
        if verdict == "CONFIRMED":
            self.__dict__["_route_own_z_unobserved"] = False   # the guessed floor was right
        if verdict != "CONTRADICTED":
            return None
        self._route_failure_reason = "route_on_observed_other_layer"
        self._movement.reset()
        return MovementAssessment(MovementPhase.FAILED, True, False, self._route_failure_reason)

    def _destination_on_other_layer(self, state: dict, assessment) -> MovementAssessment | None:
        destination = self._movement.destination or {}
        if (assessment.terminal or destination.get("coordinate_space") != "WORLD_YARDS"
                or destination.get("route_waypoint_final") is False
                or destination.get("target_guid") or destination.get("follow_group_leader")):
            return None
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        dx, dy = number(destination.get("x")), number(destination.get("y"))
        if None in (px, py, dx, dy) or math.hypot(dx-px, dy-py) > self.WRONG_LAYER_HORIZONTAL_YARDS:
            return None
        if self._movement._vertical_excess(state) <= self.WRONG_LAYER_VERTICAL_YARDS:
            return None
        return MovementAssessment(MovementPhase.FAILED, True, False, "destination_on_other_layer")

    def _sweep_hop_passed(self) -> MovementAssessment | None:
        """A zone-sweep hop we are already past in height (a fall, a jump, a
        drop off the spiral -- reported or not) is done: the planner continues
        the sweep from our layer instead of climbing back (live 2026-10-06)."""
        request, player = self._active_request, self._z.player
        if request is None or player is None or player.confidence < .7:
            return None
        destination = request.destination
        direction = destination.get("sweep_direction")
        target_z = number(destination.get("layer_z", destination.get("z")))
        if direction not in {"DOWN", "UP"} or target_z is None:
            return None
        beyond = (target_z > player.z + self.ZONE_SWEEP_LAYER_YARDS if direction == "DOWN"
                  else target_z < player.z - self.ZONE_SWEEP_LAYER_YARDS)
        if not beyond:
            return None
        # Live 2026-10-06 21:44: the planner's own (fresher-gated) check did
        # not mark this hop and offered it 30 times in 4 s, each "passed" at
        # once.  The decision made here is recorded in the sweep itself.
        sweep = (self.__dict__.get("_zone_sweeps") or {}).get(self.__dict__.get("_last_sweep_key"))
        index = destination.get("sweep_hop")
        if isinstance(sweep, dict) and isinstance(index, int) and "visited" in sweep:
            sweep["visited"].add(index)
        return MovementAssessment(MovementPhase.ARRIVED, True, True, "zone_sweep_hop_passed")

    def track_player_layer(self, state: dict, now: float) -> None:
        """Every tick, also without a MOVE (the resolver follows SEEK/combat walks)."""
        self._z.observe_player(state, now, route_z=self._route_hint_z(state))

    # A jump is airborne ~0.7-0.8 s on flat ground, but a jump or a run down
    # a slope reported falling for up to ~1.9 s (live 2026-10-11 15:15, the
    # user pressed space).  Two seconds of falling is a real drop (~20+ yd);
    # shorter real drops are confirmed on landing by the navmesh layer check.
    FALL_CONFIRM_SECONDS = 2.

    def _remember_fall_hazard(self, state: dict, now: float) -> None:
        """Remember the *upper route* at the observed fall, scoped by floor.

        A lower-floor route can legitimately pass the same X/Y. Unknown route
        height remains unsafe rather than inventing a floor or a detour.
        The memory itself is navigation/fall_hazards.FallHazardMemory.
        """
        if self._active_route is None or not self._active_route.anchors:
            return
        player = state.get("player_world_position") or {}
        x, y = number(player.get("x")), number(player.get("y"))
        if x is None or y is None:
            return
        try:
            instance = int(player.get("instance_id"))
        except (TypeError, ValueError):
            return
        z = self._route_hint_z(state)
        if z is None and self._z.player is not None and self._z.player.confidence >= .6:
            z = self._z.player.z
        if z is None:
            index = min(max(0, self._route_waypoint_index), len(self._active_route.anchors)-1)
            z = number(self._active_route.anchors[index].get("z"))
        self.fall_hazards.remember(x, y, z, instance, now)

    def _fall_hazard_blocks(self, route: GlobalRoute, state: dict, now: float) -> bool:
        player = state.get("player_world_position") or {}
        try:
            instance = int(player.get("instance_id"))
        except (TypeError, ValueError):
            return False
        layer = self._z.player
        return self.fall_hazards.blocks(
            route, instance, number(player.get("x")), number(player.get("y")),
            layer.z if layer is not None and layer.confidence >= .6 else None, now)

    @property
    def _fall_hazards(self) -> list:
        """The live hazard list (read/clear), owned by FallHazardMemory."""
        return self.fall_hazards.items

    # Live 2026-10-06 (Hrun's pit): the player fell off the spiral (the
    # addon's FALL_STARTED/FALL_ENDED events); with no client height the
    # route projection kept him on the upper layer, every replan started
    # there and the next waypoint sat right above him -- he pushed against
    # the wall "in a straight line" until stopped (user).  On a fall the
    # player is placed on the highest walkable layer below the tracked one
    # and the route is planned again from there.
    FALL_MIN_DROP_YARDS = 1.5
    FALL_EVENT_FRESH_SECONDS = 10.

    def _replan_from_tracked_layer(self, state: dict, observation_id: str, now: float) -> None:
        layered = self._state_with_layer_continuity(state, now)
        if self._z.player is not None and self._z.player.confidence < .6:
            self._route_failure_reason = "ambiguous_player_layer_after_fall"
            self._movement.reset()
            return
        if self._active_request.destination.get("z_resolved_from"):
            # The landing changes which layer of the target is reachable.
            self._active_request = self._resolve_destination_z(self._active_request, layered, now)
            if self._active_request.destination.get("z_resolution_failed"):
                self._route_failure_reason = str(self._active_request.destination["z_resolution_failed"])
                self._movement.reset()
                return
        self._active_route = self._away_from_drops(self._global_planner.plan(
            self._active_request, layered, now, danger_map=self._danger))
        self._active_route = self._bounded_localization_route(self._active_route)
        if self._fall_hazard_blocks(self._active_route, layered, now):
            self._route_failure_reason = "fall_hazard_on_route"
            self._movement.reset()
            return
        self._route_danger_revision = self._danger.revision
        self._route_waypoint_index = self._first_route_index(layered)
        self._route_previous_position = self._player_route_position(layered)
        self._active_corridor = self._corridor_builder.build(self._active_route)
        self._surface_projection_key = None
        if not self._active_route.anchors:
            self._route_failure_reason = "required_navmesh_route_unavailable"
            self._movement.reset()
            return
        self.start(self._current_route_destination(), layered, f"{observation_id}:fall", now)

    # Z resolver for destinations without a height (user 2026-10-06): the
    # walkable, reachable layer at/near the target X/Y, scored with VMAP floors,
    # the player's layer and the minimap floor cue.  A low-confidence target
    # is approached in a short leg first and resolved again (design §12).
    LOW_CONFIDENCE_LEG_YARDS = 30.
    AMBIGUOUS_ROUTE_GRACE_SECONDS = 4.
    # Live 2026-10-06 20:08-20:14 (working copy, agent started in Hrun's pit):
    # the first fix was ambiguous (.5); every MOVE failed at once
    # (ambiguous_player_layer x3 -> loop guard -> 45 s WAIT) and, standing
    # still, the floor could never resolve.  A short leg lets continuity
    # prune the hypotheses; the wall-contact stop bounds a wrong guess.
    LAYER_PROBE_YARDS = 12.

    def _ambiguous_layer_probe(self, request: NavigationRequest, state: dict, layer, now: float):
        """(state on the chosen floor hypothesis, its route) or None."""
        if not callable(getattr(self._z.geometry, "find_path", None)):
            return None
        player = state.get("player_world_position") or {}
        # A floor tracked until a broken continuity: its column's other
        # polygons are no hypotheses (11:56: the rim above a cave edge).
        held = layer.source == "CONTINUITY"
        candidates = self._z._cave_pruned(layer.instance_id, layer.x, layer.y,
                                          [layer.z] if held else [layer.z, *layer.alternatives])
        tried: list[float] = []
        for z in candidates:
            if any(abs(z-other) < 1. for other in tried):
                continue
            tried.append(z)
            probe_state = {**state, "player_world_position": {
                **player, "z": z, "z_known": True, "z_observed": False, "z_estimated": True,
                "z_source": "NAVMESH_LAYER_PROBE", "z_confidence": round(layer.confidence, 3)}}
            route = self._global_planner.plan(request, probe_state, now, danger_map=self._danger)
            if route.anchors and not self._fall_hazard_blocks(route, probe_state, now):
                return probe_state, route
        return None

    # REV4 split: combat range/LOS repositioning and facing live in
    # navigation_combat.CombatLocalPositioningAdapter; these keep the API.
    def local_combat_reposition(self, state: dict, request: dict) -> tuple[Command, ...]:
        return self.combat_positioning.local_combat_reposition(state, request)

    def reposition_for_los(self, state: dict, entity_ref: str | None,
                           observation_id: str, now: float, *,
                           desired_range: float = 4.5, defer_plan: bool = False,
                           deadline: float | None = None) -> dict | None:
        return self.combat_positioning.reposition_for_los(
            state, entity_ref, observation_id, now, desired_range=desired_range,
            defer_plan=defer_plan, deadline=deadline)

    def record_los_exhaustion(self, entity_ref: str | None, state: dict, now: float) -> bool:
        return self.combat_positioning.record_los_exhaustion(entity_ref, state, now)

    def face_entity(self, state: dict, entity_ref: str | None):
        return self.combat_positioning.face_entity(state, entity_ref)

    @property
    def _latest_los_recovery(self) -> dict[str, Any] | None:
        return self.combat_positioning.latest_los_recovery

    @_latest_los_recovery.setter
    def _latest_los_recovery(self, value) -> None:
        self.combat_positioning.latest_los_recovery = value

    # REV4 split: own-layer continuity, route-height hints, search-cell floor
    # checks and destination-height resolution live in
    # layer_resolver.DestinationLayerResolver; these keep the service API.
    def _route_hint_z(self, state: dict) -> float | None:
        return self.layer_resolver.route_hint_z(self._active_route, state)

    def _state_with_layer_continuity(self, state: dict, now: float) -> dict:
        return self.layer_resolver.with_layer_continuity(state, now)

    def search_cell_on_player_floor(self, waypoint: dict) -> bool:
        return self.layer_resolver.search_cell_on_player_floor(waypoint)

    def _resolve_destination_z(self, request: NavigationRequest, state: dict, now: float) -> NavigationRequest:
        return self.layer_resolver.resolve_destination_z(request, state, now)

    # REV4 split: the drop/corridor-centre geometry lives in
    # hazard_route.HazardAwareRouteValidator; these keep the service API.
    def _away_from_drops(self, route):
        request = self._active_request
        return self.hazard_route.center(
            route, request.destination.get("instance_id") if request is not None else None)

    def _segment_walkable(self, instance_id: int, a: tuple, b: tuple) -> bool:
        return self.hazard_route.segment_walkable(instance_id, a, b)

    def _without_drop_spikes(self, anchors: list) -> list:
        return self.hazard_route.without_drop_spikes(anchors)

    @staticmethod
    def _xyz(anchor: dict) -> tuple:
        return float(anchor["x"]), float(anchor["y"]), float(anchor["z"])

    def _note_offset_stuck(self, state: dict) -> None:
        """Stuck on a moved (centred) point: plan the raw navmesh corners here.

        The navmesh does not know every rock or prop; a centred point that
        could not be reached proves the corridor narrower than it looks.
        """
        route, index = self._active_route, self._route_waypoint_index
        if route is None or not route.anchors:
            return
        anchor = route.anchors[min(max(0, index), len(route.anchors)-1)]
        position = state.get("player_world_position") or {}
        x, y, z = number(position.get("x")), number(position.get("y")), number(anchor.get("z"))
        if not anchor.get("drop_offset") or None in (x, y, z):
            return
        self.hazard_route.note_offset_stuck(x, y, z)

    def _short_leg_route(self, route: GlobalRoute, yards: float | None = None) -> GlobalRoute:
        """The first ``LOW_CONFIDENCE_LEG_YARDS`` of a route to an unsure target."""
        limit = self.LOW_CONFIDENCE_LEG_YARDS if yards is None else float(yards)
        anchors, travelled = [route.anchors[0]] if route.anchors else [], 0.
        for left, right in zip(route.anchors, route.anchors[1:]):
            step = math.dist((float(left["x"]), float(left["y"]), float(left.get("z", 0.))),
                             (float(right["x"]), float(right["y"]), float(right.get("z", 0.))))
            if travelled + step > limit:
                # Simplification can leave one 80-yard edge. Appending that
                # whole edge defeated both the 12- and 30-yard safety limits.
                part = max(0., (limit-travelled) / step)
                point = {**right, **{key: float(left.get(key, 0.)) +
                         part*(float(right.get(key, 0.))-float(left.get(key, 0.)))
                         for key in ("x", "y", "z")}}
                anchors.append(point)
                regions = route.regions or ({},)
                return replace(route, anchors=tuple(anchors), regions=tuple(
                    {**region, "partial_localization_leg": True} for region in regions))
            anchors.append(right)
            travelled += step
            if travelled >= limit:
                break
        regions = route.regions
        if len(anchors) < len(route.anchors):
            regions = tuple({**region, "partial_localization_leg": True}
                            for region in (regions or ({},)))
        return replace(route, anchors=tuple(anchors), regions=regions)

    @staticmethod
    def _partial_localization_route(route: GlobalRoute) -> bool:
        return any(region.get("partial_localization_leg") for region in route.regions)

    def _bounded_localization_route(self, route: GlobalRoute) -> GlobalRoute:
        """The same floor-evidence bound applies at every replan boundary."""
        request = self._active_request
        if request is None or not route.anchors:
            return route
        if self.__dict__.get("_layer_probe"):
            return self._short_leg_route(route, self.LAYER_PROBE_YARDS)
        confidence = number(request.destination.get("z_confidence"))
        if confidence is not None and confidence < self._z.LOW_CONFIDENCE:
            return self._short_leg_route(route)
        return route

    # User 2026-10-05: "járja be a zónát, csak párhuzamosan seekeljen is ...
    # itt a quest zóna több Z-n keresztül van, járható navmeshen lefelé illetve
    # felfelé".  The route from the rim to the deepest reachable point *is*
    # the multi-floor zone (Hrun's spiral).  It is walked in short hops so
    # the planner re-decides after each one (yellow dot, combat, seek,
    # inspect); at the bottom the hops are walked back up once.
    ZONE_SWEEP_HOP_YARDS = 15.
    ZONE_SWEEP_VISITED_YARDS = 6.
    ZONE_SWEEP_LAYER_YARDS = 5.

    def overlay_snapshot(self, state: dict) -> dict | None:
        """Compact route view for LIVE VISION (design doc §11), or None."""
        player = state.get("player_world_position") or {}
        try:
            px, py = float(player["x"]), float(player["y"])
        except (KeyError, TypeError, ValueError):
            return None
        last = self._player_layer
        pz = (last[3] if last is not None
              and math.hypot(last[1]-px, last[2]-py) <= self.LAYER_CONTINUITY_YARDS else None)

        def triple(point) -> list:
            return [round(float(point["x"]), 1), round(float(point["y"]), 1),
                    round(float(point["z"]), 1) if isinstance(point.get("z"), (int, float)) else None]
        route = self._active_route
        request = self._active_request
        anchors = [triple(anchor) for anchor in (route.anchors if route is not None else ())
                   if isinstance(anchor, dict) and "x" in anchor and "y" in anchor][:80]
        destination = (request.destination if request is not None else None) or {}
        result = {"player": {"x": round(px, 1), "y": round(py, 1),
                             "z": round(pz, 1) if pz is not None else None,
                             "z_confidence": round(self._z.player.confidence, 2)
                             if self._z.player is not None else None,
                             "layer_id": self._z.player.layer_id if self._z.player is not None else None,
                             "facing": number(state.get("orientation")) or 0.},
                  "route": anchors if self._route_failure_reason is None else [],
                  "next_index": int(self._route_waypoint_index or 0),
                  "purpose": destination.get("purpose"),
                  "route_failure_reason": self._route_failure_reason,
                  "target_layer_id": destination.get("layer_id"),
                  "target_z_confidence": destination.get("z_confidence"),
                  "destination": (triple(destination)
                                  if "x" in destination and "y" in destination else None)}
        sweep = (self.__dict__.get("_zone_sweeps") or {}).get(self.__dict__.get("_last_sweep_key"))
        if sweep and sweep.get("hops"):
            result["sweep"] = {"hops": [triple(hop) for hop in sweep["hops"]],
                               "visited": sorted(sweep.get("visited") or ()),
                               "direction": "UP" if sweep.get("upward") else "DOWN",
                               "done": bool(sweep.get("done"))}
        return result

    def zone_sweep_next(self, state: dict, destination: dict, key) -> dict | None:
        """Next hop of the multi-floor zone sweep around a quest POI, or None."""
        self._last_sweep_key = key
        sweeps = self.__dict__.setdefault("_zone_sweeps", {})
        sweep = sweeps.get(key)
        if sweep is None:
            bottom = self.lower_layer_point(state, destination)
            if bottom is None and not destination.get("sweep_targets"):
                sweeps[key] = {"hops": [], "done": True}
                return None
            hops = self._sweep_hops(state, bottom, destination.get("sweep_targets") or ())
            sweep = sweeps[key] = {"hops": hops, "visited": set(), "upward": False, "done": not hops}
        if sweep.get("done"):
            return None
        hops = sweep["hops"]
        player = state.get("player_world_position") or {}
        try:
            px, py = float(player["x"]), float(player["y"])
        except (KeyError, TypeError, ValueError):
            return None
        resolved = self._z.player
        now = number(state.get("monotonic_time"))
        # ``monotonic_time`` is the addon's GetTime() at sampling; the fix
        # time is the agent clock at processing, normally ~0.1 s later.  A
        # one-sided test rejected every live fix (live 2026-10-07: hop 4 was
        # offered for minutes), so freshness is a symmetric window.
        pz = (resolved.z if resolved is not None
              and resolved.instance_id == player.get("instance_id")
              and resolved.confidence >= .7
              and math.hypot(resolved.x-px, resolved.y-py) <= self.ZONE_SWEEP_VISITED_YARDS
              and (now is None or resolved.at is None or abs(now-resolved.at) <= 3.)
              else None)
        for index, hop in enumerate(hops):
            if (pz is not None
                    and math.hypot(hop["x"]-px, hop["y"]-py) <= self.ZONE_SWEEP_VISITED_YARDS
                    and abs(hop["z"]-pz) <= self.ZONE_SWEEP_LAYER_YARDS):
                sweep["visited"].add(index)
            elif pz is not None and (hop["z"] > pz + self.ZONE_SWEEP_LAYER_YARDS if not sweep["upward"]
                                     else hop["z"] < pz - self.ZONE_SWEEP_LAYER_YARDS):
                # Already past it on this walk (live 2026-10-06: after a fall
                # the sweep offered the hop above again and climbed back up).
                sweep["visited"].add(index)
        order = range(len(hops)-1, -1, -1) if sweep["upward"] else range(len(hops))
        furthest = max((position for position, index in enumerate(order) if index in sweep["visited"]),
                       default=-1)
        remaining = [index for position, index in enumerate(order) if position > furthest]
        if not remaining:
            if sweep["upward"]:
                sweep["done"] = True
                return None
            sweep["upward"], sweep["visited"] = True, {len(hops)-1}
            return self.zone_sweep_next(state, destination, key)
        hop = hops[remaining[0]]
        return {"x": hop["x"], "y": hop["y"], "z": hop["z"], "z_known": True, "layer_z": hop["z"],
                "z_source": "TDB_SPAWN" if hop.get("target") else "NAVMESH_ZONE_SWEEP",
                "z_estimated": True,
                "sweep_hop": remaining[0], "sweep_hops": len(hops),
                **({"sweep_target": True, "reference_hint_id": hop.get("hint")} if hop.get("target") else {}),
                "sweep_direction": "UP" if sweep["upward"] else "DOWN"}

    def record_sweep_arrival(self, destination: dict | None) -> bool:
        """A verified arrival at a zone-sweep hop retires that hop.

        Live 2026-10-07: the planner-side position test ran only after the
        next (area-search) MOVE had taken the player 8 yd away, so the same
        hop came back after every arrival.  The hop must match the current
        sweep's own coordinates; anything else is ignored.
        """
        if not isinstance(destination, dict) or destination.get("location_source") != "QUEST_ZONE_SWEEP":
            return False
        index = destination.get("sweep_hop")
        sweep = (self.__dict__.get("_zone_sweeps") or {}).get(self.__dict__.get("_last_sweep_key"))
        if (not isinstance(index, int) or isinstance(index, bool) or not isinstance(sweep, dict)
                or "visited" not in sweep or not 0 <= index < len(sweep.get("hops") or ())):
            return False
        hop, x, y = sweep["hops"][index], number(destination.get("x")), number(destination.get("y"))
        if x is None or y is None or math.hypot(hop["x"]-x, hop["y"]-y) > 1.:
            return False
        sweep["visited"].add(index)
        return True

    # REV4 split: the sweep's hop geometry and the lower-layer search live in
    # zone_sweep.ZoneSweepGeometry; the sweep ledger (hops visited, direction,
    # done) stays here because the planner and the arrival check share it.
    def _sweep_hops(self, state: dict, bottom: dict | None, targets=()) -> list[dict]:
        return self.zone_geometry.sweep_hops(state, bottom, targets)

    def _route_hops(self, state: dict, bottom: dict) -> list[dict]:
        return self.zone_geometry.route_hops(state, bottom)

    def lower_layer_point(self, state: dict, destination: dict) -> dict | None:
        return self.zone_geometry.lower_layer_point(state, destination)

    # REV4 split: the planning-only floor/cost queries live in
    # travel_cost.TravelCostQueryPort; these keep the service API (the agent
    # engine binds them as its travel_cost / player_layer / step guards).
    def object_pull_step_safe(self, state: dict) -> bool:
        return self.travel_cost.object_pull_step_safe(state)

    def recovery_step_drops(self, state: dict, step: str) -> bool:
        return self.travel_cost.recovery_step_drops(state, step)

    def player_layer_z(self, state: dict) -> float | None:
        return self.travel_cost.player_layer_z(state)

    def walk_cost(self, state: dict, destination: dict) -> float | None:
        return self.travel_cost.walk_cost(state, destination)

    LANDED_OFF_ROUTE_YARDS = 3.
    # Live 2026-10-13 17:57: at a walkway's edge the character stepped off,
    # slid back and stepped off again (a 0-1 s fall every second) for 25 s;
    # each falling sample paused the stuck evidence, so nothing recovered.
    SLIP_WINDOW_SECONDS = 8.
    SLIP_COUNT = 3
    SLIP_RADIUS_YARDS = 3.

    def _slipping_in_place(self, state: dict, clock: float) -> bool:
        position = state.get("player_world_position") or {}
        x, y = number(position.get("x")), number(position.get("y"))
        if x is None or y is None:
            return False
        starts = [row for row in self.__dict__.get("_slip_starts", ())
                  if 0 <= clock-row[0] <= self.SLIP_WINDOW_SECONDS]
        starts.append((clock, x, y))
        self._slip_starts = starts
        if (len(starts) >= self.SLIP_COUNT
                and all(math.hypot(sx-x, sy-y) <= self.SLIP_RADIUS_YARDS for _t, sx, sy in starts)):
            self._slip_starts = []
            return True
        return False

    def _off_route_yards(self, state: dict) -> float:
        """2D distance from the player to the rest of the active route."""
        route = self._active_route
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        anchors = list(getattr(route, "anchors", None) or ())[max(0, int(self._route_waypoint_index or 0)-1):]
        points = [(number(a.get("x")), number(a.get("y"))) for a in anchors if isinstance(a, dict)]
        points = [(x, y) for x, y in points if x is not None and y is not None]
        if px is None or py is None or not points:
            return 0.
        if len(points) == 1:
            return math.hypot(points[0][0]-px, points[0][1]-py)
        best = float("inf")
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            vx, vy = bx-ax, by-ay
            length = vx*vx + vy*vy
            t = 0. if length <= 1e-9 else max(0., min(1., ((px-ax)*vx+(py-ay)*vy)/length))
            best = min(best, math.hypot(px-(ax+t*vx), py-(ay+t*vy)))
        return best

    @property
    def last_route(self) -> list[str]:
        return list(self._routes.last_route)

    # Read-only migration views for existing diagnostics/tests.  The engine
    # itself calls the service API above and never owns these objects.
    @property
    def route_knowledge(self) -> AgentNavigator:
        return self._routes

    @property
    def movement_controller(self) -> ReachMovementController:
        return self._movement
