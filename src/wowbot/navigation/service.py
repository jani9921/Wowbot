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
from wowbot.agent.models import Command, number
from wowbot.agent.navigation import AgentNavigator
from .facing import FaceController, FaceResult
from .navigation_context import NavigationContext, NavigationContextAssessment, NavigationContextClassifier
from .navigation_mode import NavigationMode, NavigationModeEvidence, resolve_navigation_mode
from .progress import ProgressMonitor, ProgressPhase
from .transition_resolver import TransitionAssessment, TransitionResolver
from .stuck_resolver import RecoveryDirective, StuckResolver, StuckResolutionState
from .danger import DangerMap
from .reachability import ReachabilityModel
from .search_coverage import SearchCoveragePlanner
from .contracts import ArrivalEnvelope, GlobalRoute, LocalMotionPlan, NavigationRequest, PathCorridor
from .global_planner import GlobalNavigator
from .corridor import PathCorridorBuilder
from .local_planner import LocalNavigator
from .stuck_classifier import StuckClassifier
from .mmap_navmesh import TrinityMMapNavMesh
from .los_recovery import LosRecoveryPlanner
from wowbot.runtime import world_entity_id


class NavigationService:
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

    def reset(self) -> None:
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
        self._active_request = request
        self._danger.observe_hostiles(state, now)
        self._active_route = self._global_planner.plan(request, state, now, danger_map=self._danger)
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
        if not final:
            destination.pop("stop_distance", None)
            destination.pop("arrival_radius", None)
            destination["purpose"] = "ROUTE_WAYPOINT"
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
        # Six yards is deliberately limited to intermediate anchors.  It is
        # large enough for measured live sampling gaps while remaining much
        # smaller than ordinary mmap anchor spacing.
        pass_radius = 6.0
        if math.hypot(current[0]-wx, current[1]-wy) <= pass_radius:
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
        state = self._state_with_navmesh_surface(state)
        if self._intermediate_waypoint_passed(state):
            self._route_waypoint_index += 1
            self.start(self._current_route_destination(), state,
                       f"{observation_id}:route:{self._route_waypoint_index}", now)
            return MovementAssessment(MovementPhase.MOVING, False, False,
                                      "route_waypoint_advanced")
        assessment = self._movement.observe(state, observation_id, now, commanded=commanded)
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
        z_hint = number(nearest.get("z"))
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

    def mark_recovery(self) -> None:
        self._movement.mark_recovery()

    def begin_stuck_recovery(self, correlation_id: str, now: float, state: dict | None = None) -> RecoveryDirective:
        """Expose one evidence-gated recovery decision; never send input here."""
        observed_state = state or {}
        assessment = self._stuck_classifier.classify(observed_state, self._progress.snapshot())
        directive = self._stuck.begin(correlation_id, now, stuck_kind=assessment.kind.value,
                                      position=self._player_route_position(observed_state))
        self._stuck_observation_anchor = self._recovery_observation(observed_state, now)
        return directive

    @property
    def stuck_recovery_active(self) -> bool:
        return self._stuck.active

    def next_stuck_recovery(self, correlation_id: str, now: float, state: dict | None = None) -> RecoveryDirective:
        """Choose the next bounded recovery intent from existing evidence."""
        pending = self.__dict__.pop("_pending_recovery_directive", None)
        if pending is not None and self._stuck.active and self._stuck.state.value == pending.action:
            # Live 2026-10-04 09:09: BACKWARD did not move, the ladder chose
            # JUMP_FORWARD in report_recovery_result, but the planner's next
            # query only saw "awaiting step result" (no action); SEEK and a
            # fresh MOVE into the same rock ran instead.  Hand it out once.
            return pending
        if not self._stuck.active:
            return self.begin_stuck_recovery(correlation_id, now, state)
        if self._stuck.state is StuckResolutionState.STOP_AND_OBSERVE and state is not None:
            phase = self._fresh_stopped_recovery_phase(state, now)
            if phase is not ProgressPhase.UNAVAILABLE:
                directive = self._stuck.observe_progress(phase, now)
                if directive.terminal:
                    self._stuck_observation_anchor = None
                return directive
        return self.observe_stuck_progress(now)

    def observe_external_hard_stuck(self, correlation_id: str, now: float) -> RecoveryDirective:
        """Accept a separately verified stationary watchdog observation.

        The caller has already established the long stationary window. We
        still require the resolver's STOP_AND_OBSERVE phase before it may
        select an input-bearing recovery step.
        """
        if not self._stuck.active:
            return self._stuck.begin(correlation_id, now)
        return self._stuck.observe_progress(ProgressPhase.HARD_STUCK, now)

    def observe_stuck_progress(self, now: float) -> RecoveryDirective:
        latest = self._progress.snapshot().get("latest") or {}
        raw_phase = latest.get("phase") if isinstance(latest, dict) else None
        phase = ProgressPhase(raw_phase) if raw_phase else ProgressPhase.UNAVAILABLE
        directive = self._stuck.observe_progress(phase, now)
        if directive.terminal:
            self._stuck_observation_anchor = None
        return directive

    def report_recovery_result(self, *, success: bool, now: float) -> RecoveryDirective:
        directive = self._stuck.report_step_result(success=success, now=now)
        if directive.terminal:
            self._stuck_observation_anchor = None
            self.__dict__.pop("_pending_recovery_directive", None)
        elif directive.action:
            self._pending_recovery_directive = directive
        return directive

    @staticmethod
    def _recovery_observation(state: dict, now: float) -> dict[str, Any]:
        position = state.get("player_world_position") or state.get("position") or {}
        movement = state.get("movement") or {}
        return {
            "token": state.get("frame_id") or state.get("observation_id"),
            "at": float(state.get("monotonic_time", now) or now),
            "x": number(position.get("x")),
            "y": number(position.get("y")),
            "moving": bool(movement.get("moving")),
            "speed": number(movement.get("speed")),
            "world_space": bool(state.get("player_world_position")),
        }

    def _fresh_stopped_recovery_phase(self, state: dict, now: float) -> ProgressPhase:
        """Classify the independent observation after STOP_AND_OBSERVE.

        This is deliberately narrower than ordinary stuck detection.  A hard
        stuck has already been supported by the ProgressMonitor; this gate
        merely proves that a later telemetry frame still shows no movement.
        It cannot start recovery on its own and it never issues input.
        """
        anchor = self._stuck_observation_anchor
        current = self._recovery_observation(state, now)
        if anchor is None:
            self._stuck_observation_anchor = current
            return ProgressPhase.UNAVAILABLE
        fresh_token = current["token"] is not None and current["token"] != anchor["token"]
        fresh_time = current["at"] > anchor["at"] + 1e-6
        if not (fresh_token or fresh_time):
            return ProgressPhase.UNAVAILABLE
        ax, ay, cx, cy = anchor["x"], anchor["y"], current["x"], current["y"]
        if None not in (ax, ay, cx, cy):
            displacement = math.hypot(float(cx)-float(ax), float(cy)-float(ay))
            tolerance = .25 if (anchor["world_space"] or current["world_space"]) else .0005
            if displacement > tolerance:
                return ProgressPhase.RECOVERED
        stopped = not current["moving"] and (
            current["speed"] is None or float(current["speed"]) <= .05)
        return ProgressPhase.HARD_STUCK if stopped else ProgressPhase.UNAVAILABLE

    OBSTACLE_AHEAD_YARDS = 2.0

    def mark_current_route_danger(self, state: dict, now: float,
                                  *, correlation_id: str | None = None,
                                  ttl: float = 90., cost: float = 12.,
                                  kind: str = "NAVIGATION_FAILURE") -> bool:
        """Persist one expiring route-failure cost at the observed player pose."""
        request = self._active_request
        if request is not None:
            world_space = request.destination.get("coordinate_space") == "WORLD_YARDS"
        else:
            # The failed MOVE may already have released its request; the
            # observed world pose still locates the obstacle.
            world_space = bool(state.get("player_world_position"))
            if not world_space and correlation_id is None:
                return False
        position = (state.get("player_world_position") if world_space
                    else state.get("position")) or {}
        x, y = number(position.get("x")), number(position.get("y"))
        if x is None or y is None:
            return False
        radius = 3.5 if world_space else .008
        orientation = number(state.get("orientation"))
        if world_space and orientation is not None:
            # The obstacle is in front of the character, not under it
            # (facing 0 = +x, counter-clockwise, as in the movement controller).
            x += math.cos(orientation) * self.OBSTACLE_AHEAD_YARDS
            y += math.sin(orientation) * self.OBSTACLE_AHEAD_YARDS
            radius = 3.0
        key = correlation_id or request.correlation_id
        self._danger.add(
            danger_id=f"navigation-failure:{key}", kind=kind,
            x=x, y=y, radius=radius, cost=cost, confidence=.9,
            now=now, ttl=ttl, source="SUPPORTED_STUCK",
        )
        return True

    def new_local_recovery_waypoint(self, state: dict, observation_id: str,
                                    now: float) -> dict | None:
        """Return one validated corridor/local-plan waypoint, never invent one.

        The caller still launches a normal MOVE through the sole movement
        authority and verifies its result before advancing the stuck ladder.
        """
        request = self._active_request
        if request is None:
            return None
        plan = self.local_plan(state, now=now, observation_id=observation_id)
        point = plan.local_waypoint
        if not isinstance(point, dict) or number(point.get("x")) is None or number(point.get("y")) is None:
            return None
        destination = dict(request.destination)
        destination.update({"x": float(point["x"]), "y": float(point["y"]),
                            "_stuck_recovery_waypoint": True,
                            "stuck_correlation": self._stuck.correlation_id})
        return destination

    def rebuild_current_corridor(self, state: dict, observation_id: str,
                                 now: float) -> bool:
        """Replan the active typed request through accumulated danger memory."""
        if self._active_request is None:
            return False
        previous = self._active_route.route_id if self._active_route else None
        self._active_route = self._global_planner.plan(
            self._active_request, state, now, danger_map=self._danger)
        self._route_danger_revision = self._danger.revision
        self._route_waypoint_index = 1 if len(self._active_route.anchors) > 1 else 0
        self._active_corridor = self._corridor_builder.build(self._active_route)
        self._latest_local_plan = self._local_planner.plan(
            state, self._active_corridor, destination=self._active_request.destination)
        self.start(self._current_route_destination(), state, observation_id, now)
        return self._active_route.route_id != previous

    def permits(self, world, destination: dict, now: float) -> bool:
        self._danger.observe_hostiles(world.state, now)
        if not self._danger.permits(destination["x"], destination["y"], now,
                                    avoid_combat=bool(destination.get("avoid_combat")),
                                    allow_combat=bool(destination.get("allow_combat")),
                                    exempt_entity_id=str(destination.get("target_guid") or "") or None):
            return False
        return self._routes.permits(world, destination, now)

    def retry_at(self, world, destination: dict, now: float) -> float | None:
        return self._routes.retry_at(world, destination, now)

    def report_entity_failure(self, entity_id: str | None, reason: str, now: float) -> None:
        if entity_id:
            self._reachability.report_failure(str(entity_id), reason, now)

    def report_entity_success(self, entity_id: str | None, now: float) -> None:
        if entity_id:
            self._reachability.report_success(str(entity_id), now)

    def begin_search_region(self, region_id: str, region: dict) -> None:
        self._search_coverage.begin(region_id, region)

    def observe_search_region(self, region_id: str, state: dict, now: float, *, target_detected: bool) -> None:
        region = (self._search_coverage.snapshot().get(str(region_id), {}).get("region") or {})
        position = ((state.get("player_world_position") or {})
                    if region.get("coordinate_space") == "WORLD_YARDS"
                    else (state.get("position") or {}))
        self._search_coverage.observe(region_id, player_x=number(position.get("x")),
                                      player_y=number(position.get("y")),
                                      target_detected=target_detected, now=now)

    def mark_search_cell_visited(self, region_id: str, cell_id: str, now: float) -> None:
        self._search_coverage.mark_visited(region_id, cell_id, now)

    def search_region_completed(self, region_id: str) -> bool | None:
        return self._search_coverage.completed(region_id)

    def walkable_point(self, instance_id: int, point: dict, *,
                       z_hint: float | None = None) -> dict | None:
        """Project world X/Y onto the configured mmap surface (None = off-mesh).

        Without a configured navmesh nothing is walkable: exploration must not
        invent destinations the route contract would reject anyway.
        """
        projector = getattr(self._navmesh, "project_position", None)
        if not callable(projector):
            return None
        try:
            projected = projector(int(instance_id), dict(point), z_hint=z_hint)
        except Exception:  # noqa: BLE001 -- a bad tile must not stop planning
            return None
        # project_position falls back to the *nearest* polygon; only a point
        # actually contained by a walkable polygon is an exploration target.
        diagnostics = getattr(self._navmesh, "last_surface_projection", None) or {}
        if projected is None or int(diagnostics.get("contained_candidates") or 0) <= 0:
            return None
        return projected

    def next_search_waypoint(self, region_id: str, state: dict) -> dict | None:
        region = (self._search_coverage.snapshot().get(str(region_id), {}).get("region") or {})
        position = ((state.get("player_world_position") or {})
                    if region.get("coordinate_space") == "WORLD_YARDS"
                    else (state.get("position") or {}))
        return self._search_coverage.next_waypoint(region_id, player_x=number(position.get("x")),
                                                   player_y=number(position.get("y")))

    def waypoint(self, world, destination: dict) -> dict:
        return self._routes.waypoint(world, destination)

    def observe_verified_move(self, before: dict, after: dict, destination: dict | None = None) -> None:
        self._routes.observe_verified_move(before, after, destination)

    def observe_failed_move(self, before: dict, after: dict, destination: dict,
                            observation_id: str, now: float):
        return self._routes.observe_failed_move(before, after, destination, observation_id, now)

    def observe_topology(self, state: dict, observation_id: str, now: float) -> list[dict]:
        return self._routes.observe_topology(state, observation_id, now)

    def local_combat_reposition(self, state: dict, request: dict) -> tuple[Command, ...]:
        """Produce one bounded visual local-navigation correction.

        This is intentionally not a second movement controller and does not
        create a route/lease on its own.  It is invoked only by the canonical
        CombatSkill's active attempt after target identity and screen-space
        localization were verified.  The caller still decides when to execute
        the returned normal movement command.
        """
        target = state.get("target") or {}
        expected = str(request.get("expected_guid") or "")
        if not expected or str(target.get("guid") or "") != expected:
            return ()
        x = number(request.get("target_screen_x"))
        y = number(request.get("target_screen_y"))
        if x is None or y is None or not .02 < x < .98 or not .02 < y < .98:
            return ()
        reason = str(request.get("reason") or "")
        # Keep the target near the screen centre.  No cardinal or world-space
        # assumption is made; the correction direction is derived only from
        # the currently verified target screen position.
        if reason == "FACING_WRONG_WAY":
            # The shared primitive owns dead-zone/hysteresis and binding
            # validation.  A centred target with a client facing error is
            # still a bounded deterministic turn, never a blind advance.
            faced = self.face_entity(state, expected)
            if faced.commands:
                return faced.commands
            # A centred visual anchor plus a contradictory client-facing
            # error contains no turn direction. Never invent a left/right
            # spin; the caller must request fresh perception instead.
            return ()
        if reason in {"COMBAT_TRACK_FOLLOW", "COMBAT_TRACK_REACQUIRE",
                      "COMBAT_TRACK_APPROACH"}:
            if reason == "COMBAT_TRACK_REACQUIRE":
                # Direction is the last supported visual bearing.  The combat
                # policy bounds the duration and number of these probes.
                turn = "TURNRIGHT" if x >= .5 else "TURNLEFT"
                return (Command("BIND", turn, .075),)
            error = x-.5
            if reason == "COMBAT_TRACK_APPROACH":
                turn = "TURNRIGHT" if error > .075 else "TURNLEFT" if error < -.075 else None
                return (Command("BIND", "MOVEFORWARD", .12,
                                simultaneous=((turn,) if turn else ())),)
            if abs(error) <= .075:
                return ()
            turn = "TURNRIGHT" if error > 0 else "TURNLEFT"
            # The executor accepts movement leases of .04-.35 s only; .035
            # raised "Érvénytelen movement lease" and failed COMBAT with an
            # executor_failure 11 times in the 2026-10-02 run.
            return (Command("BIND", turn, min(.09, max(.04, abs(error)*.20))),)
        turn = "TURNRIGHT" if x > .54 else "TURNLEFT" if x < .46 else None
        if reason == "OUT_OF_RANGE":
            return (Command("BIND", "MOVEFORWARD", .16,
                            simultaneous=((turn,) if turn else ())),)
        if reason == "LINE_OF_SIGHT":
            directive = self._los_recovery.plan(state, request)
            self._latest_los_recovery = {
                "phase": directive.phase.value,
                "action": directive.action,
                "duration": directive.duration,
                "chosen_side": directive.chosen_side,
                "geometry_source": directive.geometry_source,
                "evidence": list(directive.evidence),
                "attempt": int(request.get("attempt") or 0),
            }
            if directive.action is None:
                return ()
            return (Command("BIND", directive.action, directive.duration),)
        return ()

    def reposition_for_los(self, state: dict, entity_ref: str | None,
                           observation_id: str, now: float, *,
                           desired_range: float = 4.5) -> dict | None:
        """Start the final, geometry-backed LOS recovery through this service.

        No screen pixel is converted into a world position.  A same-instance,
        fresh selected-target coordinate is required.  ``GlobalPlanner`` may
        then use Trinity mmap geometry, while the existing movement controller
        remains the sole command owner.
        """
        expected = world_entity_id(entity_ref)
        target = state.get("target") or {}
        player = state.get("player_world_position") or {}
        position = target.get("world_position") or {}
        if (not expected or str(target.get("guid") or "") != expected
                or target.get("dead", target.get("is_dead"))
                or target.get("attackable", target.get("is_attackable")) is not True):
            return None
        sampled = number(target.get("sample_time", state.get("target_sample_time")))
        state_at = number(state.get("monotonic_time"))
        state_at = now if state_at is None else state_at
        if sampled is not None and not 0. <= state_at-sampled <= 1.5:
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
            "target_guid": expected, "purpose": "LOS_REPOSITION",
            "coordinate_space": "WORLD_YARDS", "x": tx, "y": ty,
            "z": number(position.get("z")) or 0.,
            "instance_id": target_instance, "world_map_id": target_instance,
            "stop_distance": float(desired_range), "allow_combat": True,
        }
        request = NavigationRequest(
            request_id=f"los:{observation_id}", correlation_id=observation_id,
            mode="REPOSITION_FOR_LOS", destination=destination,
            target_entity_id=expected,
            arrival=ArrivalEnvelope(desired_range=float(desired_range)),
            allow_combat=True, priority=90, timeout=2.5)
        self.start_request(request, state, now)
        return destination

    def record_los_exhaustion(self, entity_ref: str | None, state: dict,
                              now: float) -> bool:
        """Apply the finite M2.8 reachability/danger consequences once."""
        expected = world_entity_id(entity_ref)
        player = state.get("player_world_position") or {}
        x, y = number(player.get("x")), number(player.get("y"))
        if x is None or y is None:
            return False
        self._danger.add(
            danger_id=f"los-obstacle:{expected or 'unknown'}", kind="LOS_OBSTACLE",
            x=x, y=y, radius=3.5, cost=10., confidence=.8, now=now,
            ttl=30., source="LOS_RECOVERY_EXHAUSTED", entity_id=expected)
        return True

    def face_entity(self, state: dict, entity_ref: str | None) -> FaceResult:
        target = state.get("target") or {}
        if not entity_ref or str(target.get("guid") or "") != str(entity_ref):
            self._face.reset()
            return self._face.face_screen_x(None)
        screen = target.get("screen_position") or {}
        return self._face.face_screen_x(screen.get("x"))

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
