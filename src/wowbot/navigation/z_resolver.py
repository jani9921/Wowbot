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
                "layer_id": self.layer_id,
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
    # A FALL_STARTED/ENDED pair also comes from a jump or a step down a slope;
    # a fall of ~2 s drops at most ~40 yd (live 2026-10-06: a 1 s "fall" put
    # the player 90 yd lower, on the pit floor, in the resolver's view).
    FALL_MAX_DROP = 40.
    # Hrun's lower spiral is 4.5 yd from the reported player X/Y at a
    # polygon edge (2026-10-06 11:58). Four yards missed the real floor and
    # left only the overlying rim in the exact column.
    NEAR_RADIUS = 5.
    BROKEN_HOLD_SECONDS = 2.
    # FALL_ENDED arrives with the slow state page, 1-3 s after the landing;
    # the landing layer is decided on the following samples' own column.
    FALL_PENDING_SECONDS = 3.
    FALL_EVENT_FRESH_SECONDS = 10.
    FORGET_YARDS = 40.
    FORGET_SECONDS = 180.
    LAYER_RADIUS = 2.5
    TARGET_RADIUS = 8.
    TARGET_PATHS = 8
    FLOOR_CLEARANCE = 2.        # a VMAP surface this close above a floor: no room to stand
    LOW_CONFIDENCE = .6
    STOREY_YARDS = 6.
    FLOOR_CUE_PROBE_YARDS = 25.
    FLOOR_CUE_PROBE_SECONDS = 45.

    def __init__(self, geometry=None) -> None:
        self.geometry = geometry
        self.player: ResolvedPosition | None = None
        self.fall_count = 0
        self.last_fall: dict | None = None
        self._fall_sequence: float | None = None
        self._heights_cache: tuple | None = None
        self.last_target: ResolvedPosition | None = None
        self.last_target_failure: str | None = None
        self._broken_since: float | None = None
        self._pending_fall: dict | None = None
        self._floor_cue_probe_started: float | None = None
        self._floor_cue_probe_travel = 0.
        self._floor_cue_probe_target: tuple | None = None
        self._floor_cue_probe_exhausted: tuple | None = None
        self._indoors: bool | None = None

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
        layers = self._call("walkable_layers_at", instance_id,
                            {"x": x, "y": y, "instance_id": instance_id}, self.LAYER_RADIUS) or []
        refs = [(float(item["z"]), item.get("layer_id")) for item in layers
                if isinstance(item, dict) and isinstance(item.get("z"), (int, float))]
        heights = ([height for height, _ref in refs] if refs else
                   self._call("walkable_heights_at", instance_id,
                              {"x": x, "y": y, "instance_id": instance_id}, self.LAYER_RADIUS) or [])
        values = sorted(float(value) for value in heights if isinstance(value, (int, float)))
        groups: list[list[float]] = []
        for height in values:
            if groups and height-groups[-1][0] <= 1.5:
                groups[-1].append(height)
            else:
                groups.append([height])
        # Multiple Detour polygons on one sloped floor are not multiple
        # storeys.  Keep their median height but retain individual refs for
        # layer diagnostics and future topology checks.
        heights = [group[len(group)//2] for group in groups]
        self._heights_cache = (key, heights, refs)
        return heights

    def _layer_id(self, instance_id: int, x: float, y: float, z: float):
        self._layers_at(instance_id, x, y)
        refs = self._heights_cache[2] if self._heights_cache is not None else ()
        match = min(refs, key=lambda item: abs(item[0]-z), default=None)
        return match[1] if match is not None and abs(match[0]-z) <= 2. else None

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
        self._floor_cue_probe_started = None
        self._floor_cue_probe_travel = 0.
        self._floor_cue_probe_target = None
        self._floor_cue_probe_exhausted = None

    def bootstrap_player_from_down_cue(self, target: ResolvedPosition | None, *,
                                       observed_at: float | None, indoors: bool | None,
                                       now: float) -> bool:
        """Permit a bounded surface-layer probe with a fresh outdoor sensor.

        A terrain-selected first fix at a stacked X/Y is only a hypothesis.
        The BELOW arrow alone cannot distinguish it: a lower player floor may
        also have an even lower target floor.  Require the current addon's
        outdoor flag as separate evidence that the terrain-matching layer is
        the likely start.  The alternative remains in the belief and motion
        must reach a unique navmesh column within a short travel/time budget.
        """
        player = self.player
        if (player is None or player.confidence >= self.LOW_CONFIDENCE
                or not player.alternatives or target is None
                or target.instance_id != player.instance_id or indoors is not False
                or target.confidence < .8 or target.reachable is not True
                or "vmap_floor" not in target.evidence
                or observed_at is None or not 0. <= now-observed_at <= 2.):
            return False
        exhausted = self._floor_cue_probe_exhausted
        if (exhausted is not None and exhausted[0] == player.instance_id
                and math.hypot(exhausted[1]-target.x, exhausted[2]-target.y) <= 14.
                and math.hypot(exhausted[3]-player.x, exhausted[4]-player.y) <= 15.):
            return False
        hypotheses = (player.z, *player.alternatives)
        above = [height for height in hypotheses if height > target.z+3.]
        terrain = self._terrain_z(player.instance_id, player.x, player.y)
        if (len(above) != 1 or abs(above[0]-player.z) > 2.
                or terrain is None or abs(terrain-player.z) > 3.
                or any(terrain-height < 8. for height in player.alternatives)):
            return False
        self.player = replace(player, confidence=.7, source="FLOOR_CUE_PROBE",
                              evidence=("fresh_quest_dot_below", "addon_outdoors",
                                        "terrain_surface_hypothesis",
                                        "target_vmap_floor_reachable"), at=now)
        self._floor_cue_probe_started = now
        self._floor_cue_probe_travel = 0.
        self._floor_cue_probe_target = (player.instance_id, target.x, target.y)
        return True

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
        indoors = (state.get("movement") or {}).get("indoors")
        self._indoors = indoors if isinstance(indoors, bool) else None
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
        elif previous is not None and (fell or self._pending_fall is not None):
            if fell:
                self._pending_fall = {"from_z": previous.z, "at": now}
            resolved = self._landing(previous, layers, x, y, now, instance_id)
        elif previous is not None:
            resolved = self._continue(previous, layers, x, y, now, instance_id, route_z)
        else:
            resolved = self._first_fix(layers, x, y, now, instance_id, route_z)
        if resolved.source not in {"CONTINUITY"}:
            resolved = replace(resolved, layer_id=self._layer_id(instance_id, x, y, resolved.z))
        self.player = resolved
        return resolved

    def _landing(self, previous: ResolvedPosition, layers: list[float], x: float, y: float,
                 now: float, instance_id: int) -> ResolvedPosition:
        """Decide a reported fall on the current sample's own column."""
        pending = self._pending_fall
        from_z = pending["from_z"]
        if any(abs(height-from_z) <= self.STEP for height in layers):
            self._pending_fall = None               # still over the old floor: a hop or a jump
            return self._continue(previous, layers, x, y, now, instance_id)
        below = [height for height in layers
                 if from_z - self.FALL_MAX_DROP <= height <= from_z - self.FALL_MIN_DROP]
        if below:
            z = max(below)
            self._pending_fall = None
            self.fall_count += 1
            self.last_fall = {"from_z": from_z, "to_z": z, "at": now, "x": x, "y": y}
            return ResolvedPosition(x, y, z, .85, "FALL", instance_id,
                                    alternatives=tuple(h for h in layers if h != z),
                                    evidence=("fall_event",), at=now)
        if now - pending["at"] > self.FALL_PENDING_SECONDS:
            self._pending_fall = None
            return self._continue(previous, layers, x, y, now, instance_id)
        return replace(previous, x=x, y=y, at=now, confidence=.5, evidence=("fall_pending",))

    ROUTE_HINT_YARDS = 3.

    def _route_choice(self, candidates: list[float], fallback: float, route_z: float | None) -> float:
        """Among continuity-reachable floors, the one the followed route is on."""
        if route_z is None or len(candidates) < 2:
            return fallback
        routed = min(candidates, key=lambda height: abs(height-route_z))
        return routed if abs(routed-route_z) <= self.ROUTE_HINT_YARDS else fallback

    def _continue(self, previous: ResolvedPosition, layers: list[float], x: float, y: float,
                  now: float, instance_id: int, route_z: float | None = None) -> ResolvedPosition:
        moved = math.hypot(previous.x-x, previous.y-y)
        allowed = self.SLOPE*moved + self.STEP
        if previous.source == "FLOOR_CUE_PROBE" and previous.alternatives:
            self._floor_cue_probe_travel += moved
            started = self._floor_cue_probe_started
            expired = (self._floor_cue_probe_travel > self.FLOOR_CUE_PROBE_YARDS
                       or started is None or now-started > self.FLOOR_CUE_PROBE_SECONDS)
            origins = (previous.z, *previous.alternatives)
            possible = [height for height in layers
                        if any(abs(height-origin) <= allowed for origin in origins)]
            surface = [height for height in possible if abs(height-previous.z) <= allowed]
            if expired or not surface:
                self._floor_cue_probe_started = None
                if self._floor_cue_probe_target is not None:
                    self._floor_cue_probe_exhausted = (*self._floor_cue_probe_target, x, y)
                self._floor_cue_probe_target = None
                return replace(previous, x=x, y=y, at=now, confidence=.5,
                               source="CONTINUITY",
                               evidence=("floor_cue_probe_exhausted" if expired
                                         else "floor_cue_probe_contradicted",))
            chosen = min(surface, key=lambda height: abs(height-previous.z))
            remaining = tuple(height for height in possible if height != chosen)
            if not remaining:
                self._floor_cue_probe_started = None
                self._floor_cue_probe_travel = 0.
                self._floor_cue_probe_target = None
                self._floor_cue_probe_exhausted = None
                return ResolvedPosition(x, y, chosen, .85, "MMAP", instance_id,
                                        evidence=("floor_cue_probe_converged",), at=now)
            return ResolvedPosition(x, y, chosen, .7, "FLOOR_CUE_PROBE", instance_id,
                                    alternatives=remaining,
                                    evidence=("floor_cue_probe_unresolved",), at=now)
        if (previous.confidence < .7 and previous.alternatives
                and (any(item.startswith("first_fix_") for item in previous.evidence)
                     or "layer_hypotheses_unresolved" in previous.evidence)):
            # Repeated samples at the same stacked X/Y are not independent
            # evidence.  The old code promoted a terrain-guessed rim from
            # confidence .5 to .95 on the very next frame, even in a cave.
            # A broken *formerly tracked* floor or a pending fall is
            # different: its old alternatives are not permission to jump
            # 45 yd just because one edge sample lacks the current floor.
            origins = (previous.z, *previous.alternatives)
            possible = self._cave_pruned(instance_id, x, y, [
                height for height in layers
                if any(abs(height-origin) <= allowed for origin in origins)])
            if possible:
                chosen = min(possible, key=lambda height: abs(height-previous.z))
                remaining = tuple(height for height in possible if height != chosen)
                confidence = .85 if not remaining else min(previous.confidence, .5)
                return ResolvedPosition(x, y, chosen, confidence, "MMAP", instance_id,
                                        alternatives=remaining,
                                        evidence=("layer_hypotheses_converged" if not remaining
                                                  else "layer_hypotheses_unresolved",), at=now)
        nearest = min(layers, key=lambda height: abs(height-previous.z))
        if abs(nearest-previous.z) <= allowed:
            reachable = [height for height in layers if abs(height-previous.z) <= allowed]
            nearest = self._route_choice(reachable, nearest, route_z)
        others = tuple(height for height in layers if height != nearest)
        if abs(nearest-previous.z) <= allowed:
            self._broken_since = None
            ambiguous = any(abs(height-previous.z) <= allowed for height in others)
            if ambiguous and route_z is not None and abs(nearest-route_z) <= self.ROUTE_HINT_YARDS:
                return ResolvedPosition(x, y, nearest, .85, "MMAP", instance_id, alternatives=others,
                                        evidence=("continuity_route",), at=now)
            return ResolvedPosition(x, y, nearest, .7 if ambiguous else .95, "MMAP", instance_id,
                                    alternatives=others, evidence=("continuity",), at=now)
        # Standing on a polygon edge (the column under X/Y misses the floor we
        # are on): the walkable polygons a few yards around still have it.
        near = [height for height in self._near_heights(instance_id, x, y)
                if abs(height-previous.z) <= allowed]
        if near:
            self._broken_since = None
            z = self._route_choice(near, min(near, key=lambda height: abs(height-previous.z)), route_z)
            return ResolvedPosition(x, y, z, .7, "MMAP", instance_id, alternatives=tuple(layers),
                                    evidence=("continuity_near",), at=now)
        # No layer is reachable by walking from the last one (teleport, a
        # vehicle, an unreported fall): keep the old floor as an uncertain
        # hypothesis. Selecting the only polygon in this column would turn
        # a missing cave-edge polygon into a false jump to the rim.
        if self._broken_since is None:
            self._broken_since = now
        if now - self._broken_since < self.BROKEN_HOLD_SECONDS:
            return replace(previous, x=x, y=y, at=now, confidence=.4,
                           source="CONTINUITY", evidence=("continuity_broken_hold",))
        self._broken_since = None
        return ResolvedPosition(x, y, previous.z, .4, "CONTINUITY", instance_id,
                                alternatives=tuple(layers),
                                evidence=("continuity_broken",), at=now)

    def _near_heights(self, instance_id: int, x: float, y: float) -> list[float]:
        return [float(point["z"]) for point in self._call(
                    "walkable_points_near", instance_id, {"x": x, "y": y, "instance_id": instance_id},
                    self.NEAR_RADIUS) or ()
                if isinstance(point.get("z"), (int, float))]

    # Live 2026-10-06 (agent started inside Hrun's pit): the first fix took the
    # terrain-matching rim (z 98) for a player on a cave floor (45-60); every
    # required route then failed as ambiguous.  The addon's IsIndoors()
    # (0.9.57+) says "in a cave" while the topmost layer is the open terrain
    # and real floors lie well below it: the surface is not our floor.
    CAVE_SURFACE_MATCH_YARDS = 3.
    CAVE_FLOOR_GAP_YARDS = 8.

    def _cave_pruned(self, instance_id: int, x: float, y: float, heights: list[float]) -> list[float]:
        if self._indoors is not True or len(heights) < 2:
            return heights
        top = max(heights)
        terrain = self._terrain_z(instance_id, x, y)
        if terrain is None or abs(terrain-top) > self.CAVE_SURFACE_MATCH_YARDS:
            return heights
        lower = [height for height in heights if height < top-self.CAVE_FLOOR_GAP_YARDS]
        return lower or heights

    def _first_fix(self, layers: list[float], x: float, y: float, now: float, instance_id: int,
                   route_z: float | None) -> ResolvedPosition:
        layers = self._cave_pruned(instance_id, x, y, layers)
        if len(layers) == 1:
            return ResolvedPosition(x, y, layers[0], .95, "MMAP", instance_id, at=now)
        hint, source = route_z, "ROUTE"
        if hint is None:
            hint, source = self._terrain_z(instance_id, x, y), "TERRAIN"
        if hint is None:
            hint, source = max(layers), "HIGHEST"
        z = min(layers, key=lambda height: abs(height-hint))
        # A still-active route is a continuity observation from this process;
        # bare terrain at a stacked column is only a guess.
        confidence = .75 if source == "ROUTE" and abs(z-hint) <= 2. else .5
        return ResolvedPosition(x, y, z, confidence, "COMBINED", instance_id,
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
        self.last_target_failure = None
        candidates: dict[tuple[int, int, int], _TargetCandidate] = {}

        def add(cx: float, cy: float, cz: float, evidence: str) -> None:
            # Preserve distinct pockets on the same floor.  The nearest one
            # can be disconnected by a cave wall while another is reachable.
            key = (round(cz), round(cx/4.), round(cy/4.))
            known = candidates.get(key)
            if known is None or math.hypot(cx-x, cy-y) < math.hypot(known.x-x, known.y-y):
                candidates[key] = _TargetCandidate(cx, cy, cz, evidence=[evidence])
        for height in self._layers_at(instance_id, x, y):
            add(x, y, height, "mmap_at_xy")
        for point in self._call("walkable_points_near", instance_id, {"x": x, "y": y}, radius) or ():
            pz = number(point.get("z"))
            if pz is not None:
                add(float(point["x"]), float(point["y"]), pz, "mmap_near")
        if not candidates:
            terrain = self._terrain_z(instance_id, x, y)
            if terrain is None or floor_hint in {"SAME", "ABOVE", "BELOW"}:
                self.last_target = None
                self.last_target_failure = "no_walkable_target_layer"
                return None
            resolved = ResolvedPosition(x, y, terrain, .3, "TERRAIN", instance_id,
                                        evidence=("no_navmesh",))
            self.last_target = resolved
            return resolved
        surfaces = self._vmap_surfaces(instance_id, x, y)
        terrain = self._terrain_z(instance_id, x, y)
        pz = player.z if player is not None else z_hint
        ordered = sorted(candidates.values(), key=lambda item: abs(item.z-pz) if pz is not None else -item.z)
        if pz is not None and floor_hint in {"BELOW", "ABOVE"}:
            # A minimap arrow means another storey, not a slope 3 yd higher
            # on the same floor (live 21:44: ABOVE from z -4.9 chose -1.8 and
            # the MOVE "arrived" under the cocoon's ledge at 60).
            ordered = [item for item in ordered
                       if (item.z < pz-self.STOREY_YARDS if floor_hint == "BELOW"
                           else item.z > pz+self.STOREY_YARDS)]
            if not ordered:
                self.last_target = None
                self.last_target_failure = "no_layer_matching_floor_cue"
                return None
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
                    candidate.score += 20. if dz < -self.STOREY_YARDS else -50.
                elif floor_hint == "ABOVE":
                    candidate.score += 20. if dz > self.STOREY_YARDS else -50.
        has_path_query = callable(getattr(self.geometry, "find_path", None))
        if player is not None and has_path_query:
            for candidate in sorted(ordered, key=lambda item: item.score, reverse=True)[:self.TARGET_PATHS]:
                self._score_path(instance_id, player, candidate)
            viable = [item for item in ordered if item.reachable is True]
            if not viable:
                self.last_target = None
                self.last_target_failure = "no_reachable_target_layer"
                return None
        else:
            viable = ordered
        best = max(viable, key=lambda item: item.score)
        confidence = max(0., min(1., best.score / 280.))
        resolved = ResolvedPosition(
            best.x, best.y, best.z, confidence,
            "COMBINED" if "vmap_floor" in best.evidence else "MMAP", instance_id,
            layer_id=self._layer_id(instance_id, best.x, best.y, best.z),
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
                "last_target_failure": self.last_target_failure,
                "fall_count": self.fall_count, "last_fall": self.last_fall}
