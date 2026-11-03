"""Bounded alternative approach goals for a server-identified quest object.

These are search points, never interaction/arrival evidence. The existing
MOVE and NavigationService must validate and walk each navmesh route.
"""
from __future__ import annotations

import math

from .models import number
from .packet_entity_facts import best_position, entity


class ObjectApproachSearch:
    ANGLES = (-math.pi/6, math.pi/6, -math.pi/3, math.pi/3, -math.pi/2, math.pi/2)
    CONTACT_YARDS = 2.5
    MAX_RADIUS_YARDS = 40.
    MAX_SECONDS = 90.
    FLOOR_YARDS = 3.
    MOVE_FAILURES = frozenset({"supported_stuck", "no_progress", "path_blocked", "no_route",
                               "route_endpoint_outside_arrival_envelope",
                               "required_navmesh_route_unavailable"})

    def __init__(self):
        self._context = None
        self._objects: dict[str, dict] = {}

    def _sync(self, state: dict) -> None:
        quests = tuple(sorted((str(q.get("quest_id")), bool(q.get("is_complete")),
                               tuple((str(o.get("current")), bool(o.get("is_complete")))
                                     for o in q.get("objectives") or () if isinstance(o, dict)))
                              for q in state.get("active_quests") or () if isinstance(q, dict)))
        context = (state.get("session_id"), state.get("character_guid"),
                   str((state.get("player_world_position") or {}).get("instance_id")), quests)
        if context != self._context:
            self._context = context
            self._objects.clear()

    def _record(self, state: dict, spot: dict) -> dict | None:
        self._sync(state)
        record = self._objects.get(str(spot.get("guid")))
        instance = spot.get("instance_id", (state.get("player_world_position") or {}).get("instance_id"))
        if record and (str(record["point"].get("instance_id")) != str(instance)
                       or math.dist(tuple(record["point"][k] for k in ("x", "y", "z")),
                                    tuple(spot[k] for k in ("x", "y", "z"))) > self.CONTACT_YARDS):
            self._objects.pop(str(spot.get("guid")), None)
            return None
        return record

    CLOSER_YARDS = 2.5          # a range failure probes inside the 3.5 yd Interact reach
    CLOSER_ANGLES = (0., -math.pi/6, math.pi/6, -math.pi/3, math.pi/3, math.pi)

    def reject(self, state: dict, guid, *, player_z=None, reason: str = "") -> None:
        value = entity(state, guid)
        point = best_position(value) if value else None
        player = state.get("player_world_position") or {}
        px, py, now = number(player.get("x")), number(player.get("y")), number(state.get("monotonic_time"))
        if (point is None or None in (px, py, now)
                or str(point["instance_id"]) != str(player.get("instance_id"))
                or state.get("is_in_combat") or state.get("is_dead") or state.get("is_ghost")):
            return
        z = number(player_z) if player_z is not None else (
            number(player.get("z")) if player.get("z_known") is not False else None)
        radius = math.hypot(px-point["x"], py-point["y"])
        if (not 1. <= radius <= self.MAX_RADIUS_YARDS
                or z is not None and abs(z-point["z"]) > self.FLOOR_YARDS):
            return
        spot = {**point, "guid": str(guid)}
        record = self._record(state, spot)
        if record is None:
            record = self._objects[str(guid)] = {
                "point": point, "since": now, "contacts": [], "goals": [], "pending": None}
        if not any(math.hypot(px-c[0], py-c[1]) <= self.CONTACT_YARDS for c in record["contacts"]):
            record["contacts"].append((px, py, z))
        record["pending"] = None
        record["needs_probe"] = True
        # Live 2026-11-02 (Fresh Dirt): after F7 OUT_OF_RANGE the probes ring
        # was as wide as the failed spot (8.5 yd) -- never closer.  A range
        # failure probes inside the Interact reach instead.
        if "range" in str(reason) or "far" in str(reason):
            if not record.get("closer"):
                record["goals"] = []
            record["closer"] = True

    def blocked(self, state: dict, spot: dict) -> bool:
        record = self._record(state, spot)
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        return record is not None and None not in (px, py) and any(
            math.hypot(px-c[0], py-c[1]) <= self.CONTACT_YARDS for c in record["contacts"])

    def goal(self, state: dict, spot: dict) -> dict | None:
        """Overrides for a canonical MOVE; {} = centre, None = budget exhausted."""
        spot = {"instance_id": (state.get("player_world_position") or {}).get("instance_id"), **spot}
        record = self._record(state, spot)
        if record is None or not (record.get("needs_probe") or self.blocked(state, spot)):
            return {}
        now = number(state.get("monotonic_time"))
        if now is None or not 0 <= now-record["since"] <= self.MAX_SECONDS:
            return None
        if record["pending"] is not None:
            return dict(record["pending"])
        px, py, z = record["contacts"][-1]
        bearing = math.atan2(py-spot["y"], px-spot["x"])
        closer = record.get("closer") is True
        angles = self.CLOSER_ANGLES if closer else self.ANGLES
        radius = (max(1., min(self.CLOSER_YARDS, math.hypot(px-spot["x"], py-spot["y"])-2.)) if closer
                  else max(3.5, math.hypot(px-spot["x"], py-spot["y"])) + .75)
        while len(record["goals"]) < len(angles):
            index = len(record["goals"])
            angle = bearing + angles[index]
            x, y = spot["x"]+math.cos(angle)*radius, spot["y"]+math.sin(angle)*radius
            old = [*record["contacts"], *record["goals"]]
            record["goals"].append((x, y, z))
            if not closer and any(math.hypot(x-p[0], y-p[1]) <= self.CONTACT_YARDS for p in old):
                continue
            record["pending"] = {
                "x": x, "y": y, "z": z if z is not None else spot["z"],
                "z_known": True, "z_source": "SERVER_OBJECT_APPROACH_PROBE",
                "stop_distance": .75, "require_navmesh": True, "face_on_arrival": True,
                "face_towards": {k: spot[k] for k in ("x", "y", "z", "instance_id")},
                "object_approach_probe": index+1}
            return dict(record["pending"])
        return None

    def note_move_result(self, result: dict, state: dict, params: dict) -> None:
        if params.get("purpose") != "APPROACH_QUEST_OBJECT_SPAWN" or not params.get("server_entity_guid"):
            return
        guid = str(params["server_entity_guid"])
        self._sync(state)
        if params.get("object_approach_probe"):
            record = self._objects.get(guid)
            if record and result.get("outcome") in {"SUCCESS", "FAILURE"}:
                record["pending"] = None
                record["needs_probe"] = result["outcome"] == "FAILURE"
        elif (result.get("outcome") == "FAILURE"
              and str(result.get("reason") or "").lower() in self.MOVE_FAILURES):
            self.reject(state, guid)
