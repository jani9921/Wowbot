"""Canonical pure projection of existing scoped entity facts; no input or planner."""
from .value_helpers import number


def entity(state: dict, guid) -> dict | None:
    entities = state.get("packet_entities")
    value = entities.get(str(guid or "")) if isinstance(entities, dict) and guid else None
    return value if isinstance(value, dict) and not value.get("removed") else None

def best_position(value: dict) -> dict | None:
    """Spline estimate when moving, else the last server position."""
    position = value.get("position") if isinstance(value, dict) else None
    if not isinstance(position, dict):
        return None
    point = position.get("estimate") or position
    if any(number(point.get(axis)) is None for axis in ("x", "y", "z")):
        return None
    return {"x": point["x"], "y": point["y"], "z": point["z"], "coordinate_space": "WORLD_YARDS",
            "instance_id": value.get("map_id"), "z_known": True,
            "source": position.get("source"), "age": position.get("age")}

def travel_position(value: dict) -> dict | None:
    """Where a moving unit is going (its spline's end), else ``best_position``.

    Live 2026-10-25 10:57:25-10:57:41 (Westward Bound): Bjorn ran ~6 yd/s to
    the next camp; walking at his interpolated point re-planned the turn-in
    walk every second.  The server's spline end is where he will stand."""
    point = best_position(value)
    position = value.get("position") if isinstance(value, dict) else None
    destination = position.get("destination") if isinstance(position, dict) else None
    estimate = position.get("estimate") if isinstance(position, dict) else None
    if (point is None or not isinstance(destination, dict) or not isinstance(estimate, dict)
            or estimate.get("arrived") is True
            or any(number(destination.get(axis)) is None for axis in ("x", "y", "z"))):
        return point
    return {**point, "x": destination["x"], "y": destination["y"], "z": destination["z"],
            "source": "PACKET_MONSTER_MOVE_DESTINATION"}
