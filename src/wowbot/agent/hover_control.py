"""Closed-loop flight to a point in the air: a flying quest vehicle.

Live 2026-10-26 11:05-11:06 (Training Wings 70061, the Ruby Whelpling): the
whelp hovered at z 284 while its targets were at z 161-278.  The ground
controller only turned and strafed it flat, Burning Bark (20 yd) never
reached, and the agent waited.  Height, facing and pitch come from the
vehicle's own client movement packets (the client is the vehicle's active
mover); a hovering vehicle sends none, so the last one is held.

Live 2026-10-26 11:31-11:36 (the same whelp): this seat is steered by its
pitch.  Move Forward flies along the pitch, and Jump / Sit-Move Down do not
climb or sink -- they swing the pitch toward straight up / straight down at
~3.1 rad/s and it stays there (MOVE_SET_PITCH packets, no ASCENDING flag).
Held to the 90 degree stop the whelp rose and sank in place for 28 s
("hover_no_progress"); at the stop a descend swung it over the top.
Burning Bark (a DEST_TRAJ missile) flies along the pitch too: two casts at
+77 degrees hit nothing, the next at -27 degrees credited.

So the vertical keys are learned per vehicle (``COUPLED``): when a press
turns the packet pitch they are pitch keys, and the pitch is steered to the
climb angle toward the hover point -- never to the stop -- and on arrival
to the angle at ``face`` (``aim``); otherwise Jump climbs and Sit descends
as on Steady Flight.  Arrival also means facing ``face``: an arrival facing
away left Tab "NOT_FACING" and the same approach re-arrived ~100 times.
No progress in three dimensions for STALL_SECONDS fails closed.  Owned by
MovementController.

Live 2026-10-26 13:41-13:57: right after boarding a mouse look turned the
whelp's pitch past straight down to about 180 degrees (upside down,
backwards).  Each key turns the pitch the shortest way toward its own
vertical -- Jump toward +90, Sit toward -90 (ties, at the stops, go up) --
so around 180 degrees the wrapped error flipped the key on every crossing
and the pitch swung there for minutes.  Upside down only Sit is pressed,
until straight down; from there Jump turns it forward.  And an approach
ends as soon as its unit is Tab-ready (``tab_guid``): 60 % of the samples
had the unit within Tab range but not in front, the 12 % that were ready
passed while a long approach ran on, and the agent Tabbed 4 times in 16 min.
"""
from __future__ import annotations

import math

from .models import Command, number

CLIMB_BAND = 2.
ARRIVE_VERTICAL = 4.
ARRIVE_FACING = .25
ARRIVE_PITCH = .15
TURN_IN_PLACE = .5
SOFT_TURN = .12
FORWARD_LEASE = .3
VERTICAL_LEASE = .3
Z_FRESH_SECONDS = 2.
STALL_SECONDS = 8.
STALL_YARDS = 1.
AIM_SECONDS = 8.
# Pitch steering (measured on the whelp: ~3.1 rad/s per held key).
PITCH_RATE = 3.1
PITCH_LIMIT = 1.2               # well short of the 90 degree stop
PITCH_DEADBAND = .08
PITCH_TAP_MAX = .1
PITCH_SETTLE_TIMEOUT = .5
LEARN_PITCH = .2                # a press turned the pitch: pitch keys
LEARN_Z = .5                    # it moved the height, not the pitch: climb keys
PROBE_LEASE = .1

# Per vehicle (creature entry): do Jump / Sit turn the pitch?
COUPLED: dict[str, bool] = {}


def _wrap(angle: float) -> float:
    return (angle+math.pi) % math.tau - math.pi


def vehicle_key(state: dict) -> str:
    parts = str(state.get("vehicle_guid") or "").split("-")
    return parts[5] if len(parts) > 6 and parts[0] == "Vehicle" else "vehicle"


def vehicle_sample(state: dict, now: float | None = None) -> dict:
    """The vehicle's own movement sample: fresh, else the held last one.

    In a vehicle only the vehicle mover's sample counts: right after
    boarding the last own sample can still be the walk to it."""
    fresh = state.get("packet_flight") or {}
    at = number(fresh.get("sample_time"))
    if (fresh.get("position") and at is not None and (now is None or 0 <= now-at <= Z_FRESH_SECONDS)
            and (state.get("in_vehicle") is not True or fresh.get("vehicle_mover") is True)):
        return fresh
    held = state.get("packet_vehicle_pose") or {}
    return held if state.get("in_vehicle") is True and held.get("position") else {}


