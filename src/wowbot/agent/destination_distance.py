"""Coordinate-space aware distance to a destination (issue #93).

``state.position`` is a normalized 0..1 UI-map point while production MOVE
and quest locations increasingly carry ``coordinate_space=WORLD_YARDS``.
Comparing the two produced meaningless values (~223 for the same spot), so
arrival, ranking and route-progress decisions silently misfired.  Every
comparison now happens inside one coordinate space; a missing or different
instance fails closed (None).
"""
from __future__ import annotations

import math

from .models import number

# Normalized-map thresholds the planner was tuned with, and their WORLD_YARDS
# counterparts.  A destination's own stop/arrival distance wins when larger,
# so the planner and the navigation controller agree on "arrived".
ARRIVED_MAP_UNITS = .003
ARRIVED_YARDS = 4.
LONG_MOVE_MAP_UNITS = .04
LONG_MOVE_YARDS = 40.
# Ordering scale only, for callers that rank or track progress by distance.
MAP_UNITS_PER_YARD = .001


def is_world_yards(destination: dict) -> bool:
    return str(destination.get("coordinate_space") or "").upper() == "WORLD_YARDS"


def world_yards(state: dict, destination: dict) -> float | None:
    player = state.get("player_world_position") or {}
    if str(player.get("coordinate_space") or "WORLD_YARDS").upper() != "WORLD_YARDS":
        return None
    px, py = number(player.get("x")), number(player.get("y"))
    x, y = number(destination.get("x")), number(destination.get("y"))
    instance = destination.get("instance_id")
    if (None in (px, py, x, y) or instance is None or player.get("instance_id") is None
            or str(instance) != str(player.get("instance_id"))):
        return None
    return math.hypot(x-px, y-py)


def map_units(state: dict, destination: dict) -> float | None:
    pos = state.get("position") or {}
    px, py = number(pos.get("x")), number(pos.get("y"))
    x, y = number(destination.get("x")), number(destination.get("y"))
    if (None in (px, py, x, y) or not (0 <= px <= 1 and 0 <= py <= 1)
            or destination.get("map_id") != state.get("map_id")):
        return None
    return math.hypot(x-px, y-py)


def scaled_distance(state: dict, destination: dict) -> float | None:
    """Distance in map units; WORLD_YARDS is converted with MAP_UNITS_PER_YARD."""
    if is_world_yards(destination):
        yards = world_yards(state, destination)
        return None if yards is None else yards * MAP_UNITS_PER_YARD
    return map_units(state, destination)


def arrived(state: dict, destination: dict) -> bool:
    if is_world_yards(destination):
        yards = world_yards(state, destination)
        if yards is None:
            return False
        own = max((number(destination.get(key)) or 0.)
                  for key in ("stop_distance", "arrival_radius"))
        return yards <= max(ARRIVED_YARDS, own)
    distance = map_units(state, destination)
    return distance is not None and distance <= ARRIVED_MAP_UNITS


def long_move(state: dict, destination: dict) -> bool:
    if is_world_yards(destination):
        yards = world_yards(state, destination)
        return yards is not None and yards > LONG_MOVE_YARDS
    distance = map_units(state, destination)
    return distance is not None and distance > LONG_MOVE_MAP_UNITS


def world_arrived(world, destination: dict) -> bool:
    """``arrived`` for a WorldModel-like object; normalized goals keep using
    its own ``distance`` so test doubles and snapshots stay authoritative."""
    if is_world_yards(destination):
        return arrived(world.state, destination)
    distance = world.distance(destination)
    return distance is not None and distance <= ARRIVED_MAP_UNITS


def world_long_move(world, destination: dict) -> bool:
    if is_world_yards(destination):
        return long_move(world.state, destination)
    distance = world.distance(destination)
    return distance is not None and distance > LONG_MOVE_MAP_UNITS
