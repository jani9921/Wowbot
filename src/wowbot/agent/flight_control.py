"""Closed-loop Steady Flight along a ``FlightPlan`` (owned by MovementController).

User 2026-10-25: "first plain riding in the air".  Steady Flight hovers when
no key is held, climbs while Jump is held and descends while Sit/Move Down is
held; forward flight keeps its height at pitch 0.  The loop therefore needs
only the keys the ground controller already uses plus JUMP and SITORSTAND:

* on the ground (mounted): take off with Jump; no takeoff within the bound
  fails the MOVE (``flight_takeoff_failed``) instead of walking blindly,
* in the air: turn toward the landing point, run forward, and hold Jump /
  Sit while the server-measured height is off the plan's target height (the
  highest ground of the stretch ahead plus clearance); a height far below the
  target is climbed in place first, so the ridge is never flown into,
* above the landing point: descend until the client no longer reports
  flying (landed); only that is arrival.

Height comes from the player's own movement packets (Ymir,
``z_source=PACKET_CLIENT_MOVEMENT``); the addon cannot read Z.  Without a
fresh measured height the character hovers and taps Jump briefly -- the
start/stop ascend packets carry a fresh position.  No progress in three
dimensions for ``STALL_SECONDS`` fails closed (``flight_no_progress``).
"""
from __future__ import annotations

import math

from .models import Command, number
from wowbot.navigation.flight_route import FlightPlan

CLIMB_BAND = 1.5             # below the target by more: hold Jump while flying on
DESCEND_BAND = 2.5           # above the target by more: hold Sit while flying on
CLIMB_IN_PLACE = 15.         # this far below: climb first, then fly
TURN_IN_PLACE = .6
SOFT_TURN = .15
FORWARD_LEASE = .32
VERTICAL_LEASE = .35
LAND_RADIUS = 3.
Z_FRESH_SECONDS = 1.5
TAKEOFF_SECONDS = 2.5
TAKEOFF_ATTEMPTS = 3
STALL_SECONDS = 6.
STALL_YARDS = 1.


