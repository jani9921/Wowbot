"""Closed-loop Skyriding actuator owned by ReachMovementController.

An explicit FlightPath supplies geometry and declarative checkpoint evidence.
This controller has no quest IDs, catalog queries or task-planning authority.

Skyriding is momentum flight.  The user's own runs (live 2026-10-25 10:00 and
14:09-14:10, decoded movement packets at ~7 Hz) showed:

* a level glide (pitch 0) holds the height while the speed bleeds ~1.5 yd/s²,
* diving gains speed (about 14·sin(-pitch) yd/s², capped near 65 yd/s) and a
  pull-up trades it for height,
* Surge Forward adds ~+16..30 forward, Skyward Ascent ~+43 up; both cost
  vigor (the action is then not usable),
* jumping twice from the ground (or walking off a ledge) starts the glide.

The agent's own course (live 17:26-17:30, quest 77345, 8 rings) circled
rings and overshot every heading by ~1.3 rad.  Measured there:

* Turn Left/Right rotate a steady 2.35 rad/s (795 packet pairs: p50 2.34,
  p90 2.37) and Pitch Up/Down ~1.4 rad/s (p50 1.22, p90 1.5);
* the feedback reached this loop up to 0.6 s late (the medium tick polled
  the packets; now the fast lane peeks them) and a held key keeps turning
  until the next sample.  The loop therefore predicts facing, pitch and
  position from the keys it has held since the sample (its lease ledger);
* a ring abeam inside the turn circle (radius v/2.35: 23 yd at 55 yd/s)
  cannot be reached by turning toward it -- the drake orbits it.  The loop
  flies straight until the ring is outside the circle, then turns in;
* the server credits a ring (RingHitDistance 10 yd) about one medium tick
  later; meanwhile the loop steers to the next ring provisionally and turns
  back to the old one if no credit arrives within PASS_GRACE;
* Jump while gliding is Skyward Ascent (3 of 3 airborne Jump casts); Surge
  Forward is on the Skyriding bar (spell 372608) and is tapped only after
  the bar shows it usable there.

A ring is "passed" only when the server credits it.  After the last point it
glides down and the MOVE ends once the client no longer flies.
"""
from __future__ import annotations

import math

from .models import Command, number
from wowbot.navigation.flight_path import FlightPath

TURN_RATE = 2.35                # rad/s while a turn key is held (live 17:26-17:30)
PITCH_RATE = 1.4                # rad/s while a pitch key is held
PITCH_DEADBAND = .05
YAW_DEADBAND = .06
MIN_LEASE, MAX_LEASE = .04, .15             # the executor's lease bounds are .04-.35 s
PITCH_LIMITS = (-1.25, .85)
GRAVITY = 14.                   # yd/s² along the flight path (from the dive / pull-up samples)
BLEND_YARDS = 25.               # start turning toward the ring after the current one
CLIMB_MARGIN = 6.               # yd of height the speed must carry with margin
LAND_PITCH = -.25
FEEDBACK_FRESH = 1.2            # s: the packet flight sample must be this fresh
RING_PASS_YARDS = 10.           # the course scene's RingHitDistance
PASS_GRACE = 2.                 # s to wait for the server credit of a ring we flew through
TURN_CIRCLE_MARGIN = .7         # of RING_PASS_YARDS: a ring this deep inside the circle is unreachable
SURGE_SPELL_ID = 372608
SURGE_BELOW = 42.               # yd/s: Surge Forward when slower ...
SURGE_FARTHER = 70.             # ... the next point is at least this far ...
SURGE_ALIGNED = .3              # ... and yaw and pitch are within this of the aim
STALL_SPEED = 12.               # yd/s: below this the drake sinks (live: up -14 at 8 yd/s)
TARGET_CLIMB_YARDS = 10.        # a final point this far above still gets boosts
ROOT_WAIT_SECONDS = 15.         # a start-line root older than this is not waited for
GROUND_FINISH_YARDS = 100.
OFF_MESH_RELAUNCHES = 2         # retries to touch down on a landing with no navmesh      # a travel glide that touched down this close to its landing walks on
CRUISE_SPEED = 30.              # yd/s: slower and DIVE_MARGIN above the point -> dive
DIVE_MARGIN = 15.
DIVE_PITCH = -.35
ABILITY_INTERVAL = 1.5          # s between two boosts (the bar's usable flag lags ~1 s)


