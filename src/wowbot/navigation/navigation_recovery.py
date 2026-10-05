"""NavigationService stuck recovery: ladder steps, learned danger, local waypoints, corridor rebuild.

Split out of service.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import math
from typing import Any
from wowbot.agent.models import number
from .progress import ProgressPhase
from .stuck_resolver import RecoveryDirective, StuckResolutionState


class NavigationRecoveryMixin:
    """Methods of NavigationService (service.py); moved verbatim."""

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
