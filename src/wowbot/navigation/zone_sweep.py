"""Multi-floor zone-sweep geometry (REV4 NavigationService split).

Moved out of ``NavigationService`` (SRC_MELY_AUDIT 4.3: SearchCoverage API).
Planning-only answers for the quest-zone sweep:

* ``lower_layer_point`` -- the deepest walkable point next to a quest location
  that the mmap connects to the player (Hrun's pit),
* ``route_hops`` -- the rim-to-bottom route resampled into short hops,
* ``sweep_hops`` -- those hops with the quest's TDB object spawns inserted
  where the route passes them.

The sweep ledger (visited hops, direction, done) stays with the service: the
planner, the arrival check and the hop-passed check share it.  This reads the
owner's ZResolver, navmesh and two owner limits through providers and owns
only the lower-layer cache, which a navigation reset clears.
"""
from __future__ import annotations

import math


class ZoneSweepGeometry:
    LOWER_LAYER_RADIUS_YARDS = 35.
    LOWER_LAYER_MIN_DROP_YARDS = 15.
    LOWER_LAYER_SURFACE_YARDS = 6.
    LOWER_LAYER_MAX_ROUTES = 12

    def __init__(self, layers, navmesh, hop_yards, continuity_yards) -> None:
        self._layers = layers                       # () -> the owner's current ZResolver
        self._navmesh = navmesh                     # () -> the owner's navmesh
        self._hop_yards = hop_yards                 # () -> NavigationService.ZONE_SWEEP_HOP_YARDS
        self._continuity_yards = continuity_yards   # () -> NavigationService.LAYER_CONTINUITY_YARDS
        self.lower_layer_cache: dict = {}

    def reset(self) -> None:
        self.lower_layer_cache.clear()

    def _player_layer(self) -> tuple | None:
        """(instance, x, y, z, at) of the player's resolved layer (ZResolver)."""
        player = self._layers().player
        return (None if player is None else
                (player.instance_id, player.x, player.y, player.z, player.at))

    def sweep_hops(self, state: dict, bottom: dict | None, targets=()) -> list[dict]:
        """The rim-to-bottom route resampled every ``ZONE_SWEEP_HOP_YARDS`` (the owner's),
        with the quest's TDB object spawns placed where the route passes them
        (user 2026-10-13: the walk's route is the TDB spawns + the dots)."""
        hops = self.route_hops(state, bottom) if bottom is not None else []
        points = [t for t in targets or () if isinstance(t, dict)
                  and all(isinstance(t.get(k), (int, float)) for k in ("x", "y", "z"))]
        if not points:
            return hops
        if not hops:
            # No route to the bottom: visit the spawns from the top floor down.
            return [{**t, "target": True} for t in sorted(points, key=lambda t: -float(t["z"]))]
        result = [dict(hop) for hop in hops]
        for target in sorted(points, key=lambda t: -float(t["z"])):
            nearest = min(range(len(result)), key=lambda i: math.hypot(result[i]["x"]-target["x"],
                                                                        result[i]["y"]-target["y"])
                          + 2.*abs(result[i]["z"]-target["z"]))
            result.insert(nearest+1, {"x": float(target["x"]), "y": float(target["y"]),
                                      "z": float(target["z"]), "target": True, "hint": target.get("hint")})
        return result

    def route_hops(self, state: dict, bottom: dict) -> list[dict]:
        find = getattr(self._navmesh(), "find_path", None)
        player = state.get("player_world_position") or {}
        try:
            instance_id = int(player["instance_id"])
            start = {"x": float(player["x"]), "y": float(player["y"]), "instance_id": instance_id}
        except (KeyError, TypeError, ValueError):
            return []
        last = self._player_layer()
        if (last is not None and last[0] == instance_id
                and math.hypot(last[1]-start["x"], last[2]-start["y"]) <= self._continuity_yards()):
            # Start on the tracked own layer (an estimate: the navmesh may still probe).
            start.update({"z": last[3], "z_known": True, "z_estimated": True,
                          "z_source": "NAVMESH_LAYER_CONTINUITY"})
        if not callable(find):
            return []
        path = find(instance_id, start, {**bottom, "instance_id": instance_id})
        anchors = [anchor for anchor in (path.anchors if path is not None else ())
                   if isinstance(anchor.get("z"), (int, float))]
        if len(anchors) < 2:
            return []
        hops, travelled = [], 0.
        for left, right in zip(anchors, anchors[1:]):
            a = (float(left["x"]), float(left["y"]), float(left["z"]))
            b = (float(right["x"]), float(right["y"]), float(right["z"]))
            segment = math.dist(a, b)
            position = 0.
            while segment > 0 and travelled + (segment-position) >= self._hop_yards():
                position += self._hop_yards() - travelled
                ratio = position/segment
                hops.append({"x": a[0]+(b[0]-a[0])*ratio, "y": a[1]+(b[1]-a[1])*ratio,
                             "z": a[2]+(b[2]-a[2])*ratio})
                travelled = 0.
            travelled += segment - position
        end = anchors[-1]
        hops.append({"x": float(end["x"]), "y": float(end["y"]), "z": float(end["z"])})
        return hops

    def lower_layer_point(self, state: dict, destination: dict) -> dict | None:
        """The deepest reachable walkable point next to a quest location.

        Design doc §5 (live 2026-10-05 12:25, "Who Lurks in the Pit"): the
        quest POI sits on the rim of a pit; its cocoons are ~110 yd lower,
        reached by a spiral path.  Without Z the POI projects onto the rim
        and the agent "arrived" there.  This returns a point on a walkable
        layer at least 15 yd under the POI's own surface, within 35 yd, that
        the mmap connects to the player (route found), else None.  Planning
        only: the caller turns it into a normal navmesh MOVE.
        """
        navmesh = self._navmesh()
        near = getattr(navmesh, "walkable_points_near", None)
        find = getattr(navmesh, "find_path", None)
        project = getattr(navmesh, "project_position", None)
        player = state.get("player_world_position") or {}
        try:
            instance_id = int(destination.get("instance_id", player.get("instance_id")))
            x, y = float(destination["x"]), float(destination["y"])
            px, py = float(player["x"]), float(player["y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (callable(near) and callable(find) and callable(project)):
            return None
        cache = self.lower_layer_cache
        key = (instance_id, round(x), round(y))
        if key in cache:
            return cache[key]
        points = [point for point in near(instance_id, {"x": x, "y": y}, self.LOWER_LAYER_RADIUS_YARDS)
                  if isinstance(point.get("z"), (int, float))]
        rim = [point["z"] for point in points
               if math.hypot(point["x"]-x, point["y"]-y) <= self.LOWER_LAYER_SURFACE_YARDS]
        result = None
        if rim:
            surface = max(rim)
            deep = sorted((point for point in points
                           if point["z"] <= surface - self.LOWER_LAYER_MIN_DROP_YARDS),
                          key=lambda point: (point["z"], math.hypot(point["x"]-x, point["y"]-y)))
            tracked = self._player_layer()
            hint = (tracked[3] if tracked is not None and tracked[0] == instance_id
                    and math.hypot(tracked[1]-px, tracked[2]-py) <= self._continuity_yards() else None)
            start = project(instance_id, {"x": px, "y": py, "instance_id": instance_id}, z_hint=hint)
            failed: list[dict] = []
            attempts = 0
            for point in deep:
                if start is None or attempts >= self.LOWER_LAYER_MAX_ROUTES:
                    break
                if any(math.dist((point["x"], point["y"], point["z"]),
                                 (other["x"], other["y"], other["z"])) <= 8. for other in failed):
                    continue      # same unreachable pocket (an isolated covered region)
                attempts += 1
                target = {"x": point["x"], "y": point["y"], "z": point["z"], "z_known": True,
                          "instance_id": instance_id}
                path = find(instance_id, start, target)
                end = path.anchors[-1] if path is not None and path.anchors else None
                if end is not None and math.dist(
                        (float(end["x"]), float(end["y"]), float(end.get("z", point["z"]))),
                        (point["x"], point["y"], point["z"])) <= 6.:
                    result = {"x": point["x"], "y": point["y"], "z": point["z"],
                              "z_known": True, "layer_z": point["z"],
                              "z_source": "NAVMESH_LOWER_LAYER",
                              "drop_yards": round(surface-point["z"], 1),
                              "route_yards": round(float(path.cost), 1)}
                    break
                failed.append(point)
        if len(cache) > 64:
            cache.clear()
        cache[key] = result
        return result
