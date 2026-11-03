"""Own-layer and destination-height resolution (REV4 NavigationService split).

Moved out of ``NavigationService`` (SRC_MELY_AUDIT 4.3: LayerResolver /
DestinationZResolver).  It answers floor questions only:

* the active route's height where the player stands (the tie-breaker for the
  own-layer tracker),
* a new route's start state on the tracked own layer (never "observed"),
* whether a height-less search cell lies on the player's floor,
* the walkable, reachable layer for a destination without a height,
* whether a fresh server-observed own height contradicts the floor the route
  was planned on.

It reads the owner's current ZResolver through a provider (a navigation reset
replaces it) and owns only the observed-height watch.  Planning, failing a
MOVE and input stay with the service.
"""
from __future__ import annotations

from dataclasses import replace
import math

from wowbot.value_helpers import number


class DestinationLayerResolver:
    ROUTE_HINT_CORRIDOR_YARDS = 4.
    # Live 2026-10-28 10:53-10:54 (Obsidian Citadel, Left and Right): the
    # route was planned on a floor 10 yd below the observed z 387.6; the
    # walk spun 70 s around waypoint 2 (1.8 yd flat, 8.5 yd with the layer
    # excess).  Floors here are 7-12 yd apart.
    OBSERVED_LAYER_YARDS = 7.
    OBSERVED_LAYER_HORIZONTAL_YARDS = 6.
    OBSERVED_LAYER_SECONDS = 2.
    OBSERVED_Z_MAX_AGE = 2.
    SEARCH_CELL_FLOOR_YARDS = 15.
    SEARCH_CELL_DROP_YARDS = 20.

    def __init__(self, layers) -> None:
        self._layers = layers                 # () -> the owner's current ZResolver
        self.observed_own_z: tuple | None = None
        self.observed_layer_since: float | None = None

    def observed_layer(self, state: dict, destination: dict, skip: bool, immediate: bool,
                       now: float) -> str | None:
        """The server-observed own height is far from the waypoint we stand at.

        Live 2026-10-27 16:10:27-16:11:08 (Obsidian Citadel): the MOVE started
        while the player height was unknown and the route was planned on the
        courtyard floor (z 216).  The player stood on the wall top (own
        movement packets z 260); it ran back and forth 1-4 yd around waypoint
        1 for 40 s.  The final-waypoint check never ran (an intermediate
        waypoint), the navmesh-surface height followed the wrong floor, and
        the usable South Siege Arbalest (same wall level) was never chosen.
        A route from the wrong floor fails so the next plan starts from the
        observed height.

        ``CONTRADICTED`` fails the route; ``CONFIRMED`` means a fresh observed
        height agrees with the guessed floor.  ``immediate`` (a layer probe or a
        route planned before any observed height) skips the persistence wait."""
        player = state.get("player_world_position") or {}
        px, py, pz = number(player.get("x")), number(player.get("y")), number(player.get("z"))
        source = str(player.get("source") or player.get("z_source") or "")
        if pz is not None and (player.get("z_observed") is True or source.startswith("PACKET_CLIENT_MOVEMENT")):
            self.observed_own_z = (pz, px, py, now)
        if skip:
            self.observed_layer_since = None
            return None
        known = self.observed_own_z
        dx, dy = number(destination.get("x")), number(destination.get("y"))
        dz = number(destination.get("layer_z", destination.get("z")))
        if (known is None or None in (px, py, dx, dy, dz) or now-known[3] > self.OBSERVED_Z_MAX_AGE
                or known[1] is None or math.hypot(known[1]-px, known[2]-py) > self.OBSERVED_LAYER_HORIZONTAL_YARDS
                or math.hypot(dx-px, dy-py) > self.OBSERVED_LAYER_HORIZONTAL_YARDS
                or abs(known[0]-dz) <= self.OBSERVED_LAYER_YARDS):
            if (known is not None and dz is not None and 0 <= now-known[3] <= self.OBSERVED_Z_MAX_AGE
                    and abs(known[0]-dz) <= self.OBSERVED_LAYER_YARDS):
                self.observed_layer_since = None
                return "CONFIRMED"                               # the guessed floor was right
            self.observed_layer_since = None
            return None
        since = self.observed_layer_since
        if since is None:
            self.observed_layer_since = since = now
        # A layer probe walks only to learn the floor: the first server
        # height that contradicts it answers the question.
        # Live 2026-10-28 10:53: the route was planned 1.7 s before the
        # first own movement packet of a new runtime context; that first
        # server height already contradicts the guessed floor.
        if now-since < self.OBSERVED_LAYER_SECONDS and not immediate:
            return None
        self.observed_layer_since = None
        return "CONTRADICTED"

    def route_hint_z(self, route, state: dict) -> float | None:
        """The active route's height where the player stands on it.

        Live 2026-10-06 21:29: walking down the ramp from the entrance, the
        rim polygon overhangs the ramp; continuity kept the rim (93.5) while
        the player was at ~78, the waypoint below was "on another layer" and
        never passed, and the character turned back and forth for 30 s.
        The route the controller is following is the best tie-breaker."""
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        if route is None or not route.anchors or px is None or py is None:
            return None
        best = None
        anchors = [anchor for anchor in route.anchors if number(anchor.get("z")) is not None]
        for left, right in zip(anchors, anchors[1:]) if len(anchors) > 1 else ():
            ax, ay, az = float(left["x"]), float(left["y"]), float(left["z"])
            bx, by, bz = float(right["x"]), float(right["y"]), float(right["z"])
            vx, vy = bx-ax, by-ay
            length_sq = vx*vx + vy*vy
            t = 0. if length_sq <= 1e-9 else max(0., min(1., ((px-ax)*vx + (py-ay)*vy)/length_sq))
            distance = math.hypot(ax+t*vx-px, ay+t*vy-py)
            if best is None or distance < best[0]:
                best = (distance, az+t*(bz-az))
        if best is None and anchors:
            nearest = min(anchors, key=lambda anchor: (float(anchor["x"])-px)**2 + (float(anchor["y"])-py)**2)
            best = (math.hypot(float(nearest["x"])-px, float(nearest["y"])-py), float(nearest["z"]))
        return best[1] if best is not None and best[0] <= self.ROUTE_HINT_CORRIDOR_YARDS else None

    def with_layer_continuity(self, state: dict, now: float) -> dict:
        """A new route starts on the resolved own layer (an estimate, never observed)."""
        player = state.get("player_world_position") or {}
        if player.get("z_observed") is True and "z" in player:
            return state
        try:
            instance_id, x, y = int(player["instance_id"]), float(player["x"]), float(player["y"])
        except (KeyError, TypeError, ValueError):
            return state
        resolved = self._layers().current_player(instance_id, x, y, now)
        if resolved is None:
            return state
        return {**state, "player_world_position": {
            **player, "z": resolved.z, "z_known": True, "z_observed": False,
            "z_estimated": True, "z_source": "NAVMESH_LAYER_CONTINUITY",
            "z_confidence": round(resolved.confidence, 3), "layer_id": resolved.layer_id}}

    def search_cell_on_player_floor(self, waypoint: dict) -> bool:
        """Live 2026-10-06 21:16: a height-less quest-area cell resolved onto
        the rim and the agent ran up the spiral to the entrance and back.
        In a cave, a search cell is walked only on (about) the player's floor."""
        player = self._layers().player
        if (player is None or player.confidence < .6
                or waypoint.get("coordinate_space") != "WORLD_YARDS" or waypoint.get("z") is not None):
            return True
        x, y = number(waypoint.get("x")), number(waypoint.get("y"))
        if x is None or y is None:
            return True
        if self._layers()._indoors is not True:
            # Live 2026-10-13 05:56 (Hrun's pit rim): an outdoor sweep cell
            # over the pit had only the pit bottom (z -23) under it; the
            # route to it led round the rim and off the edge into the cave.
            # Outdoors a cell is skipped only when every walkable surface
            # there lies far below the player (uphill cells stay).
            layers = self._layers()._layers_at(player.instance_id, x, y)
            return not layers or max(layers) >= player.z - self.SEARCH_CELL_DROP_YARDS
        target = self._layers().resolve_target(player.instance_id, x, y, player=player, floor_hint="SAME")
        self._layers().last_target = None
        return target is not None and abs(target.z-player.z) <= self.SEARCH_CELL_FLOOR_YARDS

    def resolve_destination_z(self, request, state: dict, now: float):
        destination = dict(request.destination)
        if destination.get("hover_point"):
            # This is an explicit point in the air, not a missing ground
            # height. Snapping it onto a floor also displaced its XY.
            return request
        origin = destination.get("z_resolved_from")
        if destination.get("coordinate_space") != "WORLD_YARDS":
            return request
        if not origin and number(destination.get("z")) is not None and destination.get("z_known") is not False:
            return request
        player = state.get("player_world_position") or {}
        try:
            instance_id = int(destination.get("instance_id", player.get("instance_id")))
            x, y = ((float(origin["x"]), float(origin["y"])) if origin
                    else (float(destination["x"]), float(destination["y"])))
            px, py = float(player["x"]), float(player["y"])
        except (KeyError, TypeError, ValueError):
            return request
        resolved_player = self._layers().current_player(instance_id, px, py, now)
        hint = destination.get("floor_hint") or {"LOWER": "BELOW", "UPPER": "ABOVE"}.get(
            str(destination.get("destination_layer") or ""))
        target = self._layers().resolve_target(instance_id, x, y, player=resolved_player, floor_hint=hint)
        if target is None:
            if hint in {"SAME", "ABOVE", "BELOW"}:
                destination["z_resolution_failed"] = (self._layers().last_target_failure
                                                       or "no_reachable_target_layer")
                return replace(request, destination=destination)
            return request
        moved = math.hypot(target.x-x, target.y-y) > self._layers().LAYER_RADIUS
        destination.update({
            "x": target.x if moved else x, "y": target.y if moved else y, "z": target.z,
            "z_known": True, "z_observed": False, "z_estimated": True,
            "z_source": f"Z_RESOLVER_{target.source}", "z_confidence": round(target.confidence, 3),
            "layer_id": getattr(target, "layer_id", None),
            "z_resolved_from": {"x": x, "y": y}, "z_alternatives": list(target.alternatives)[:6]})
        destination.pop("z_resolution_failed", None)
        return replace(request, destination=destination)
