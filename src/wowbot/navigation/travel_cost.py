"""Planning-only floor and travel-cost queries (REV4 NavigationService split).

Moved out of ``NavigationService`` (SRC_MELY_AUDIT 4.3: NavigationRecovery /
TravelCostQueryPort).  Every answer is a query: none plans a route, owns a
key or changes a navigation request.

* ``object_pull_step_safe`` -- one short backward plant-pull step stays on a
  confirmed, continuous floor,
* ``recovery_step_drops`` -- a stuck-recovery step direction would leave the
  floor for a drop,
* ``player_layer_z`` -- the Z resolver's current floor for the player,
* ``walk_cost`` -- the navmesh walking length to a candidate point (cached).

It reads the owner's current ZResolver and navmesh through providers (a
navigation reset replaces the resolver) and owns only the walk-cost cache.
"""
from __future__ import annotations

import math
import time

from wowbot.value_helpers import number


class TravelCostQueryPort:
    # Live 2026-10-13 17:57 (Hrun's pit spiral, at the fence): the stuck
    # recovery stepped ~4 yd backwards off the narrow walkway into the pit.
    RECOVERY_PROBE_YARDS = (1.5, 3., 4.5)
    RECOVERY_FLOOR_YARDS = 4.
    WALK_COST_CACHE_SECONDS = 15.

    def __init__(self, layers, navmesh) -> None:
        self._layers = layers                 # () -> the owner's current ZResolver
        self._navmesh = navmesh               # () -> the owner's navmesh
        self._walk_costs: dict = {}
        self.last_cost_geometry = None

    def object_pull_step_safe(self, state: dict) -> bool:
        """One short backward plant-pull step on a confirmed, continuous floor.

        Missing geometry is not permission to step off a ledge. This query
        plans no route, owns no keys and changes no navigation request.
        """
        from wowbot.agent.destination_distance import observed_height
        raw = state.get('player_world_position') or {}
        x, y, facing = number(raw.get('x')), number(raw.get('y')), number(state.get('orientation'))
        z = observed_height(raw)
        if (z is None and self._layers().player is not None and self._layers().player.confidence >= .6
                and str(self._layers().player.instance_id) == str(raw.get('instance_id'))):
            z = self._layers().player.z
        if (None in (x,y,z,facing) or raw.get('instance_id') is None or self._navmesh() is None
                or raw.get('coordinate_space') != 'WORLD_YARDS'):
            return False
        try:
            instance = int(raw['instance_id'])
            start = {'x':x,'y':y,'z':z,'z_known':True}
            for distance in (.35,.7,1.2):
                probe = {'x':x-math.cos(facing)*distance,'y':y-math.sin(facing)*distance,
                         'z':z,'z_known':True}
                # WorldGeometry's general surface projection may prefer the
                # terrain under a platform (real weed: 332 vs player 337).
                # A path explicitly constrained to our known floor must
                # actually reach each short backward probe on that floor.
                path = self._navmesh().find_path(instance,start,probe)
                anchors = path.anchors if path is not None else ()
                if (not anchors or any(abs(point['z']-z)>1.5 for point in anchors)
                        or math.hypot(anchors[-1]['x']-probe['x'],anchors[-1]['y']-probe['y'])>.4
                        or sum(math.hypot(b['x']-a['x'],b['y']-a['y'])
                               for a,b in zip(anchors,anchors[1:]))>distance+.6):
                    return False
            return True
        except (AttributeError,KeyError,TypeError,ValueError,OSError):
            return False

    def recovery_step_drops(self, state: dict, step: str) -> bool:
        """Would this recovery step's direction leave the player's floor
        for a drop (walkable surface only far below)?  A wall or a missing
        polygon (no surface at all) is no drop."""
        # Live 2026-10-13 18:08:52: stuck at the spiral's narrow point, the
        # running jump was clear straight ahead, but the arc carried the
        # character sideways over the edge to the pit bottom.  A jump needs
        # the whole front half clear.
        directions = {"BACKWARD": (math.pi,),
                      "JUMP_FORWARD": (0., math.pi/4, -math.pi/4, math.pi/2, -math.pi/2),
                      "STRAFE": (math.pi/2, -math.pi/2)}.get(str(step).upper())
        player = self._layers().player
        position = state.get("player_world_position") or {}
        facing = number(state.get("orientation"))
        px, py = number(position.get("x")), number(position.get("y"))
        if (directions is None or player is None or player.confidence < .6
                or facing is None or px is None or py is None):
            return False
        for offset in directions:
            angle = facing + offset
            for distance in self.RECOVERY_PROBE_YARDS:
                layers = self._layers()._layers_at(player.instance_id, px + math.cos(angle)*distance,
                                            py + math.sin(angle)*distance)
                if (layers and not any(abs(height-player.z) <= self.RECOVERY_FLOOR_YARDS for height in layers)
                        and min(layers) < player.z - self.RECOVERY_FLOOR_YARDS):
                    return True
        return False

    def player_layer_z(self, state: dict) -> float | None:
        """The Z resolver's current floor for the player (planning only).

        Live 2026-10-14 13:33:20 (Who Lurks in the Pit): Retail exports no
        player height (``z_known: False``), so the TDB spawn choice ranked
        the cocoons by x/y alone and sent the agent from the rim (z 95) to
        the pit bottom (z -5.9) first -- 0.3 yd nearer in 2D than the top
        cocoon (z 60).  The resolver had the rim height all along.
        """
        position = state.get("player_world_position") or {}
        try:
            instance_id, x, y = int(position["instance_id"]), float(position["x"]), float(position["y"])
        except (KeyError, TypeError, ValueError):
            return None
        now = number(state.get("monotonic_time"))
        last = self._layers().player
        if last is not None and last.at is not None:
            # The resolver stamps samples with the runtime clock; the
            # state's addon sample time is often a little older (live
            # 2026-10-14 20:15:59: -0.2 s made the rim height "stale" and
            # the pit bottom was chosen again).
            now = last.at if now is None else max(now, last.at)
        player = self._layers().current_player(instance_id, x, y, now if now is not None else 0.)
        if player is None or player.confidence < .4:
            return None
        return float(player.z)

    # User 2026-10-20 ("csináld meg mind": PixelBuddy's FindPathBatch takes
    # the first reachable of several spawns).  Planning-only: the navmesh
    # walking length from the player to a candidate point, None when there is
    # no complete path (or no navmesh).  Cached per 4 yd of player movement.
    def walk_cost(self, state: dict, destination: dict) -> float | None:
        navmesh = self._navmesh()
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        dx, dy = number(destination.get("x")), number(destination.get("y"))
        instance = player.get("instance_id")
        if (navmesh is None or None in (px, py, dx, dy, instance)
                or str(destination.get("instance_id", instance)) != str(instance)
                or not callable(getattr(navmesh, "find_path", None))):
            return None
        dz = number(destination.get("z")) if destination.get("z_known") is not False else None
        pz = number(player.get("z")) if player.get("z_known", player.get("z") is not None) else None
        # The start height belongs to the key: live 2026-10-21 a ghost 35 yd
        # above the ground had no route; after descending it had one.
        key = (str(instance), round(px/4), round(py/4), None if pz is None else round(pz/4),
               round(dx, 1), round(dy, 1), None if dz is None else round(dz, 1))
        cache = self._walk_costs
        at = time.monotonic()
        if key in cache and at - cache[key][0] < self.WALK_COST_CACHE_SECONDS:
            return cache[key][1]
        flags = ("z_estimated", "z_observed", "z_source")
        start = {"x": px, "y": py, "z": number(player.get("z")) or 0.,
                 "z_known": player.get("z_known", player.get("z") is not None),
                 **{flag: player[flag] for flag in flags if flag in player}}
        end = {"x": dx, "y": dy, **({"z": dz, "z_known": True} if dz is not None else {"z_known": False}),
               **{flag: destination[flag] for flag in flags if flag in destination}}
        try:
            from wowbot.geometry_contracts import query_path
            result = query_path(navmesh, int(instance), start, end)
            self.last_cost_geometry = result.diagnostic()
            path = result.value if result.ready else None
        except Exception:                 # a planning query never stops the agent
            path = None
        cost = float(path.cost) if path is not None and getattr(path, "anchors", None) else None
        if len(cache) > 512:
            cache.clear()
        cache[key] = (at, cost)
        return cost
