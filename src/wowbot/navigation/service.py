"""Canonical telemetry-assisted movement service for the active agent path.

Route knowledge and closed-loop movement are private components.  Callers use
this service, never either component as an independent navigation authority.
"""
from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
from typing import Any

from wowbot.agent.movement_controller import MovementAssessment, MovementPhase, ReachMovementController
from wowbot.agent.models import number
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
from .navigation_combat import NavigationCombatMixin
from .navigation_search import NavigationSearchMixin
from .z_resolver import ZResolver


class NavigationService(NavigationSearchMixin, NavigationCombatMixin, NavigationRecoveryMixin):
    def __init__(self, bindings=None, *, navmesh=None) -> None:
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
        self._handled_falls = 0
        self._global_planner = GlobalNavigator(navmesh=self._navmesh, walkable=self.walkable_point)
        self._corridor_builder = PathCorridorBuilder()
        self._local_planner = LocalNavigator()
        self._stuck_classifier = StuckClassifier()
        self._los_recovery = LosRecoveryPlanner()
        self._latest_los_recovery: dict[str, Any] | None = None
        self._active_request: NavigationRequest | None = None
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
        if not keep_floor:
            self._z = ZResolver(self._z.geometry)
        for key in ("_zone_sweeps", "_lower_layer_cache", "_last_sweep_key",
                    "_ambiguous_since"):
            self.__dict__.pop(key, None)
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
        self.__dict__.pop("_pending_recovery_directive", None)

    def close(self) -> None:
        if self._navmesh is not None:
            self._navmesh.close()

    def cancel_movement(self) -> None:
        self._movement.reset()
        self._active_request = None
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

    def start(self, destination: dict, state: dict, observation_id: str, now: float) -> None:
        self._movement.start(destination, state, observation_id, now)

    def start_request(self, request: NavigationRequest, state: dict, now: float) -> None:
        """Accept one typed request and delegate all control to the existing controller."""
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
        self._active_route = (probe_route if probe_route is not None else
                              self._global_planner.plan(request, state, now, danger_map=self._danger))
        confidence = number(request.destination.get("z_confidence"))
        if confidence is not None and confidence < self._z.LOW_CONFIDENCE and self._active_route.anchors:
            self._active_route = self._short_leg_route(self._active_route)
        if self._layer_probe and self._active_route.anchors:
            self._active_route = self._short_leg_route(self._active_route, self.LAYER_PROBE_YARDS)
        self._route_danger_revision = self._danger.revision
        self._route_waypoint_index = self._first_route_index(state)
        self._route_previous_position = self._player_route_position(state)
        self._active_corridor = self._corridor_builder.build(self._active_route)
        state = self._state_with_navmesh_surface(state)
        self._latest_local_plan = self._local_planner.plan(
            state, self._active_corridor, destination=request.destination)
        if not self._active_route.anchors:
            self._route_failure_reason = "required_navmesh_route_unavailable"
            self._movement.reset()
            return
        self._route_failure_reason = None
        destination = self._current_route_destination()
        if request.arrival.radius is not None and destination.get("route_waypoint_final"):
            destination["arrival_radius"] = request.arrival.radius
        if request.arrival.desired_range is not None and destination.get("route_waypoint_final"):
            destination["stop_distance"] = request.arrival.desired_range
        self.start(destination, state, request.correlation_id, now)

    # Live 2026-10-04 00:41: Detour's first corner lay 1.1 yd from the player.
    # Every replan (the danger map changes with nearby mobs) restarted the
    # route at that corner, which counted as arrived at once, so the next
    # waypoint was never steered to and the character stood still.
    ROUTE_START_SKIP_YARDS = 3.0
    WAYPOINT_LAYER_YARDS = 6.
    # User 2026-10-06: "a spirálon ... eléggé a szélén megy".  Taking a
    # waypoint 2.5 yd early cut every bend of the spiral toward the drop.
    INTERMEDIATE_PASS_YARDS = 1.5
    NEXT_LEG_YARDS = 2.5

    NEXT_LEG_LOOKAHEAD = 4

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
        final = index == final_index
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
        else:
            if request.arrival.radius is not None:
                destination["arrival_radius"] = request.arrival.radius
            if request.arrival.desired_range is not None:
                destination["stop_distance"] = request.arrival.desired_range
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
        """Refresh a read-only local plan for the current route/corridor.

        This is deliberately called by the navigation owner.  The returned
        plan is not a command and cannot bypass the movement controller.
        A confirmed central obstruction asks for a local replan; it does not
        infer a fake world-space detour from screen pixels.
        """
        if self._active_request is None or self._route_failure_reason:
            return None
        state = self._state_with_navmesh_surface(state)
        self._danger.observe_hostiles(state, now)
        danger_changed = self._danger.revision != self._route_danger_revision
        if self._global_planner.needs_replan(
                self._active_route, self._active_request, state, now,
                danger_changed=danger_changed):
            self._active_route = self._global_planner.plan(
                self._active_request, state, now, danger_map=self._danger)
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
                       allow_dead: bool = False) -> dict | None:
        """Start or refresh one canonical reach attempt for a selected entity.

        This is intentionally the only entity-approach entry point.  It
        accepts an exact, currently selected entity plus simultaneous world
        positions; it never extrapolates a screen pixel into world space.
        Callers retain ownership of their skill FSM while this service owns
        the movement controller and route knowledge.
        """
        expected = world_entity_id(entity_ref)
        target = state.get("target") or {}
        if not expected or str(target.get("guid") or "") != expected:
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
        sample_at = number(target.get("sample_time", state.get("target_sample_time")))
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
        destination = {
            "target_guid": expected,
            "purpose": "INTERACT",
            "coordinate_space": "WORLD_YARDS",
            "x": tx,
            "y": ty,
            "z": number(position.get("z")) or 0.,
            "instance_id": target_instance,
            "world_map_id": target_instance,
            "stop_distance": float(stop_distance),
            "avoid_combat": bool(target.get("avoid_combat", False)),
            "allow_combat": bool(target.get("allow_combat", False)),
        }
        self.start(destination, state, observation_id, now)
        return destination

    def observe(self, state: dict, observation_id: str, now: float, *, commanded: bool = True):
        if self._route_failure_reason:
            return MovementAssessment(MovementPhase.FAILED, True, False,
                                      self._route_failure_reason)
        self._z.observe_player(state, now, route_z=self._route_hint_z(state))
        fell = self._z.fall_count > self._handled_falls
        self._handled_falls = self._z.fall_count
        passed = self._sweep_hop_passed()
        if passed is not None:
            return passed
        if fell and self._active_request is not None:
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
        state = self._state_with_navmesh_surface(state)
        if self._intermediate_waypoint_passed(state):
            self._route_waypoint_index += 1
            self.start(self._current_route_destination(), state,
                       f"{observation_id}:route:{self._route_waypoint_index}", now)
            return MovementAssessment(MovementPhase.MOVING, False, False,
                                      "route_waypoint_advanced")
        assessment = self._movement.observe(state, observation_id, now, commanded=commanded)
        wrong_layer = self._destination_on_other_layer(state, assessment)
        if wrong_layer is not None:
            return wrong_layer
        route = self._active_route
        if (assessment.terminal and assessment.success and route is not None
                and self._route_waypoint_index < len(route.anchors)-1
                and assessment.reason == "reach_arrival_verified"):
            self._route_waypoint_index += 1
            self._route_previous_position = self._player_route_position(state)
            self.start(self._current_route_destination(), state,
                       f"{observation_id}:route:{self._route_waypoint_index}", now)
            return MovementAssessment(MovementPhase.MOVING, False, False,
                                      "route_waypoint_advanced")
        return assessment

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
        if self._route_failure_reason:
            return ()
        state = self._state_with_navmesh_surface(state)
        self.local_plan(state, now=now, observation_id=observation_id)
        return self._movement.command(state, observation_id, now)

    def _state_with_navmesh_surface(self, state: dict) -> dict:
        """Refresh player Z from the active mmap corridor without mutating WorldModel."""
        route, navmesh = self._active_route, self._navmesh
        projector = getattr(navmesh, "project_position", None)
        player = state.get("player_world_position") or {}
        if route is None or not route.anchors or not callable(projector):
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
        snapshot = {"route": self._routes.snapshot(now), "movement": self._movement.snapshot(),
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
        snapshot["z_resolver"] = self._z.snapshot()
        snapshot["route_danger_revision"] = self._route_danger_revision
        snapshot["route_failure_reason"] = self._route_failure_reason
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

    def movement_snapshot(self) -> dict[str, Any]:
        return self._movement.snapshot()

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

    ROUTE_HINT_CORRIDOR_YARDS = 4.

    def _route_hint_z(self, state: dict) -> float | None:
        """The active route's height where the player stands on it.

        Live 2026-10-06 21:29: walking down the ramp from the entrance, the
        rim polygon overhangs the ramp; continuity kept the rim (93.5) while
        the player was at ~78, the waypoint below was "on another layer" and
        never passed, and the character turned back and forth for 30 s.
        The route the controller is following is the best tie-breaker."""
        route, player = self._active_route, state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        if route is None or not route.anchors or px is None or py is None:
            return None
        best = None
        anchors = [anchor for anchor in route.anchors if number(anchor.get("z")) is not None]
        for left, right in zip(anchors, anchors[1:]) if len(anchors) > 1 else ():
            ax, ay, az = float(left["x"]), float(left["y"]), float(left["z"])
            bx, by, bz = float(right["x"]), float(right["y"]), float(right["z"])
            vx, vy = bx-ax, by-ay
            length_sq = vx*vx + vy*vy
            t = 0. if length_sq <= 1e-9 else max(0., min(1., ((px-ax)*vx + (py-ay)*vy)/length_sq))
            distance = math.hypot(ax+t*vx-px, ay+t*vy-py)
            if best is None or distance < best[0]:
                best = (distance, az+t*(bz-az))
        if best is None and anchors:
            nearest = min(anchors, key=lambda anchor: (float(anchor["x"])-px)**2 + (float(anchor["y"])-py)**2)
            best = (math.hypot(float(nearest["x"])-px, float(nearest["y"])-py), float(nearest["z"]))
        return best[1] if best is not None and best[0] <= self.ROUTE_HINT_CORRIDOR_YARDS else None

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
        self._active_route = self._global_planner.plan(
            self._active_request, layered, now, danger_map=self._danger)
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

    def _state_with_layer_continuity(self, state: dict, now: float) -> dict:
        """A new route starts on the resolved own layer (an estimate, never observed)."""
        player = state.get("player_world_position") or {}
        if player.get("z_observed") is True and "z" in player:
            return state
        try:
            instance_id, x, y = int(player["instance_id"]), float(player["x"]), float(player["y"])
        except (KeyError, TypeError, ValueError):
            return state
        resolved = self._z.current_player(instance_id, x, y, now)
        if resolved is None:
            return state
        return {**state, "player_world_position": {
            **player, "z": resolved.z, "z_known": True, "z_observed": False,
            "z_estimated": True, "z_source": "NAVMESH_LAYER_CONTINUITY",
            "z_confidence": round(resolved.confidence, 3), "layer_id": resolved.layer_id}}

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

    SEARCH_CELL_FLOOR_YARDS = 15.

    def search_cell_on_player_floor(self, waypoint: dict) -> bool:
        """Live 2026-10-06 21:16: a height-less quest-area cell resolved onto
        the rim and the agent ran up the spiral to the entrance and back.
        In a cave, a search cell is walked only on (about) the player's floor."""
        player = self._z.player
        if (player is None or player.confidence < .6
                or waypoint.get("coordinate_space") != "WORLD_YARDS" or waypoint.get("z") is not None
                or self._z._indoors is not True):
            return True
        x, y = number(waypoint.get("x")), number(waypoint.get("y"))
        if x is None or y is None:
            return True
        target = self._z.resolve_target(player.instance_id, x, y, player=player, floor_hint="SAME")
        self._z.last_target = None
        return target is not None and abs(target.z-player.z) <= self.SEARCH_CELL_FLOOR_YARDS

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
            if route.anchors:
                return probe_state, route
        return None

    def _resolve_destination_z(self, request: NavigationRequest, state: dict, now: float) -> NavigationRequest:
        destination = dict(request.destination)
        origin = destination.get("z_resolved_from")
        if destination.get("coordinate_space") != "WORLD_YARDS":
            return request
        if not origin and number(destination.get("z")) is not None and destination.get("z_known") is not False:
            return request
        player = state.get("player_world_position") or {}
        try:
            instance_id = int(destination.get("instance_id", player.get("instance_id")))
            x, y = ((float(origin["x"]), float(origin["y"])) if origin
                    else (float(destination["x"]), float(destination["y"])))
            px, py = float(player["x"]), float(player["y"])
        except (KeyError, TypeError, ValueError):
            return request
        resolved_player = self._z.current_player(instance_id, px, py, now)
        hint = destination.get("floor_hint") or {"LOWER": "BELOW", "UPPER": "ABOVE"}.get(
            str(destination.get("destination_layer") or ""))
        target = self._z.resolve_target(instance_id, x, y, player=resolved_player, floor_hint=hint)
        if target is None:
            if hint in {"SAME", "ABOVE", "BELOW"}:
                destination["z_resolution_failed"] = (self._z.last_target_failure
                                                       or "no_reachable_target_layer")
                return replace(request, destination=destination)
            return request
        moved = math.hypot(target.x-x, target.y-y) > self._z.LAYER_RADIUS
        destination.update({
            "x": target.x if moved else x, "y": target.y if moved else y, "z": target.z,
            "z_known": True, "z_observed": False, "z_estimated": True,
            "z_source": f"Z_RESOLVER_{target.source}", "z_confidence": round(target.confidence, 3),
            "layer_id": getattr(target, "layer_id", None),
            "z_resolved_from": {"x": x, "y": y}, "z_alternatives": list(target.alternatives)[:6]})
        destination.pop("z_resolution_failed", None)
        return replace(request, destination=destination)

    def _short_leg_route(self, route: GlobalRoute, yards: float | None = None) -> GlobalRoute:
        """The first ``LOW_CONFIDENCE_LEG_YARDS`` of a route to an unsure target."""
        limit = self.LOW_CONFIDENCE_LEG_YARDS if yards is None else float(yards)
        anchors, travelled = [route.anchors[0]] if route.anchors else [], 0.
        for left, right in zip(route.anchors, route.anchors[1:]):
            step = math.dist((float(left["x"]), float(left["y"]), float(left.get("z", 0.))),
                             (float(right["x"]), float(right["y"]), float(right.get("z", 0.))))
            anchors.append(right)
            travelled += step
            if travelled >= limit:
                break
        return replace(route, anchors=tuple(anchors))

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
            if bottom is None:
                sweeps[key] = {"hops": [], "done": True}
                return None
            hops = self._sweep_hops(state, bottom)
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
        pz = (resolved.z if resolved is not None
              and resolved.instance_id == player.get("instance_id")
              and resolved.confidence >= .7
              and math.hypot(resolved.x-px, resolved.y-py) <= self.ZONE_SWEEP_VISITED_YARDS
              and (now is None or resolved.at is None or 0 <= now-resolved.at <= 3.)
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
                "z_source": "NAVMESH_ZONE_SWEEP", "z_estimated": True,
                "sweep_hop": remaining[0], "sweep_hops": len(hops),
                "sweep_direction": "UP" if sweep["upward"] else "DOWN"}

    def _sweep_hops(self, state: dict, bottom: dict) -> list[dict]:
        """The rim-to-bottom route resampled every ``ZONE_SWEEP_HOP_YARDS``."""
        find = getattr(self._navmesh, "find_path", None)
        player = state.get("player_world_position") or {}
        try:
            instance_id = int(player["instance_id"])
            start = {"x": float(player["x"]), "y": float(player["y"]), "instance_id": instance_id}
        except (KeyError, TypeError, ValueError):
            return []
        last = self._player_layer
        if (last is not None and last[0] == instance_id
                and math.hypot(last[1]-start["x"], last[2]-start["y"]) <= self.LAYER_CONTINUITY_YARDS):
            # Start on the tracked own layer (an estimate: the navmesh may still probe).
            start.update({"z": last[3], "z_known": True, "z_estimated": True,
                          "z_source": "NAVMESH_LAYER_CONTINUITY"})
        if not callable(find):
            return []
        path = find(instance_id, start, {**bottom, "instance_id": instance_id})
        anchors = [anchor for anchor in (path.anchors if path is not None else ())
                   if isinstance(anchor.get("z"), (int, float))]
        if len(anchors) < 2:
            return []
        hops, travelled = [], 0.
        for left, right in zip(anchors, anchors[1:]):
            a = (float(left["x"]), float(left["y"]), float(left["z"]))
            b = (float(right["x"]), float(right["y"]), float(right["z"]))
            segment = math.dist(a, b)
            position = 0.
            while segment > 0 and travelled + (segment-position) >= self.ZONE_SWEEP_HOP_YARDS:
                position += self.ZONE_SWEEP_HOP_YARDS - travelled
                ratio = position/segment
                hops.append({"x": a[0]+(b[0]-a[0])*ratio, "y": a[1]+(b[1]-a[1])*ratio,
                             "z": a[2]+(b[2]-a[2])*ratio})
                travelled = 0.
            travelled += segment - position
        end = anchors[-1]
        hops.append({"x": float(end["x"]), "y": float(end["y"]), "z": float(end["z"])})
        return hops

    LOWER_LAYER_RADIUS_YARDS = 35.
    LOWER_LAYER_MIN_DROP_YARDS = 15.
    LOWER_LAYER_SURFACE_YARDS = 6.
    LOWER_LAYER_MAX_ROUTES = 12

    def lower_layer_point(self, state: dict, destination: dict) -> dict | None:
        """The deepest reachable walkable point next to a quest location.

        Design doc §5 (live 2026-10-05 12:25, "Who Lurks in the Pit"): the
        quest POI sits on the rim of a pit; its cocoons are ~110 yd lower,
        reached by a spiral path.  Without Z the POI projects onto the rim
        and the agent "arrived" there.  This returns a point on a walkable
        layer at least 15 yd under the POI's own surface, within 35 yd, that
        the mmap connects to the player (route found), else None.  Planning
        only: the caller turns it into a normal navmesh MOVE.
        """
        navmesh = self._navmesh
        near = getattr(navmesh, "walkable_points_near", None)
        find = getattr(navmesh, "find_path", None)
        project = getattr(navmesh, "project_position", None)
        player = state.get("player_world_position") or {}
        try:
            instance_id = int(destination.get("instance_id", player.get("instance_id")))
            x, y = float(destination["x"]), float(destination["y"])
            px, py = float(player["x"]), float(player["y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (callable(near) and callable(find) and callable(project)):
            return None
        cache = self.__dict__.setdefault("_lower_layer_cache", {})
        key = (instance_id, round(x), round(y))
        if key in cache:
            return cache[key]
        points = [point for point in near(instance_id, {"x": x, "y": y}, self.LOWER_LAYER_RADIUS_YARDS)
                  if isinstance(point.get("z"), (int, float))]
        rim = [point["z"] for point in points
               if math.hypot(point["x"]-x, point["y"]-y) <= self.LOWER_LAYER_SURFACE_YARDS]
        result = None
        if rim:
            surface = max(rim)
            deep = sorted((point for point in points
                           if point["z"] <= surface - self.LOWER_LAYER_MIN_DROP_YARDS),
                          key=lambda point: (point["z"], math.hypot(point["x"]-x, point["y"]-y)))
            tracked = self._player_layer
            hint = (tracked[3] if tracked is not None and tracked[0] == instance_id
                    and math.hypot(tracked[1]-px, tracked[2]-py) <= self.LAYER_CONTINUITY_YARDS else None)
            start = project(instance_id, {"x": px, "y": py, "instance_id": instance_id}, z_hint=hint)
            failed: list[dict] = []
            attempts = 0
            for point in deep:
                if start is None or attempts >= self.LOWER_LAYER_MAX_ROUTES:
                    break
                if any(math.dist((point["x"], point["y"], point["z"]),
                                 (other["x"], other["y"], other["z"])) <= 8. for other in failed):
                    continue      # same unreachable pocket (an isolated covered region)
                attempts += 1
                target = {"x": point["x"], "y": point["y"], "z": point["z"], "z_known": True,
                          "instance_id": instance_id}
                path = find(instance_id, start, target)
                end = path.anchors[-1] if path is not None and path.anchors else None
                if end is not None and math.dist(
                        (float(end["x"]), float(end["y"]), float(end.get("z", point["z"]))),
                        (point["x"], point["y"], point["z"])) <= 6.:
                    result = {"x": point["x"], "y": point["y"], "z": point["z"],
                              "z_known": True, "layer_z": point["z"],
                              "z_source": "NAVMESH_LOWER_LAYER",
                              "drop_yards": round(surface-point["z"], 1),
                              "route_yards": round(float(path.cost), 1)}
                    break
                failed.append(point)
        if len(cache) > 64:
            cache.clear()
        cache[key] = result
        return result

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
