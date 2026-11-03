"""A small Skyriding flight model from the user's decoded runs (2026-10-25).

Not the game: a level glide holds height and bleeds speed, diving gains
GRAVITY·sin(-pitch) up to ~65 yd/s, Surge Forward +20, Skyward Ascent +43 up
(decaying 20 yd/s²).  Measured on the agent's own course (live 17:26-17:30):
turn keys rotate 2.35 rad/s, pitch keys 1.4 rad/s, below ~12 yd/s the drake
sinks.  Like the live loop:

* the controller runs at ``control_hz`` (FAST addon frames, ~20 Hz) while
  the client sends a movement packet on a key change (at most every
  ``packet_gap`` s) and otherwise a heartbeat every 0.5 s;
* a packet reaches the controller ``delivery`` s after it was sent (fast
  lane peek ~0.05 s; the old medium-tick polling was 0.3-0.6 s);
* a ring credit arrives ``credit_delay`` s after the pass (medium tick);
* a lease replaces the previous one (InputScheduler); an action-button tap
  first releases every held key (InputExecutor.execute).
Rings credit within 10 yd.
"""
from __future__ import annotations

import math

TURN_RATE, PITCH_RATE = 2.35, 1.4
SURGE_ID = 372608


class SkyridingSim:
    def __init__(self, start, facing, course, *, ground_z=100., control_hz=20., packet_gap=.13,
                 heartbeat=.5, delivery=.05, credit_delay=.6, input_latency=.03, vigor=6,
                 vigor_regen=None, ring_radius=10.):
        self.x, self.y, self.z = start
        self.start_z = start[2]
        self.yaw, self.pitch = facing, 0.
        self.v, self.up = 0., 0.
        self.airborne = self.adv = False
        self.ground_z = ground_z
        self.course = [tuple(p[:3]) for p in course]
        self.ring_radius = ring_radius
        self.passed = 0
        self.passed_at: list[float] = []
        self.t = 0.
        self.held: dict[str, float] = {}       # binding -> release time
        self.pending: list[tuple[float, object]] = []
        self.dt = 1. / control_hz
        self.packet_gap, self.heartbeat = packet_gap, heartbeat
        self.delivery, self.credit_delay, self.latency = delivery, credit_delay, input_latency
        self.vigor = vigor
        self.vigor_regen = vigor_regen
        self._regen_at = 0.
        self.closest = []
        self.packets: list[tuple[float, dict]] = []
        self.key_changed = True
        self.surges = self.ascents = 0

    # -- input -------------------------------------------------------------
    def apply(self, command) -> None:
        self.pending.append((self.t + self.latency, command))

    def _execute(self, command):
        if command.binding.startswith("ACTIONBUTTON"):
            self.held.clear()                      # execute(): release movement first
            self.key_changed = True
            if command.binding == "ACTIONBUTTON1" and self.adv and self.vigor > 0:
                self.vigor -= 1
                self.surges += 1
                self.v += 20.
            return
        keys = (command.binding, *command.simultaneous)
        for key in list(self.held):
            if key not in keys:
                del self.held[key]
                self.key_changed = True
        for key in keys:
            if key == "JUMP":
                self._jump()
                continue
            if key not in self.held:
                self.key_changed = True
            self.held[key] = self.t + command.duration

    def _jump(self):
        self.key_changed = True
        if not self.airborne:
            self.airborne, self.up = True, 8.
        elif not self.adv or self.vigor > 0:
            if self.adv:
                self.vigor -= 1
                self.ascents += 1
            self.adv, self.up = True, 43.
            self.v = max(self.v, 14.)

    # -- physics -----------------------------------------------------------
    def _step(self, dt):
        for at, command in list(self.pending):
            if at <= self.t:
                self.pending.remove((at, command))
                self._execute(command)
        for key, end in list(self.held.items()):
            if end <= self.t:
                del self.held[key]
                self.key_changed = True
        down = lambda key: key in self.held
        if self.vigor_regen and self.adv and self.t >= self._regen_at:
            self._regen_at = self.t + self.vigor_regen
            self.vigor = min(6, self.vigor + 1)
        self.yaw = (self.yaw + (down("TURNLEFT") - down("TURNRIGHT")) * TURN_RATE * dt) % math.tau
        if self.adv:
            self.pitch = max(-1.5, min(1.5, self.pitch + (down("PITCHUP") - down("PITCHDOWN")) * PITCH_RATE * dt))
            accel = -14. * math.sin(self.pitch) - 1.5
            if self.v > 65. and accel > -6.:
                accel = -6.                        # boosts decay back toward the cap
            self.v = max(8., self.v + accel * dt)
            self.up = max(0., self.up - 20. * dt)
            sink = 14. if self.v < 12. else 0.
            self.x += self.v * math.cos(self.pitch) * math.cos(self.yaw) * dt
            self.y += self.v * math.cos(self.pitch) * math.sin(self.yaw) * dt
            self.z += (self.v * math.sin(self.pitch) + self.up - sink) * dt
        elif self.airborne:
            self.up -= 20. * dt
            self.z += self.up * dt
            if self.z <= self.start_z and self.up < 0:
                self.airborne, self.z, self.up = False, self.start_z, 0.
        if self.adv and self.z <= self.ground(self.x, self.y):
            self.adv = self.airborne = False
            self.z, self.v, self.pitch = self.ground(self.x, self.y), 0., 0.
        if self.passed < len(self.course):
            distance = math.dist((self.x, self.y, self.z), self.course[self.passed])
            self.closest.append((self.passed, distance))
            if distance <= self.ring_radius:
                self.passed += 1
                self.passed_at.append(self.t)
        self.t += dt
        self._maybe_packet()

    def ground(self, x, y) -> float:
        return self.ground_z

    def _maybe_packet(self):
        last = self.packets[-1][0] if self.packets else -1e9
        if ((self.key_changed or self.held) and self.t - last >= self.packet_gap) or self.t - last >= self.heartbeat:
            self.key_changed = False
            self.packets.append((self.t, {"x": self.x, "y": self.y, "z": self.z, "pitch": self.pitch,
                                          "facing": self.yaw, "v": self.v, "up": self.up, "adv": self.adv}))
            del self.packets[:-64]

    def run_tick(self):
        for _ in range(max(1, int(round(self.dt / .01)))):
            self._step(.01)

    # -- what the controller sees -----------------------------------------
    def state(self, quest_id, rings, ring_entry="182800", target_entry="182847"):
        visible = [(at, p) for at, p in self.packets if at <= self.t - self.delivery]
        if not visible:
            visible = [(self.t, {"x": self.x, "y": self.y, "z": self.z, "pitch": self.pitch, "facing": self.yaw,
                                 "v": self.v, "up": self.up, "adv": self.adv})]
        at, packet = visible[-1]
        credited = sum(1 for when in self.passed_at if when <= self.t - self.credit_delay)
        position = {"x": packet["x"], "y": packet["y"], "z": packet["z"], "z_observed": True,
                    "z_source": "PACKET_CLIENT_MOVEMENT", "sample_time": at}
        return {
            "monotonic_time": self.t, "is_mounted": True, "orientation": packet["facing"],
            "movement": {"flying": packet["adv"]},
            "player_world_position": position,
            "packet_flight": {"sample_time": at, "pitch": packet["pitch"], "facing": packet["facing"],
                              "forward_velocity": packet["v"], "up_velocity": packet["up"],
                              "adv_flying": packet["adv"], "position": position},
            "packet_quest_credits": {str(quest_id): {ring_entry: {"count": min(credited, rings)},
                                                     target_entry: {"count": 1 if credited > rings else 0}}},
            # A scene course counts the own client's ring triggers instead.
            "route_counters": {"scene": {"checkpoints": min(credited, rings),
                                         "race_complete": 1 if credited > rings else 0}},
            "skyriding_controls": True,
            "skyriding_bar": {"kind": "SKYRIDING", "page": 11, "actions": [
                {"name": "Surge Forward", "id": SURGE_ID, "action": "ACTIONBUTTON1",
                 "is_usable": self.vigor > 0, "lacks_resource": self.vigor <= 0, "cooldown_remaining": 0},
                {"name": "Skyward Ascent", "id": 372610, "action": "ACTIONBUTTON2",
                 "is_usable": self.vigor > 0, "lacks_resource": self.vigor <= 0, "cooldown_remaining": 0}]},
        }
