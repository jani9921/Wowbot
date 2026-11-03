"""Closed-loop HoverControl on a pitch-steered seat (live 2026-10-26 11:31-11:36).

The model is what the whelp's own packets showed: Move Forward flies along
the pitch at ~7 yd/s, Jump / Sit swing the pitch toward +/-90 degrees at
~3.1 rad/s (from the stop the tie went "over the top"), turning ~3 rad/s,
and the client reports the pose ~0.1 s late.  The controller must reach
hover points far below and above without ever reaching the stop.
"""
import math

import pytest

import wowbot.agent.hover_control as hover
from wowbot.agent.hover_control import HoverControl

DT, LATENCY, SPEED, PITCH_RATE, TURN_RATE = .075, .1, 7., 3.1, 3.


def toward(pitch, stop, amount):
    """Live: a key turns the pitch the shortest way to its vertical (+-90);
    from the opposite stop (a tie) it turns up, i.e. over the top from +90."""
    diff = (stop - pitch + math.pi) % math.tau - math.pi
    if abs(abs(diff) - math.pi) < 1e-9:
        diff = math.pi
    step = max(-amount, min(amount, diff))
    return (pitch + step + math.pi) % math.tau - math.pi


class Whelp:
    def __init__(self, x, y, z, facing=0., pitch=0.):
        self.x, self.y, self.z, self.facing, self.pitch, self.t = x, y, z, facing, pitch, 0.
        self.held: dict[str, float] = {}
        self.history: list[tuple] = []
        self.max_pitch = abs(pitch)

    def press(self, commands):
        for command in commands:
            for key in (command.binding, *command.simultaneous):
                self.held[key] = self.t + command.duration

    def step(self):
        # Each key acts only for the part of the step it is held.
        down = {k: max(0., min(DT, until-self.t)) for k, until in self.held.items()}
        for key, stop in (("JUMP", math.pi/2), ("SITORSTAND", -math.pi/2)):
            if down.get(key):
                self.pitch = toward(self.pitch, stop, PITCH_RATE*down[key])
        self.facing += TURN_RATE*(down.get("TURNLEFT", 0.) - down.get("TURNRIGHT", 0.))
        forward = down.get("MOVEFORWARD", 0.)
        self.x += SPEED*forward*math.cos(self.pitch)*math.cos(self.facing)
        self.y += SPEED*forward*math.cos(self.pitch)*math.sin(self.facing)
        self.z += SPEED*forward*math.sin(self.pitch)
        self.max_pitch = max(self.max_pitch, abs(self.pitch))
        self.t += DT
        self.history.append((self.t, self.x, self.y, self.z, self.facing, self.pitch))

    def state(self):
        seen = next((row for row in reversed(self.history) if row[0] <= self.t - LATENCY), None) or (
            self.t, self.x, self.y, self.z, self.facing, self.pitch)
        at, x, y, z, facing, pitch = seen
        position = {"x": x, "y": y, "z": z, "source": "PACKET_CLIENT_MOVEMENT", "sample_time": at,
                    "coordinate_space": "WORLD_YARDS", "instance_id": 2444}
        return {"in_vehicle": True, "movement": {"flying": True}, "orientation": facing,
                "player_world_position": position, "monotonic_time": self.t,
                "packet_flight": {"sample_time": at, "facing": facing, "pitch": pitch, "flying": True,
                                  "vehicle_mover": True, "position": position}}


def fly(whelp, target, *, face=None, seconds=40.):
    control = HoverControl(target, 3., face=face, aim=face is not None)
    for _ in range(int(seconds/DT)):
        state = whelp.state()
        status, reason = control.assess(state, 0., 0., whelp.t)
        if status != "MOVING":
            return status, reason, control
        whelp.press(control.commands(state, 0., 0., 0., whelp.t))
        whelp.step()
    return "TIMEOUT", "", control


@pytest.fixture(autouse=True)
def clean():
    saved = dict(hover.COUPLED)
    hover.COUPLED.clear()
    yield
    hover.COUPLED.clear()
    hover.COUPLED.update(saved)


@pytest.mark.parametrize("target", [
    {"x": 1581.3, "y": -200.4, "z": 199.},      # live: a weedling 86 yd below, 30 yd away
    {"x": 1602.2, "y": -238.6, "z": 330.},      # far above
    {"x": 1551.0, "y": -241.0, "z": 250.},      # nearly straight below
])
def test_the_pitch_seat_reaches_far_below_and_above_without_the_stop(target):
    whelp = Whelp(1550.1, -242.2, 285.1, facing=2.67)
    status, reason, _control = fly(whelp, target)
    assert (status, reason) == ("ARRIVED", "hover_arrived")
    assert hover.COUPLED["vehicle"] is True                 # learned from the first press
    assert whelp.max_pitch < math.pi/2 - .1                 # never at the 90 degree stop


def test_a_leftover_steep_pitch_is_levelled_and_the_unit_aimed_at():
    whelp = Whelp(1588.0, -213.6, 259.2, facing=1.72, pitch=1.34)   # live 11:34:16, after the misses
    weed = {"x": 1595.6, "y": -215.9, "z": 241.2}
    status, reason, _control = fly(whelp, {"x": 1589.9, "y": -214.2, "z": 247.2}, face=weed)
    assert (status, reason) == ("ARRIVED", "hover_arrived")
    aim = math.atan2(weed["z"]-whelp.z, math.hypot(weed["x"]-whelp.x, weed["y"]-whelp.y))
    bearing = math.atan2(weed["y"]-whelp.y, weed["x"]-whelp.x)
    assert abs(whelp.pitch - aim) <= .2 and abs((bearing-whelp.facing+math.pi) % math.tau - math.pi) <= .3


@pytest.mark.parametrize("pitch", [2.9, -2.8, 3.1, -3.1])
def test_upside_down_it_turns_back_through_straight_down(pitch):
    """Live 13:41: a mouse look left the pitch near 180 degrees and the old
    wrapped error swung it there for minutes."""
    whelp = Whelp(1547.2, -244.9, 285.6, facing=1.58, pitch=pitch)
    status, reason, _control = fly(whelp, {"x": 1520.3, "y": -220.0, "z": 269.0})
    assert (status, reason) == ("ARRIVED", "hover_arrived")
    flips = sum(1 for a, b in zip(whelp.history, whelp.history[1:]) if abs(b[5]-a[5]) > math.pi)
    assert flips <= 1                                      # one pass through 180 at most
