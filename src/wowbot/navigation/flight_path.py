"""Declarative ordered flight path: geometry and observation requirements.

The path has no quest/lesson knowledge, input authority or independent state.
The existing ReachMovementController owns its runtime progress and phases.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math

from wowbot.verification.conditions import evaluate_condition, validate_condition


def _point(value):
    if not isinstance(value, dict) or any(type(value.get(k)) not in {int, float}
                                         or not math.isfinite(value[k]) for k in ("x", "y", "z")):
        raise ValueError("Flight path requires finite XYZ waypoints")
    return {k: float(value[k]) for k in ("x", "y", "z")}


@dataclass(frozen=True)
class FlightPath:
    instance_id: int
    mode: str
    waypoints: tuple[dict, ...]
    landing: dict
    checkpoint_conditions: tuple[dict | None, ...]
    arrival_condition: dict | None = None
    radius: float = 4.5
    # A travel leg cut at the planning horizon ends at a point in the air:
    # passing it completes the leg and the next MOVE plans on from there.
    end_in_air: bool = False
    # A landing with no navmesh under it (a dome top, a tower): touching down
    # within ``landing_radius`` is the arrival; no walking leg follows.
    landing_on_navmesh: bool = True
    landing_radius: float | None = None

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or value.get("mode") != "SKYRIDING":
            raise ValueError("Unsupported explicit flight-path mode")
        instance = value.get("instance_id")
        points, conditions = value.get("waypoints"), value.get("checkpoint_conditions")
        radius = value.get("radius", 4.5)
        end_in_air = value.get("end_in_air", False)
        on_navmesh = value.get("landing_on_navmesh", True)
        landing_radius = value.get("landing_radius")
        if (type(instance) is not int or instance < 0 or not isinstance(points, (list, tuple))
                or len(points) > 128 or type(radius) not in {int, float}
                or not math.isfinite(radius) or not 0 < radius <= 50 or type(end_in_air) is not bool
                or type(on_navmesh) is not bool
                or (landing_radius is not None and (type(landing_radius) not in {int, float}
                                                    or not 0 < landing_radius <= 50))):
            raise ValueError("Invalid flight-path geometry")
        if conditions is None:
            conditions = [None] * len(points)
        if not isinstance(conditions, (list, tuple)) or len(conditions) != len(points):
            raise ValueError("Flight-path checkpoints do not match its waypoints")
        for condition in [*conditions, value.get("arrival_condition")]:
            if condition is not None:
                validate_condition(condition)
        return cls(instance, value["mode"], tuple(_point(p) for p in points), _point(value.get("landing")),
                   tuple(conditions), value.get("arrival_condition"), float(radius), end_in_air,
                   on_navmesh, None if landing_radius is None else float(landing_radius))

    def to_dict(self):
        return asdict(self)

    @property
    def identity(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]

    def progress(self, state, previous=0, *, now=None):
        """Sequential verified checkpoints; geometry never overrides a required signal."""
        sample = state.get("packet_flight") or {}
        position = sample.get("position") or state.get("player_world_position") or {}
        clock = state.get("monotonic_time") if now is None else now
        measured = position.get("sample_time")
        position_fresh = (type(clock) in {int, float} and type(measured) in {int, float}
                          and 0 <= clock-measured <= 1.2
                          and position.get("instance_id") == self.instance_id)
        index = max(0, min(len(self.waypoints), previous))
        for offset in range(index, len(self.waypoints)):
            condition = self.checkpoint_conditions[offset]
            if condition is not None:
                passed = evaluate_condition(condition, state) is True
            else:
                try:
                    passed = position_fresh and math.dist(tuple(position[k] for k in ("x", "y", "z")),
                                       tuple(self.waypoints[offset][k] for k in ("x", "y", "z"))) <= self.radius
                except (KeyError, TypeError, ValueError):
                    passed = False
            if not passed:
                break
            index = offset + 1
        return index

    def air_segment_complete(self, state, previous=0):
        return self.progress(state, previous) == len(self.waypoints)

    def arrival_confirmed(self, state):
        return evaluate_condition(self.arrival_condition, state) is True


def airborne(state, now):
    sample = state.get("packet_flight") or {}
    at = sample.get("sample_time")
    fresh = type(at) in {int, float} and 0 <= now-at <= 1.2
    return bool((fresh and (sample.get("adv_flying") or sample.get("flying")))
                or (state.get("movement") or {}).get("flying") is True)


def grounded(state, now):
    movement = state.get("movement") or {}
    return movement.get("flying") is False and movement.get("falling") is not True and not airborne(state, now)


ROOT_WAIT_SECONDS = 15.


def rooted(state, now, max_age=ROOT_WAIT_SECONDS):
    """The server holds the own character in place (a race start line, live
    2026-10-25 21:05:51); a root older than ``max_age`` is not trusted."""
    root = state.get("movement_rooted") or {}
    at = root.get("sampled_at")
    return root.get("rooted") is True and type(at) in {int, float} and 0 <= now-at <= max_age
