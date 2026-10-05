"""NavigationService combat positioning: range/LOS repositioning and facing.

Split out of service.py (2026-10-05); unchanged.
"""
from __future__ import annotations
from wowbot.agent.models import Command, number
from .facing import FaceResult
from .contracts import ArrivalEnvelope, NavigationRequest
from wowbot.runtime import world_entity_id


class NavigationCombatMixin:
    """Methods of NavigationService (service.py); moved verbatim."""

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