class FlightControl:
    def __init__(self, plan: FlightPlan, bindings=None) -> None:
        self.plan = plan
        self.bindings = bindings
        self.z: float | None = None
        self.z_at: float | None = None
        self.takeoff_started: float | None = None
        self.takeoff_attempts = 0
        self.samples: list[tuple[float, float, float, float]] = []
        self.phase = "TAKEOFF"
        self.last_reason = ""
        self.waypoint_index = 0

    def route_corner(self, state, now):
        """Sequential air bends; a final-XY shortcut cannot skip the detour."""
        position = state.get('player_world_position') or {}
        x, y, z = number(position.get('x')), number(position.get('y')), self.height(now)
        if x is None or y is None:
            return None
        while self.waypoint_index < len(self.plan.waypoints):
            point = self.plan.waypoints[self.waypoint_index]
            if (z is None or abs(z-point['z']) > 6.
                    or math.hypot(point['x']-x, point['y']-y) > 3.):
                return point
            self.waypoint_index += 1
        return None

    # -- measurements ------------------------------------------------------
    def observe_height(self, state: dict, now: float) -> None:
        position = state.get("player_world_position") or {}
        z = number(position.get("z"))
        if (z is not None and position.get("z_observed") is True
                and position.get("z_source") in {"PACKET_CLIENT_MOVEMENT", "PACKET_MOVEMENT"}):
            at = number(position.get("sample_time"))
            if self.z_at is None or at is None or at >= self.z_at:
                self.z, self.z_at = z, (at if at is not None else now)

    def height(self, now: float) -> float | None:
        if self.z is None or self.z_at is None or now-self.z_at > Z_FRESH_SECONDS:
            return None
        return self.z

    @staticmethod
    def flying(state: dict, now: float | None = None) -> bool:
        from wowbot.navigation.flight_path import airborne
        clock = now if now is not None else number(state.get('monotonic_time'))
        return airborne(state, clock if clock is not None else 0.)

    def ground_contact(self, state: dict, now: float) -> bool:
        if self.flying(state, now):
            return False
        if state.get('is_ghost') is not True:
            return True
        # The addon can report flying=False while the ghost's own movement
        # packet still puts it above the corpse. XY alone is not touchdown.
        z = self.height(now)
        return z is not None and abs(z-float(self.plan.landing['z'])) <= LAND_RADIUS

    def _bound(self, binding: str) -> bool:
        return not self.bindings or self.bindings.contains(binding)

    # -- assessment (called from MovementController._observe_once) ---------
    def assess(self, state: dict, distance: float, tolerance: float, now: float) -> tuple[str, str]:
        """("ARRIVED"|"FAILED"|"MOVING", reason)."""
        self.observe_height(state, now)
        flying = self.flying(state, now)
        corner = self.route_corner(state, now)
        if (self.plan.truncated and flying and corner is None
                and distance <= max(tolerance, LAND_RADIUS) and self.height(now) is not None
                and abs(self.height(now)-float(self.plan.landing['z'])) <= 6.):
            self.phase = 'CRUISE'
            return 'ARRIVED', 'flight_segment_complete'
        measured_z = self.height(now)
        on_landing_layer = (measured_z is None or
                            abs(measured_z-float(self.plan.landing['z'])) <= max(tolerance, LAND_RADIUS))
        landed_here = (corner is None and distance <= max(tolerance, LAND_RADIUS)
                       and on_landing_layer and self.ground_contact(state, now))
        if landed_here and (self.phase in {"LANDING", "CRUISE"} or self.takeoff_started is None):
            self.phase = "LANDED"
            return "ARRIVED", "flight_landed"
        if not flying:
            if state.get("is_mounted") is not True:
                return "FAILED", "flight_not_mounted"
            if self.takeoff_started is not None and now-self.takeoff_started > TAKEOFF_SECONDS:
                if self.takeoff_attempts >= TAKEOFF_ATTEMPTS:
                    return "FAILED", "flight_takeoff_failed"
                self.takeoff_started = None              # try again
            self.phase = "TAKEOFF"
            return "MOVING", "flight_takeoff"
        position = state.get("player_world_position") or {}
        x, y = number(position.get("x")), number(position.get("y"))
        z = self.height(now)
        if x is not None and y is not None and z is not None:
            self.samples.append((now, x, y, z))
            self.samples = [row for row in self.samples if now-row[0] <= STALL_SECONDS + 1.]
            oldest = self.samples[0]
            if (now-oldest[0] >= STALL_SECONDS
                    and math.dist(oldest[1:], (x, y, z)) < STALL_YARDS):
                return "FAILED", "flight_no_progress"
        self.phase = "LANDING" if corner is None and distance <= max(tolerance, LAND_RADIUS) else "CRUISE"
        return "MOVING", f"flight_{self.phase.lower()}"

    # -- commands (called from MovementController.command) -----------------
    def commands(self, state: dict, distance: float, heading_error: float,
                 tolerance: float, now: float) -> tuple[Command, ...]:
        self.observe_height(state, now)
        corner = self.route_corner(state, now)
        if corner is not None:
            position = state.get('player_world_position') or {}
            x, y = number(position.get('x')), number(position.get('y'))
            facing = number(state.get('orientation'))
            if None in (x, y, facing):
                return ()
            distance = math.hypot(corner['x']-x, corner['y']-y)
            heading_error = (math.atan2(corner['y']-y, corner['x']-x)-facing+math.pi) % math.tau-math.pi
        for binding in ("JUMP", "SITORSTAND", "MOVEFORWARD", "TURNLEFT", "TURNRIGHT"):
            if not self._bound(binding):
                raise ValueError(f"Hiányzó repülési binding: {binding}")
        if not self.flying(state, now):
            if distance <= max(tolerance, LAND_RADIUS) and self.phase in {"LANDING", "CRUISE", "LANDED"}:
                return ()
            if self.takeoff_started is None:
                self.takeoff_started, self.takeoff_attempts = now, self.takeoff_attempts + 1
                # One jump to leave the ground, then holding Jump starts flight.
                return (Command("BIND", "JUMP", .15),)
            return (Command("BIND", "JUMP", .35),)            # the lease maximum
        turn = "TURNLEFT" if heading_error > 0 else "TURNRIGHT"
        if corner is None and distance <= max(tolerance, LAND_RADIUS):
            if self.plan.truncated:
                z = self.height(now)
                if z is None:
                    return (Command('BIND', 'JUMP', .08),)
                gap = float(self.plan.landing['z'])-z
                return ((Command('BIND', 'JUMP' if gap > 0 else 'SITORSTAND', VERTICAL_LEASE),)
                        if abs(gap) > 3. else ())
            # Right above the landing point: straight down.
            z = self.height(now)
            if z is None or z < float(self.plan.landing['z'])-LAND_RADIUS:
                return (Command('BIND', 'JUMP', .08 if z is None else VERTICAL_LEASE),)
            return (Command("BIND", "SITORSTAND", VERTICAL_LEASE),)
        z = self.height(now)
        if z is None:
            # Hover (Steady Flight holds its height) and make the client send
            # a fresh position: a short ascend starts/stops a movement packet.
            return (Command("BIND", "JUMP", .08),)
        if corner is not None and distance <= 3. and abs(corner['z']-z) > 6.:
            return (Command('BIND', 'JUMP' if corner['z'] > z else 'SITORSTAND', VERTICAL_LEASE),)
        position = state.get("player_world_position") or {}
        along = self.plan.along(number(position.get("x")) or 0., number(position.get("y")) or 0.)
        error_z = self.plan.target_z(along) - z
        vertical = ("JUMP",) if error_z > CLIMB_BAND else ("SITORSTAND",) if error_z < -DESCEND_BAND else ()
        if error_z > CLIMB_IN_PLACE:
            return (Command("BIND", "JUMP", VERTICAL_LEASE,
                            simultaneous=(turn,) if abs(heading_error) > SOFT_TURN else ()),)
        if abs(heading_error) > TURN_IN_PLACE:
            from .hover_control import turn_lease
            duration = max(.04, min(.12, abs(heading_error) / 3.14 * .55))
            return (turn_lease(turn, duration, vertical),)
        steer = (turn,) if abs(heading_error) > SOFT_TURN else ()
        return (Command("BIND", "MOVEFORWARD", FORWARD_LEASE if distance > 12. else .12,
                        simultaneous=(*steer, *vertical)),)