def pitch_steerable(state: dict) -> bool:
    """This vehicle's pitch is known and steered by learned keys."""
    return COUPLED.get(vehicle_key(state)) is True and number(vehicle_sample(state).get("pitch")) is not None


class HoverControl:
    vehicle = True

    def __init__(self, target: dict, stop: float, bindings=None, *, face=None, aim: bool = False,
                 tab_guid: str | None = None) -> None:
        self.target = {k: float(target[k]) for k in ("x", "y", "z")}
        self.tab_guid = str(tab_guid) if tab_guid else None
        self.stop = max(1., float(stop))
        self.bindings = bindings
        self.face = None
        if isinstance(face, dict) and number(face.get("x")) is not None and number(face.get("y")) is not None:
            self.face = {"x": float(face["x"]), "y": float(face["y"])}
            if number(face.get("z")) is not None:
                self.face["z"] = float(face["z"])
        self.aim = aim
        self.phase = "APPROACH"
        self.samples: list[tuple[float, float, float, float]] = []
        self.last_reason = ""
        self.probe: dict | None = None
        self.settle: tuple[float, float] | None = None      # (tap end, give-up time)
        self.aim_started: float | None = None
        self.steer_end: float | None = None                 # last turn/pitch key release

    # -- measurements ------------------------------------------------------
    @staticmethod
    def _pose(state: dict, now: float):
        """(x, y, z | None, facing | None, pitch | None, sample time | None)."""
        sample = vehicle_sample(state, now)
        position = sample.get("position") or state.get("player_world_position") or {}
        x, y = number(position.get("x")), number(position.get("y"))
        z = number(position.get("z")) if position.get("source") == "PACKET_CLIENT_MOVEMENT" or (
            position.get("z_observed") is True) else None
        facing = number(sample.get("facing", state.get("orientation")))
        return x, y, z, facing, number(sample.get("pitch")), number(sample.get("sample_time"))

    def _errors(self, state: dict, now: float):
        pose = self._pose(state, now)
        x, y, z = pose[:3]
        if x is None or y is None:
            return None
        flat = math.hypot(self.target["x"]-x, self.target["y"]-y)
        return flat, (None if z is None else self.target["z"]-z), pose

    def _bound(self, binding: str) -> bool:
        return not self.bindings or self.bindings.contains(binding)

    def _key(self, state: dict) -> str:
        return vehicle_key(state)

    def _facing_error(self, pose) -> float | None:
        x, y, _z, facing = pose[:4]
        if self.face is None or facing is None:
            return None
        return _wrap(math.atan2(self.face["y"]-y, self.face["x"]-x) - facing)

    def _wanted_pitch(self, flat: float, dz: float | None, pose) -> float:
        if flat > self.stop or (dz is not None and abs(dz) > ARRIVE_VERTICAL):
            if dz is None:
                return 0.
            return max(-PITCH_LIMIT, min(PITCH_LIMIT, math.atan2(dz, max(flat, 1.))))
        x, y, z = pose[:3]
        if self.aim and self.face is not None and "z" in self.face and z is not None:
            reach = math.hypot(self.face["x"]-x, self.face["y"]-y)
            return max(-PITCH_LIMIT, min(PITCH_LIMIT, math.atan2(self.face["z"]-z, max(reach, 1.))))
        return 0.

    def _learn(self, state: dict, pose, now: float) -> None:
        """Did the last vertical press turn the pitch or move the height?"""
        probe = self.probe
        if probe is None:
            return
        _x, _y, z, _facing, pitch, at = pose
        if at is None or at < probe["until"]:
            if now-probe["at"] > 2.:
                self.probe = None
            return
        turned = None if pitch is None or probe["pitch"] is None else abs(_wrap(pitch-probe["pitch"]))
        if turned is not None and turned >= LEARN_PITCH:
            COUPLED[self._key(state)] = True
        elif (z is not None and probe["z"] is not None and abs(z-probe["z"]) >= LEARN_Z
              and (turned is None or turned < .05)):
            COUPLED[self._key(state)] = False
        self.probe = None

    # -- assessment --------------------------------------------------------
    def assess(self, state: dict, distance: float, tolerance: float, now: float) -> tuple[str, str]:
        if state.get("in_vehicle") is not True:
            return "FAILED", "hover_left_vehicle"
        errors = self._errors(state, now)
        if errors is None:
            return "MOVING", "hover_waiting_for_position"
        flat, dz, pose = errors
        x, y, z = pose[:3]
        if self.tab_guid and (state.get("target") or {}).get("guid") is None:
            from .packet_entity_facts import tab_target_check
            if tab_target_check(state, self.tab_guid, airborne=True)[0]:
                self.phase = "ARRIVED"
                return "ARRIVED", "hover_tab_ready"
        if flat <= self.stop and (dz is None or abs(dz) <= ARRIVE_VERTICAL):
            facing = self._facing_error(pose)
            pitch = pose[4]
            pitch_error = (abs(_wrap(self._wanted_pitch(flat, dz, pose)-pitch))
                           if COUPLED.get(self._key(state)) is True and pitch is not None else None)
            # Judged on a pose sampled after the last turn/pitch key: the
            # client reports ~0.1 s late, a turn still in flight overshoots.
            if (self._settled(pose[5], now) and (facing is None or abs(facing) <= ARRIVE_FACING)
                    and (pitch_error is None or pitch_error <= ARRIVE_PITCH)):
                self.phase = "ARRIVED"
                return "ARRIVED", "hover_arrived"
            self.aim_started = self.aim_started if self.aim_started is not None else now
            if now-self.aim_started > AIM_SECONDS:
                return "FAILED", "hover_aim_timeout"
            self.phase = "AIM"
            return "MOVING", "hover_aim"
        self.aim_started = None
        if z is not None:
            self.samples.append((now, x, y, z))
            self.samples = [row for row in self.samples if now-row[0] <= STALL_SECONDS + 1.]
            oldest = self.samples[0]
            if now-oldest[0] >= STALL_SECONDS and math.dist(oldest[1:], (x, y, z)) < STALL_YARDS:
                return "FAILED", "hover_no_progress"
        self.phase = "APPROACH" if flat > self.stop else "LEVEL"
        return "MOVING", f"hover_{self.phase.lower()}"

    def _settled(self, at: float | None, now: float) -> bool:
        """A pose sampled after the last turn/pitch key's release (or given up)."""
        end = self.steer_end
        return end is None or (at is not None and at >= end + .03) or now >= end + PITCH_SETTLE_TIMEOUT

    # -- commands ----------------------------------------------------------
    def commands(self, state: dict, distance: float, heading_error: float,
                 tolerance: float, now: float) -> tuple[Command, ...]:
        result = self._commands(state, heading_error, now)
        for command in result:
            if {command.binding, *command.simultaneous} & {"TURNLEFT", "TURNRIGHT", "JUMP", "SITORSTAND"}:
                self.steer_end = now + command.duration
        return result

    def _commands(self, state: dict, heading_error: float, now: float) -> tuple[Command, ...]:
        for binding in ("JUMP", "SITORSTAND", "MOVEFORWARD", "TURNLEFT", "TURNRIGHT"):
            if not self._bound(binding):
                raise ValueError(f"Hiányzó jármű-repülési binding: {binding}")
        errors = self._errors(state, now)
        if errors is None:
            return ()
        flat, dz, pose = errors
        self._learn(state, pose, now)
        x, y, _z, facing, pitch, at = pose
        arrived_xy = flat <= self.stop
        if not arrived_xy and facing is not None:
            heading_error = _wrap(math.atan2(self.target["y"]-y, self.target["x"]-x) - facing)
        elif arrived_xy:
            heading_error = self._facing_error(pose) or 0.
        turn = "TURNLEFT" if heading_error > 0 else "TURNRIGHT"
        coupled = COUPLED.get(self._key(state))
        if coupled is True and pitch is not None:
            return self._pitch_steer(flat, dz, pose, heading_error, turn, now)
        vertical = (() if dz is None or abs(dz) <= CLIMB_BAND else ("JUMP",) if dz > 0 else ("SITORSTAND",))
        if coupled is None and pitch is not None and abs(pitch) >= .35 and not vertical:
            # A leftover steep pitch: the first press that would level it
            # also tells which kind of seat this is.
            vertical = ("SITORSTAND",) if pitch > 0 else ("JUMP",)
        lease = PROBE_LEASE if coupled is None else VERTICAL_LEASE
        if vertical and coupled is None and self.probe is None:
            self.probe = {"at": now, "until": now + PROBE_LEASE, "pitch": pitch, "z": pose[2]}
        if arrived_xy:
            if vertical:
                return (Command("BIND", vertical[0], lease),)
            if abs(heading_error) > ARRIVE_FACING*.6 and self._settled(at, now):
                return (Command("BIND", turn, max(.04, min(.12, abs(heading_error) / math.pi * .55))),)
            return ()
        if abs(heading_error) > TURN_IN_PLACE:
            duration = max(.04, min(.12, abs(heading_error) / math.pi * .55))
            return (turn_lease(turn, min(duration, lease) if vertical else duration, vertical),)
        steer = (turn,) if abs(heading_error) > SOFT_TURN else ()
        if vertical and coupled is None:
            # A short probe press, forward riding along.
            return (Command("BIND", vertical[0], PROBE_LEASE, simultaneous=("MOVEFORWARD", *steer)),)
        return (Command("BIND", "MOVEFORWARD", FORWARD_LEASE if flat > self.stop + 8. else .12,
                        simultaneous=(*steer, *vertical)),)

    def _pitch_steer(self, flat, dz, pose, heading_error, turn, now) -> tuple[Command, ...]:
        """Steer the pitch with short taps (each measured before the next);
        fly forward along it when roughly right."""
        pitch, at = _wrap(pose[4]), pose[5]
        inverted = abs(pitch) > math.pi/2 + .02
        # Upside down: Sit (the shortest way to straight down), never Jump.
        error = (-((-math.pi/2 - pitch) % math.tau) if inverted
                 else self._wanted_pitch(flat, dz, pose) - pitch)
        vertical_only = flat <= self.stop and dz is not None and abs(dz) > ARRIVE_VERTICAL
        moving = (not inverted and (flat > self.stop or vertical_only)
                  and abs(heading_error) <= TURN_IN_PLACE and abs(error) < .6)
        # Aiming in place, each key's effect is measured before the next one
        # (the pose arrives ~0.1-0.2 s late); on the way the turn is continuous.
        aiming = flat <= self.stop and not vertical_only
        steady = not aiming or self._settled(at, now)
        turning = (abs(heading_error) > (SOFT_TURN if flat > self.stop else ARRIVE_FACING*.6) and steady
                   and not inverted)
        settled = steady and (self.settle is None or (at is not None and at >= self.settle[0])
                              or now >= self.settle[1])
        steer = (turn,) if turning else ()
        if abs(error) > PITCH_DEADBAND and settled:
            # Upside down the Sit runs into the stop at straight down: no
            # overshoot, so it is held longer.
            tap = max(.04, min(.3 if inverted else PITCH_TAP_MAX,
                               abs(error) / PITCH_RATE + (.05 if inverted else 0.)))
            self.settle = (now + tap + .03, now + tap + PITCH_SETTLE_TIMEOUT)
            return (Command("BIND", "JUMP" if error > 0 else "SITORSTAND", tap,
                            simultaneous=(*(("MOVEFORWARD",) if moving else ()), *steer)),)
        if moving:
            return (Command("BIND", "MOVEFORWARD", FORWARD_LEASE if flat > self.stop + 8. else .12,
                            simultaneous=steer),)
        if turning:
            return (Command("BIND", turn, max(.04, min(.12, abs(heading_error) / math.pi * .55))),)
        return ()


def turn_lease(turn: str, duration: float, vertical: tuple[str, ...]) -> Command:
    """A turn with a climb/descend key in one valid movement lease.

    The executor accepts Jump only as the lease key itself or beside Move
    Forward; Turn + Jump as simultaneous keys is rejected (and would drop
    the agent to MANUAL), so a climbing turn holds Jump with the turn."""
    if vertical == ("JUMP",):
        return Command("BIND", "JUMP", duration, simultaneous=(turn,))
    return Command("BIND", turn, duration, simultaneous=vertical)
