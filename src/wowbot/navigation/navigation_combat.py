"""Combat local positioning: range/LOS repositioning and facing.

Split out of service.py (2026-10-05) as a mixin; since the REV4 split
(SRC_MELY_AUDIT 4.3) it is ``CombatLocalPositioningAdapter``, a component with
explicit ports instead of the service's private attributes:

* ``face`` -- the service's FaceController (the shared facing primitive),
* ``los_recovery`` -- the LOS recovery planner,
* ``danger`` -- the service's DangerMap,
* ``resolve_entity`` / ``start_entity`` -- the service's entity-goal request
  owner.  The adapter never starts a second controller or input lease.

It owns only the latest LOS recovery directive (the service snapshot shows it).
"""
from __future__ import annotations
from wowbot.agent.models import Command, number
from .facing import FaceResult
from wowbot.runtime import world_entity_id


class CombatLocalPositioningAdapter:
    """NavigationService's combat positioning; the method bodies are unchanged."""

    def __init__(self, face, los_recovery, danger, resolve_entity, start_entity) -> None:
        self._face = face
        self._los_recovery = los_recovery
        self._danger = danger
        self._resolve_entity_destination = resolve_entity
        self._start_entity_request = start_entity
        self.latest_los_recovery: dict | None = None

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
            self.latest_los_recovery = {
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
                           desired_range: float = 4.5, defer_plan: bool = False,
                           deadline: float | None = None) -> dict | None:
        """Start the final, geometry-backed LOS recovery through this service.

        No screen pixel is converted into a world position.  A same-instance,
        fresh selected-target coordinate is required.  ``GlobalPlanner`` may
        then use Trinity mmap geometry, while the existing movement controller
        remains the sole command owner.
        """
        expected = world_entity_id(entity_ref)
        target = state.get("target") or {}
        if (not expected or str(target.get("guid") or "") != expected
                or target.get("dead", target.get("is_dead"))
                or target.get("attackable", target.get("is_attackable")) is not True):
            return None
        destination = self._resolve_entity_destination(state, expected, now, stop_distance=desired_range)
        if deadline is not None:
            deadline = number(deadline)
            if deadline is None:
                return None
        if destination is None or deadline is not None and now >= deadline:
            return None
        destination.update(purpose='LOS_REPOSITION', entity_goal=True, allow_combat=True, require_navmesh=True)
        self._start_entity_request(destination, state, observation_id, now, defer_plan=defer_plan,
            deadline=min(deadline,now+2.5) if deadline is not None else now+2.5, mode='REPOSITION_FOR_LOS')
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
