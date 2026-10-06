"""One owner of heights for navigation: the player's layer and a target's Z.

User 2026-10-06 ("Z resolver"): never take a height from one source.  The
reliable target height is a walkable navmesh polygon that physically exists
(VMAP floor) and is reachable from the player's current layer.  Retail
exports no player height at all, so the player's own layer is resolved here
too, from sample to sample:

* candidates are the navmesh layers under the player's X/Y;
* between samples the height can change only as much as walking allows
  (slope x horizontal travel + a step/jump);
* a FALL_ENDED event moves the player to the highest layer below;
* without history (start, teleport) the terrain height / route hint picks
  among several layers, with low confidence and the alternatives kept.

Before this, five places guessed the player's height independently (route
projection, continuity, terrain hint, fall check, start probe) and a route
projection kept the player on the upper spiral after he had fallen (live
2026-10-06, Hrun's pit).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import Any

from wowbot.agent.models import number


@dataclass(frozen=True)
class ResolvedPosition:
    x: float
    y: float
    z: float
    confidence: float
    source: str                                  # MMAP / VMAP / TERRAIN / COMBINED / CONTINUITY / FALL
    instance_id: int | None = None
    layer_id: Any = None
    reachable: bool | None = None
    path_length: float | None = None
    alternatives: tuple[float, ...] = ()
    evidence: tuple[str, ...] = ()
    at: float | None = None

    def point(self) -> dict:
        return {"x": self.x, "y": self.y, "z": self.z, "instance_id": self.instance_id,
                "coordinate_space": "WORLD_YARDS", "z_known": True, "z_observed": False,
                "z_estimated": True, "z_source": f"Z_RESOLVER_{self.source}",
                "z_confidence": round(self.confidence, 3)}

    def snapshot(self) -> dict:
        return {"x": round(self.x, 1), "y": round(self.y, 1), "z": round(self.z, 2),
                "confidence": round(self.confidence, 3), "source": self.source,
                "reachable": self.reachable,
                "path_length": round(self.path_length, 1) if self.path_length is not None else None,
                "alternatives": [round(value, 1) for value in self.alternatives],
                "evidence": list(self.evidence)}


@dataclass
class _TargetCandidate:
    x: float
    y: float
    z: float
    score: float = 0.
    reachable: bool | None = None
    path_length: float | None = None
    evidence: list = field(default_factory=list)


class ZResolver:
    SLOPE = 1.2                 # yards of height per yard walked (~50 degrees)
    STEP = 2.5                  # a step or a jump
    FALL_MIN_DROP = 1.5
    FALL_EVENT_FRESH_SECONDS = 10.
    FORGET_YARDS = 40.
    FORGET_SECONDS = 180.
    LAYER_RADIUS = 2.5
    TARGET_RADIUS = 8.
    TARGET_PATHS = 5
    FLOOR_CLEARANCE = 2.        # a VMAP surface this close above a floor: no room to stand
    LOW_CONFIDENCE = .6

    def __init__(self, geometry=None) -> None:
        self.geometry = geometry
        self.player: ResolvedPosition | None = None
        self.fall_count = 0
        self.last_fall: dict | None = None
        self._fall_sequence: float | None = None
        self._heights_cache: tuple | None = None
        self.last_target: ResolvedPosition | None = None

    # -- geometry ---------------------------------------------------------------
    def _call(self, name: str, *args, **kwargs):
        method = getattr(self.geometry, name, None)
        if not callable(method):
            return None
        try:
            return method(*args, **kwargs)
        except Exception:                        # geometry is evidence, never a crash
            return None

    def _layers_at(self, instance_id: int, x: float, y: float) -> list[float]:
        key = (instance_id, round(x, 1), round(y, 1))
        if self._heights_cache is not None and self._heights_cache[0] == key:
            return self._heights_cache[1]
        heights = self._call("walkable_heights_at", instance_id,
                             {"x": x, "y": y, "instance_id": instance_id}, self.LAYER_RADIUS) or []
        heights = sorted(float(value) for value in heights if isinstance(value, (int, float)))
        self._heights_cache = (key, heights)
        return heights

    def _terrain_z(self, instance_id: int, x: float, y: float) -> float | None:
        sample = self._call("terrain_sample", instance_id, {"x": x, "y": y})
        if sample is None or getattr(sample, "is_hole", False):
            return None
        return number(getattr(sample, "terrain_z", None))

    def _vmap_surfaces(self, instance_id: int, x: float, y: float) -> list[float]:
        return [float(value) for value in (self._call("vmap_surfaces_at", instance_id,
                                                      {"x": x, "y": y}) or ())]

    # -- the player's own layer --------------------------------------------------
    def seed_player(self, instance_id: int, x: float, y: float, z: float, now: float,
                    source: str = "SEED") -> None:
        self.player = ResolvedPosition(float(x), float(y), float(z), .9, source, int(instance_id), at=now)

    def current_player(self, instance_id: int, x: float, y: float, now: float) -> ResolvedPosition | None:
        last = self.player
        if (last is None or last.instance_id != instance_id
                or math.hypot(last.x-x, last.y-y) > self.FORGET_YARDS
                or not 0 <= now - (last.at or now) <= self.FORGET_SECONDS):
            return None
        return last

    def observe_player(self, state: dict, now: float, *, route_z: float | None = None) -> ResolvedPosition | None:
        player = state.get("player_world_position") or {}
        try:
            instance_id, x, y = int(player["instance_id"]), float(player["x"]), float(player["y"])
        except (KeyError, TypeError, ValueError):
            return self.player
        fell = self._new_fall(state)
        observed = number(player.get("z")) if player.get("z_observed") is True else None
        previous = self.current_player(instance_id, x, y, now)
        layers = self._layers_at(instance_id, x, y)
        if observed is not None:
            resolved = ResolvedPosition(x, y, observed, .99, "OBSERVED", instance_id, at=now)
        elif not layers:
            if previous is None:
                return None
            resolved = replace(previous, x=x, y=y, at=now, confidence=min(previous.confidence, .5),
                               source="CONTINUITY", evidence=("no_navmesh_layer",))
        elif previous is not None and fell:
            below = [height for height in layers if height < previous.z - self.FALL_MIN_DROP]
            if below:
                z = max(below)
                self.fall_count += 1
                self.last_fall = {"from_z": previous.z, "to_z": z, "at": now, "x": x, "y": y}
                resolved = ResolvedPosition(x, y, z, .85, "FALL", instance_id,
                                            alternatives=tuple(h for h in layers if h != z),
                                            evidence=("fall_event",), at=now)
            else:
                resolved = self._continue(previous, layers, x, y, now, instance_id)
        elif previous is not None:
            resolved = self._continue(previous, layers, x, y, now, instance_id)
        else:
            resolved = self._first_fix(layers, x, y, now, instance_id, route_z)
        self.player = resolved
        return resolved

    def _continue(self, previous: ResolvedPosition, layers: list[float], x: float, y: float,
                  now: float, instance_id: int) -> ResolvedPosition:
        moved = math.hypot(previous.x-x, previous.y-y)
        allowed = self.SLOPE*moved + self.STEP
        nearest = min(layers, key=lambda height: abs(height-previous.z))
        others = tuple(height for height in layers if height != nearest)
        if abs(nearest-previous.z) <= allowed:
            ambiguous = any(abs(height-previous.z) <= allowed for height in others)
            return ResolvedPosition(x, y, nearest, .7 if ambiguous else .95, "MMAP", instance_id,
                                    alternatives=others, evidence=("continuity",), at=now)
        # No layer is reachable by walking from the last one (teleport, a
        # vehicle, an unreported fall): take the nearest, say we are unsure.
        return ResolvedPosition(x, y, nearest, .4, "MMAP", instance_id, alternatives=others,
                                evidence=("continuity_broken",), at=now)

    def _first_fix(self, layers: list[float], x: float, y: float, now: float, instance_id: int,
                   route_z: float | None) -> ResolvedPosition:
        if len(layers) == 1:
            return ResolvedPosition(x, y, layers[0], .95, "MMAP", instance_id, at=now)
        hint, source = route_z, "ROUTE"
        if hint is None:
            hint, source = self._terrain_z(instance_id, x, y), "TERRAIN"
        if hint is None:
            hint, source = max(layers), "HIGHEST"
        z = min(layers, key=lambda height: abs(height-hint))
        return ResolvedPosition(x, y, z, .5, "COMBINED", instance_id,
                                alternatives=tuple(height for height in layers if height != z),
                                evidence=(f"first_fix_{source.lower()}",), at=now)

    def _new_fall(self, state: dict) -> bool:
        events = [event for event in state.get("events") or ()
                  if isinstance(event, dict) and event.get("event_type") == "FALL_ENDED"]
        if not events:
            return False
        event = max(events, key=lambda item: number(item.get("sequence")) or -1.)
        sequence = number(event.get("sequence"))
        seen = self._fall_sequence
        if sequence is None or (seen is not None and sequence <= seen):
            return False
        self._fall_sequence = sequence
        said, stamp = number(event.get("timestamp")), number(state.get("timestamp"))
        if seen is None and (said is None or stamp is None
                             or stamp - said > self.FALL_EVENT_FRESH_SECONDS):
            return False                                 # an old fall in the first snapshot
        return True

    # -- a target's height -------------------------------------------------------
    def resolve_target(self, instance_id: int, x: float, y: float, *,
                       player: ResolvedPosition | None, floor_hint: str | None = None,
                       z_hint: float | None = None, radius: float | None = None) -> ResolvedPosition | None:
        """The walkable, reachable height at/near (x, y) -- user design §1-§12.

        ``floor_hint``: SAME (yellow minimap dot), BELOW / ABOVE (dot with an
        arrow, lower-layer text), else None.
        """
        radius = self.TARGET_RADIUS if radius is None else radius
        candidates: dict[int, _TargetCandidate] = {}

        def add(cx: float, cy: float, cz: float, evidence: str) -> None:
            key = round(cz)
            known = candidates.get(key)
            if known is None or math.hypot(cx-x, cy-y) < math.hypot(known.x-x, known.y-y):
                candidates[key] = _TargetCandidate(cx, cy, cz, evidence=[evidence])
        for height in self._layers_at(instance_id, x, y):
            add(x, y, height, "mmap_at_xy")
        for point in self._call("walkable_points_near", instance_id, {"x": x, "y": y}, radius) or ():
            pz = number(point.get("z"))
            if pz is not None and round(pz) not in candidates:
                add(float(point["x"]), float(point["y"]), pz, "mmap_near")
        if not candidates:
            terrain = self._terrain_z(instance_id, x, y)
            if terrain is None:
                return None
            resolved = ResolvedPosition(x, y, terrain, .3, "TERRAIN", instance_id,
                                        evidence=("no_navmesh",))
            self.last_target = resolved
            return resolved
        surfaces = self._vmap_surfaces(instance_id, x, y)
        terrain = self._terrain_z(instance_id, x, y)
        pz = player.z if player is not None else z_hint
        ordered = sorted(candidates.values(), key=lambda item: abs(item.z-pz) if pz is not None else -item.z)
        for index, candidate in enumerate(ordered):
            candidate.score += 80.                                       # a walkable polygon
            if surfaces:
                if any(-self.FLOOR_CLEARANCE <= candidate.z-surface <= 1. for surface in surfaces):
                    candidate.score += 50.; candidate.evidence.append("vmap_floor")
                if any(0. < surface-candidate.z < self.FLOOR_CLEARANCE for surface in surfaces):
                    candidate.score -= 80.; candidate.evidence.append("vmap_no_headroom")
            if terrain is not None and abs(candidate.z-terrain) <= 2.:
                candidate.evidence.append("terrain")
            if pz is not None:
                dz = candidate.z - pz
                if abs(dz) <= 10.:
                    candidate.score += 30.
                if abs(dz) > 60.:
                    candidate.score -= 50.
                if floor_hint == "SAME":
                    candidate.score += 20. if abs(dz) <= 8. else -20.
                elif floor_hint == "BELOW":
                    candidate.score += 20. if dz < -3. else -50.
                elif floor_hint == "ABOVE":
                    candidate.score += 20. if dz > 3. else -50.
            if player is not None and index < self.TARGET_PATHS:
                self._score_path(instance_id, player, candidate)
        best = max(ordered, key=lambda item: item.score)
        confidence = max(0., min(1., best.score / 280.))
        resolved = ResolvedPosition(
            best.x, best.y, best.z, confidence,
            "COMBINED" if "vmap_floor" in best.evidence else "MMAP", instance_id,
            reachable=best.reachable, path_length=best.path_length,
            alternatives=tuple(item.z for item in ordered if item is not best),
            evidence=tuple(best.evidence))
        self.last_target = resolved
        return resolved

    def _score_path(self, instance_id: int, player: ResolvedPosition, candidate: _TargetCandidate) -> None:
        start = {**player.point(), "instance_id": instance_id}
        end = {"x": candidate.x, "y": candidate.y, "z": candidate.z, "z_known": True,
               "z_observed": True, "instance_id": instance_id}
        path = self._call("find_path", instance_id, start, end)
        anchors = getattr(path, "anchors", None) or ()
        last = anchors[-1] if anchors else None
        if last is None or math.dist((float(last["x"]), float(last["y"]), float(last.get("z", candidate.z))),
                                     (candidate.x, candidate.y, candidate.z)) > 3.:
            candidate.reachable = False
            candidate.score -= 100.
            candidate.evidence.append("no_path")
            return
        candidate.reachable = True
        candidate.path_length = float(getattr(path, "cost", 0.) or 0.)
        candidate.score += 100.
        candidate.evidence.append("reachable")
        straight = math.dist((player.x, player.y, player.z), (candidate.x, candidate.y, candidate.z))
        if candidate.path_length > 3.*straight + 40.:
            candidate.score -= 40.
            candidate.evidence.append("long_detour")

    def snapshot(self) -> dict:
        return {"player": self.player.snapshot() if self.player is not None else None,
                "last_target": self.last_target.snapshot() if self.last_target is not None else None,
                "fall_count": self.fall_count, "last_fall": self.last_fall}