def _wrap(angle: float) -> float:
    return (angle + math.pi) % math.tau - math.pi


class SkyridingControl:
    def __init__(self, path: FlightPath, bindings=None) -> None:
        self.path = path
        self.waypoints = [tuple(p[k] for k in ("x", "y", "z")) for p in (*path.waypoints, path.landing)]
        self.bindings = bindings
        self.rings = len(path.waypoints)
        self.index = 0
        self.phase = "TAKEOFF"
        self.takeoff_presses = 0
        self.last_takeoff_at: float | None = None
        self.finished_at: float | None = None
        self.last_boost_at: float | None = None
        self.last_reason = ""
        self.was_airborne = False
        self.off_mesh_relaunches = 0
        # (start, end, yaw sign, pitch sign) of the steering leases sent.
        self._ledger: list[tuple[float, float, int, int]] = []
        self._previous: tuple[float, float, float] | None = None
        self._closest: dict[int, float] = {}
        self._provisional: tuple[int, float] | None = None

    # -- inputs ------------------------------------------------------------
    def _progress(self, state: dict, now: float) -> int:
        passed = self.path.progress(state, min(self.index, self.rings), now=now)
        if passed == self.rings and self.path.arrival_condition is not None and self.path.arrival_confirmed(state):
            passed += 1
        return max(self.index, passed)

    @staticmethod
    def _flight(state: dict, now: float) -> dict | None:
        sample = state.get("packet_flight") or {}
        at = number(sample.get("sample_time"))
        if at is None or not 0 <= now-at <= FEEDBACK_FRESH:
            return None
        return sample

    @staticmethod
    def _airborne(state: dict, sample: dict | None) -> bool:
        return bool((sample or {}).get("adv_flying") or (state.get("movement") or {}).get("flying"))

    def _bound(self, binding: str) -> bool:
        return not self.bindings or self.bindings.contains(binding)

    # -- assessment --------------------------------------------------------
    def assess(self, state: dict, now: float) -> tuple[str, str]:
        self.index = self._progress(state, now)
        sample = self._flight(state, now)
        airborne = self._airborne(state, sample)
        self.was_airborne = self.was_airborne or airborne
        if self.index >= len(self.waypoints) and self.path.end_in_air:
            return "ARRIVED", "skyriding_air_leg_complete"
        if self.index >= len(self.waypoints):
            self.phase = "LANDING"
            if not airborne:
                return "ARRIVED", "skyriding_course_complete_landed"
            self.finished_at = self.finished_at or now
            if now-self.finished_at > 25.:
                return "FAILED", "skyriding_landing_timeout"
            return "MOVING", "skyriding_course_complete_landing"
        off_mesh = self._off_mesh_touchdown(state, airborne)
        if off_mesh is not None:
            return off_mesh
        if self.index >= self.rings and not self._travel_takeoff(airborne):
            self.phase = "LANDING"
            return "MOVING", "skyriding_target_landing" if airborne else "skyriding_ground_approach_required"
        if state.get("is_mounted") is not True and not airborne:
            return "FAILED", "skyriding_not_mounted"
        if not airborne and self._touched_down_near_landing(state):
            # A travel glide that landed short of its last air point but near
            # the landing walks the rest instead of taking off again.
            self.index = self.rings
            self.phase = "LANDING"
            return "MOVING", "skyriding_ground_approach_required"
        if not airborne and self._rooted(state, now):
            # A race start line roots the rider until the start (live 20:47:09-
            # 20:47:17); jumping then would only use up the takeoff attempts.
            self.phase = "TAKEOFF"
            return "MOVING", "skyriding_start_line_rooted"
        if not airborne:
            self.phase = "TAKEOFF"
            if self.takeoff_presses >= 6:
                return "FAILED", "skyriding_takeoff_failed"
            return "MOVING", "skyriding_takeoff"
        self.phase = "COURSE"
        if sample is None or number(sample.get("pitch")) is None:
            return "MOVING", "skyriding_waiting_for_flight_feedback"
        return "MOVING", f"skyriding_ring_{self.index + 1}"

    @staticmethod
    def _rooted(state: dict, now: float) -> bool:
        from wowbot.navigation.flight_path import rooted
        return rooted(state, now, ROOT_WAIT_SECONDS)

    def _travel_takeoff(self, airborne: bool) -> bool:
        """A travel flight that has not flown yet takes off even when only its
        landing is left (a short hop, or a relaunch after the landing proved
        unreachable on foot).  A course never relaunches after its rings."""
        return (not airborne and not self.was_airborne and self.path.arrival_condition is None
                and not any(self.path.checkpoint_conditions))

    def _off_mesh_touchdown(self, state: dict, airborne: bool) -> tuple[str, str] | None:
        """A landing with no navmesh (live 2026-10-25: the Skytop dome top):
        touching down within its radius arrives; elsewhere near it the drake
        takes off and lands again (bounded)."""
        if airborne or not self.was_airborne or self.path.landing_on_navmesh or self.path.end_in_air:
            return None
        position = state.get("player_world_position") or {}
        x, y = number(position.get("x")), number(position.get("y"))
        if x is None or y is None:
            return None
        landing = self.waypoints[-1]
        distance = math.hypot(x-landing[0], y-landing[1])
        if self.index < self.rings and distance > GROUND_FINISH_YARDS:
            return None                       # an early touchdown far away: the normal takeoff retry
        if distance <= (self.path.landing_radius or self.path.radius):
            self.index, self.phase = self.rings, "LANDED"
            return "ARRIVED", "skyriding_landed_off_navmesh"
        if self.off_mesh_relaunches >= OFF_MESH_RELAUNCHES:
            return "FAILED", "skyriding_off_mesh_landing_missed"
        self.off_mesh_relaunches += 1
        self.index, self.was_airborne = self.rings, False     # take off for the landing again
        self.phase = "TAKEOFF"
        return "MOVING", "skyriding_off_mesh_relaunch"

    def _touched_down_near_landing(self, state: dict) -> bool:
        if (not self.was_airborne or self.path.end_in_air or not self.path.landing_on_navmesh
                or not all(self._geometric(index) for index in range(self.index, self.rings))):
            return False
        position = state.get("player_world_position") or {}
        x, y = number(position.get("x")), number(position.get("y"))
        landing = self.waypoints[-1]
        return x is not None and y is not None and math.hypot(x-landing[0], y-landing[1]) <= GROUND_FINISH_YARDS

    # -- state estimate ----------------------------------------------------
    def _send(self, now: float, duration: float, yaw: int, pitch: int) -> None:
        """Record a lease: the scheduler replaces the previous one at once."""
        self._ledger = [(start, min(end, now), y, p) for start, end, y, p in self._ledger
                        if end > now-2.]
        if yaw or pitch:
            self._ledger.append((now, now+duration, yaw, pitch))

    def _predict(self, point, sample: dict, facing: float, at: float | None, now: float):
        """(position, facing, pitch) now, from the packet sample, its velocity
        and the steering keys held since it was taken.

        A straight glide sends only a heartbeat every ~0.5 s (live 14:09:52-
        14:09:54: 0.5 s apart at 43 yd/s = 22 yd); key changes send more."""
        pitch = number(sample.get("pitch")) or 0.
        speed = number(sample.get("forward_velocity"))
        up = number(sample.get("up_velocity")) or 0.
        if at is None:
            return point, facing, pitch
        turned = pitched = 0.
        for start, end, yaw_sign, pitch_sign in self._ledger:
            overlap = max(0., min(end, now) - max(start, at))
            turned += yaw_sign * TURN_RATE * overlap
            pitched += pitch_sign * PITCH_RATE * overlap
        new_pitch = max(-1.5, min(1.5, pitch + pitched))
        if speed is None:
            return point, (facing + turned) % math.tau, new_pitch
        elapsed = max(0., min(1., now-at))
        mid_facing, mid_pitch = facing + turned/2., (pitch + new_pitch)/2.
        x, y, z = point
        return ((x + speed*math.cos(mid_pitch)*math.cos(mid_facing)*elapsed,
                 y + speed*math.cos(mid_pitch)*math.sin(mid_facing)*elapsed,
                 z + (speed*math.sin(mid_pitch) + up)*elapsed),
                (facing + turned) % math.tau, new_pitch)

    def _geometric(self, index: int) -> bool:
        """A point no server signal confirms: a travel waypoint, or the air
        end of a travel leg.  Geometry never overrides a required signal."""
        if index < self.rings:
            return self.path.checkpoint_conditions[index] is None
        return index == self.rings and self.path.end_in_air

    def _approach(self, index: int, position) -> float:
        """Closest approach to the point on the segment since the last estimate
        (at 55 yd/s two estimates are ~3-8 yd apart)."""
        point = self.waypoints[index]
        distance = math.dist(position, point)
        if self._previous is not None:
            ax, ay, az = self._previous
            bx, by, bz = position
            dx, dy, dz = bx-ax, by-ay, bz-az
            span = dx*dx + dy*dy + dz*dz
            t = 0. if span <= 1e-9 else max(0., min(1., ((point[0]-ax)*dx + (point[1]-ay)*dy + (point[2]-az)*dz) / span))
            distance = min(distance, math.dist((ax+dx*t, ay+dy*t, az+dz*t), point))
        closest = self._closest[index] = min(self._closest.get(index, math.inf), distance)
        return closest

    def _crossed(self, index: int, position) -> bool:
        """Past a travel waypoint: beyond the plane through it across the next
        leg, within a corridor beside it (a near miss is not flown again)."""
        point = self.waypoints[index]
        following = self.waypoints[index + 1] if index + 1 < len(self.waypoints) else None
        if following is None:
            return False
        lx, ly = following[0]-point[0], following[1]-point[1]
        length = math.hypot(lx, ly)
        if length < 1e-3:
            return False
        ahead = ((position[0]-point[0])*lx + (position[1]-point[1])*ly) / length
        aside = abs((position[0]-point[0])*ly - (position[1]-point[1])*lx) / length
        return ahead >= 0. and aside <= 3*self.path.radius

    def _steer_index(self, position, now: float) -> int:
        """The point to steer at: the next uncredited one, or the one after it
        while the server has not yet credited a ring we just flew through."""
        index = self.index
        while index < len(self.waypoints) and self._geometric(index):
            if not (self._approach(index, position) <= self.path.radius or self._crossed(index, position)):
                break
            index = self.index = index + 1
        if index >= self.rings:
            self._previous = position
            return index
        ring = self.waypoints[index]
        closest = self._approach(index, position)
        self._previous = position
        if self._geometric(index):
            return index
        provisional = self._provisional
        if provisional is not None and provisional[0] != index:
            provisional = self._provisional = None
        if provisional is not None:
            if now-provisional[1] <= PASS_GRACE:
                return index + 1
            # No credit: we missed it.  It is the target again.
            self._provisional = None
            self._closest.pop(index, None)
            return index
        if closest <= RING_PASS_YARDS and math.dist(position, ring) > closest + 3.:
            self._provisional = (index, now)
            return index + 1
        return index

    # -- guidance ----------------------------------------------------------
    def _aim(self, position, index: int) -> tuple[float, float, float]:
        """(desired yaw, desired pitch, distance) toward the point, blended
        toward the one after it once it is close."""
        px, py, pz = position
        tx, ty, tz = self.waypoints[min(index, len(self.waypoints)-1)]
        distance = math.dist((px, py, pz), (tx, ty, tz))
        if distance < BLEND_YARDS and index + 1 < len(self.waypoints):
            nx, ny, nz = self.waypoints[index + 1]
            weight = 1. - distance / BLEND_YARDS
            tx, ty, tz = (tx + (nx-tx)*weight*.5, ty + (ny-ty)*weight*.5, tz + (nz-tz)*weight*.5)
        dx, dy, dz = tx-px, ty-py, tz-pz
        yaw = math.atan2(dy, dx) % math.tau
        pitch = math.atan2(dz, max(1e-3, math.hypot(dx, dy)))
        return yaw, max(PITCH_LIMITS[0], min(PITCH_LIMITS[1], pitch)), distance

    @staticmethod
    def _inside_turn_circle(position, facing: float, pitch: float, speed: float | None,
                            target, yaw_error: float) -> bool:
        """The target lies so deep inside the circle a full turn toward it
        flies that the drake would orbit it instead of passing through."""
        if speed is None or abs(yaw_error) <= YAW_DEADBAND:
            return False
        radius = max(0., speed*math.cos(pitch)) / TURN_RATE
        side = 1. if yaw_error > 0 else -1.                     # +: turning left
        cx = position[0] - side*radius*math.sin(facing)
        cy = position[1] + side*radius*math.cos(facing)
        return math.hypot(target[0]-cx, target[1]-cy) < radius - RING_PASS_YARDS*TURN_CIRCLE_MARGIN

    def _surge_binding(self, state: dict) -> str | None:
        """Surge Forward's action button, only while the Skyriding bar shows it."""
        bar = state.get("skyriding_bar") or {}
        if bar.get("kind") != "SKYRIDING" or state.get("skyriding_controls") is False:
            return None
        for action in bar.get("actions") or ():
            binding = str(action.get("action") or "")
            if (action.get("id") == SURGE_SPELL_ID and action.get("is_usable") is True
                    and not action.get("lacks_resource") and not number(action.get("cooldown_remaining"))
                    and binding.startswith("ACTIONBUTTON") and self._bound(binding)):
                return binding
        return None

    def commands(self, state: dict, now: float) -> tuple[Command, ...]:
        for binding in ("PITCHUP", "PITCHDOWN", "TURNLEFT", "TURNRIGHT", "JUMP"):
            if not self._bound(binding):
                raise ValueError(f"Hiányzó Skyriding binding: {binding}")
        sample = self._flight(state, now)
        airborne = self._airborne(state, sample)
        if not airborne:
            if (self.index >= self.rings and not self._travel_takeoff(airborne)) or self._rooted(state, now):
                return ()
            # Jump, then jump again in the air: Skyward Ascent starts the glide.
            if self.last_takeoff_at is not None and now-self.last_takeoff_at < .45:
                return ()
            self.last_takeoff_at, self.takeoff_presses = now, self.takeoff_presses + 1
            return (Command("BIND", "JUMP", .12),)
        if sample is None or number(sample.get("pitch")) is None:
            return ()
        # FAST addon samples supply only XY. Keep the measured packet XYZ,
        # facing and sample time together before bounded prediction.
        position = sample.get("position") or state.get("player_world_position") or {}
        x, y, z = (number(position.get(axis)) for axis in ("x", "y", "z"))
        facing = number(sample.get("facing", state.get("orientation")))
        if None in (x, y, z, facing):
            return ()
        at = number(position.get("sample_time", sample.get("sample_time")))
        point, facing, pitch = self._predict((x, y, z), sample, facing, at, now)
        speed = number(sample.get("forward_velocity"))
        index = self._steer_index(point, now)
        desired_yaw, desired_pitch, distance = self._aim(point, index)
        target = self.waypoints[min(index, len(self.waypoints)-1)]
        if self.index >= len(self.waypoints):
            # Keep the touchdown near the target instead of gliding onward
            # after the server credits the area while we are still airborne.
            desired_pitch = LAND_PITCH
        elif (index < self.rings and speed is not None and speed < CRUISE_SPEED
              and point[2] - target[2] > DIVE_MARGIN):
            # A level glide bleeds ~1.5 yd/s²: spend spare height on speed.
            desired_pitch = min(desired_pitch, DIVE_PITCH)
        yaw_error = _wrap(desired_yaw - facing)
        pitch_error = desired_pitch - pitch
        extend = self._inside_turn_circle(point, facing, pitch, speed, target, yaw_error)
        yaw = 0 if extend or abs(yaw_error) <= YAW_DEADBAND else (1 if yaw_error > 0 else -1)
        pitch_sign = 0 if abs(pitch_error) <= PITCH_DEADBAND else (1 if pitch_error > 0 else -1)
        self.last_reason = "extend_out_of_turn_circle" if extend else (
            f"provisional_ring_{index + 1}" if index != self.index else f"ring_{index + 1}")
        boost = self._boost(state, now, point, speed, index, distance, yaw_error, pitch_error)
        keys = []
        if yaw:
            keys.append(("TURNLEFT" if yaw > 0 else "TURNRIGHT", abs(yaw_error) / TURN_RATE))
        if pitch_sign:
            keys.append(("PITCHUP" if pitch_sign > 0 else "PITCHDOWN", abs(pitch_error) / PITCH_RATE))
        if boost is not None and boost != "JUMP":
            # A discrete action-button tap: the executor releases the held
            # steering keys first.
            self._send(now, 0., 0, 0)
            return (Command("BIND", boost, .05),)
        if boost == "JUMP":
            self._send(now, .08, yaw, pitch_sign)
            return (Command("BIND", "JUMP", .08, simultaneous=tuple(key for key, _ in keys)),)
        if not keys:
            self._send(now, 0., 0, 0)
            return ()
        # Held together for the shorter need: the larger error is finished on
        # the next samples instead of over-steering the smaller one.
        keys.sort(key=lambda row: -row[1])
        duration = max(MIN_LEASE, min(MAX_LEASE, min(need for _key, need in keys)))
        self._send(now, duration, yaw, pitch_sign)
        return (Command("BIND", keys[0][0], duration, simultaneous=tuple(key for key, _ in keys[1:])),)

    def _boost(self, state, now, point, speed, index, distance, yaw_error, pitch_error) -> str | None:
        """Skyward Ascent (Jump) when the speed cannot carry the climb or the
        drake stalls; Surge Forward when slow, aligned and far from the point.

        The final point is approached without boosts (a landing area below)
        unless it lies TARGET_CLIMB_YARDS above: the Skytop race finishes on
        the observatory, 186 yd above its last ring."""
        if (index > self.rings or index >= len(self.waypoints) or speed is None
                or (self.last_boost_at is not None and now-self.last_boost_at < ABILITY_INTERVAL)):
            return None
        climb = self.waypoints[index][2] - point[2]
        if index == self.rings and climb <= TARGET_CLIMB_YARDS:
            return None
        boost = None
        if (climb > 0 and speed*speed < 2*GRAVITY*(climb + CLIMB_MARGIN)) or (speed < STALL_SPEED and climb > -15.):
            boost = "JUMP"
        elif (speed < SURGE_BELOW and distance >= SURGE_FARTHER
              and abs(yaw_error) <= SURGE_ALIGNED and abs(pitch_error) <= SURGE_ALIGNED):
            boost = self._surge_binding(state)
        if boost is not None:
            self.last_boost_at = now
        return boost
