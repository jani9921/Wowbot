"""Hazard-aware shaping of a planned ground route (REV4 NavigationService split).

Moved out of ``NavigationService`` (SRC_MELY_AUDIT 4.3: HazardAwareRouteValidator,
"drop/fall safe passage ne vesszen el"). It keeps route corners off real drops
and in the middle of the walkable corridor, re-checks every moved point against
the surface and removes reversal spikes. It owns no route, request or input:
the service passes the planned route and keeps route/waypoint ownership.
"""
from __future__ import annotations

from dataclasses import replace
import math

from wowbot.value_helpers import number


class HazardAwareRouteValidator:
    """Geometry over the owner's current layers/navmesh (both are replaced
    on a navigation reset, so they are read through providers)."""

    def __init__(self, layers, navmesh) -> None:
        self._layers, self._navmesh = layers, navmesh
        # Centred points the character got stuck at (bounded); see
        # NavigationService._note_offset_stuck. Survives a navigation reset,
        # as the former service attribute did.
        self.offset_stuck: list[tuple[float, float, float]] = []

    def note_offset_stuck(self, x: float, y: float, z: float) -> None:
        self.offset_stuck.append((x, y, z))
        del self.offset_stuck[:-16]

    # Live 2026-10-13 17:44-17:57 (Hrun's pit, user screenshots): the spiral
    # walkway is ~50 yd wide between the fence at the drop and the cave wall,
    # yet the shortest route hugged the fence; steering drift and a running
    # jump at the fence threw the character into the pit three times.  Keep
    # route corners off a real drop (all surfaces far below) where the
    # walkway allows it.
    DROP_KEEP_YARDS = 10.
    DROP_PROBE_RADII = (2., 4., 6., 8., 10.)
    DROP_DIRECTIONS = 16
    DROP_DEPTH_YARDS = 6.

    def _drop_side(self, instance_id: int, x: float, y: float, z: float):
        """(nearest drop distance, unit vector toward it) or None."""
        for radius in self.DROP_PROBE_RADII:
            vx = vy = 0.
            for k in range(self.DROP_DIRECTIONS):
                angle = math.tau * k / self.DROP_DIRECTIONS
                layers = self._layers()._layers_at(instance_id, x + math.cos(angle)*radius, y + math.sin(angle)*radius)
                if (layers and not any(abs(h-z) <= .8*radius+2. for h in layers)
                        and min(layers) < z - self.DROP_DEPTH_YARDS):
                    vx, vy = vx + math.cos(angle), vy + math.sin(angle)
            norm = math.hypot(vx, vy)
            if norm > 1e-6:
                return radius, (vx/norm, vy/norm)
        return None

    def _walkable_near(self, instance_id: int, x: float, y: float, z: float, shift: float) -> float | None:
        # A gentle slope only: a spiral's next turn above/below is no target.
        layers = self._layers()._layers_at(instance_id, x, y)
        near = [h for h in layers if abs(h-z) <= .4*shift+1.5]
        return min(near, key=lambda h: abs(h-z)) if near else None

    # User 2026-10-13: "it need not take the shortest way; a bit further in
    # is longer but it does not fall".  Long chords along the fence are
    # split so that their middle is kept off the drop too.
    DROP_DENSIFY_YARDS = 4.

    def _densified(self, anchors: list) -> list:
        result = [anchors[0]]
        for left, right in zip(anchors, anchors[1:]):
            try:
                ax, ay, az = float(left["x"]), float(left["y"]), float(left["z"])
                bx, by, bz = float(right["x"]), float(right["y"]), float(right["z"])
            except (KeyError, TypeError, ValueError):
                result.append(right)
                continue
            parts = int(math.hypot(bx-ax, by-ay) // self.DROP_DENSIFY_YARDS)
            for k in range(1, parts):
                t = k / parts
                result.append({**left, "x": ax+(bx-ax)*t, "y": ay+(by-ay)*t, "z": az+(bz-az)*t,
                               "drop_densified": True})
            result.append(right)
        return result

    # User 2026-10-14 21:05: "on the walkable navmesh it should rather go in
    # the middle, not the shortest way -- it keeps walking at the edge".
    # The shortest path hugs both edges: the fence over the drop (falls,
    # 10-13) and the cave wall (wall-running, 10-14 21:02: every stuck point
    # was a drop-only offset pushed toward the wall).  Each route point moves
    # to the middle of the walkable corridor across the path: both sides are
    # probed, and where no surface is at this height there is a wall or a
    # drop.  In an open area it only keeps CENTER_KEEP_YARDS from the edge.
    CENTER_PROBE_STEP_YARDS = 1.5
    CENTER_PROBE_MAX_YARDS = 15.
    CENTER_KEEP_YARDS = 6.
    CENTER_MAX_SHIFT_YARDS = 8.
    CENTER_MIN_SHIFT_YARDS = .75
    CENTER_SEGMENT_STEP_YARDS = .75
    CENTER_SEGMENT_HEIGHT_YARDS = 2.5
    SIMPLIFY_DEVIATION_YARDS = 1.5
    OFFSET_STUCK_YARDS = 20.

    def _edge_distance(self, instance_id: int, x: float, y: float, z: float,
                       nx: float, ny: float) -> float | None:
        """Yards to the corridor edge in direction (nx, ny); None: open."""
        step = self.CENTER_PROBE_STEP_YARDS
        distance = step
        while distance <= self.CENTER_PROBE_MAX_YARDS + 1e-9:
            layers = self._layers()._layers_at(instance_id, x+nx*distance, y+ny*distance)
            tolerance = min(4., 1.5 + .3*distance)
            if not any(abs(height-z) <= tolerance for height in layers):
                return distance - step/2
            distance += step
        return None

    def segment_walkable(self, instance_id: int, a: tuple, b: tuple) -> bool:
        """A surface at the segment's height along its whole centre line."""
        (x0, y0, z0), (x1, y1, z1) = a, b
        horizontal = math.hypot(x1-x0, y1-y0)
        max_slope = number(getattr(getattr(self._navmesh(), "navmesh", self._navmesh()),
                                   "max_walkable_slope_degrees", None))
        if (max_slope is not None and abs(z1-z0) > .6
                and abs(z1-z0) > horizontal * math.tan(math.radians(max_slope)) + 1e-4):
            return False
        steps = max(1, int(horizontal / self.CENTER_SEGMENT_STEP_YARDS))
        for k in range(steps+1):
            t = k/steps
            layers = self._layers()._layers_at(instance_id, x0+(x1-x0)*t, y0+(y1-y0)*t)
            if not any(abs(height-(z0+(z1-z0)*t)) <= self.CENTER_SEGMENT_HEIGHT_YARDS for height in layers):
                return False
        return True

    def _near_offset_stuck(self, x: float, y: float, z: float) -> bool:
        return any(math.hypot(x-sx, y-sy) <= self.OFFSET_STUCK_YARDS and abs(z-sz) <= 8.
                   for sx, sy, sz in self.offset_stuck)

    @staticmethod
    def xyz(anchor: dict) -> tuple:
        return float(anchor["x"]), float(anchor["y"]), float(anchor["z"])

    def center(self, route, fallback=None):
        """Keep the route in the middle of the walkable corridor (see above).

        ``fallback``: the request's instance for anchors without one."""
        anchors = list(getattr(route, "anchors", None) or ())
        if (len(anchors) < 2 or anchors[-1].get("flight_plan")
                or not callable(getattr(self._layers().geometry, "walkable_heights_at", None))):
            return route
        anchors = self._densified(anchors)
        if len(anchors) < 3:
            return route
        result = [anchors[0]]
        for index in range(1, len(anchors)-1):
            anchor = anchors[index]
            try:
                x, y, z = self.xyz(anchor)
                instance_id = int(anchor.get("instance_id") or fallback)
                px, py, _ = self.xyz(anchors[index-1])
                qx, qy, _ = self.xyz(anchors[index+1])
            except (KeyError, TypeError, ValueError):
                result.append(anchor)
                continue
            keep = None if anchor.get("drop_densified") else anchor
            length = math.hypot(qx-px, qy-py)
            if length <= 1e-6 or self._near_offset_stuck(x, y, z):
                if keep is not None:
                    result.append(keep)
                continue
            lx, ly = -(qy-py)/length, (qx-px)/length          # left of the travel direction
            left = self._edge_distance(instance_id, x, y, z, lx, ly)
            right = self._edge_distance(instance_id, x, y, z, -lx, -ly)
            if left is None and right is None:
                shift = 0.
            elif left is None:
                shift = max(0., self.CENTER_KEEP_YARDS - right)
            elif right is None:
                shift = -max(0., self.CENTER_KEEP_YARDS - left)
            else:
                shift = (left - right) / 2.
            shift = max(-self.CENTER_MAX_SHIFT_YARDS, min(self.CENTER_MAX_SHIFT_YARDS, shift))
            nx, ny = x + lx*shift, y + ly*shift
            nz = (self._walkable_near(instance_id, nx, ny, z, abs(shift))
                  if abs(shift) >= self.CENTER_MIN_SHIFT_YARDS else None)
            if nz is None or not self.segment_walkable(instance_id, (x, y, z), (nx, ny, nz)):
                if keep is not None:
                    result.append(keep)
                continue
            result.append({**anchor, "x": nx, "y": ny, "z": nz, "drop_offset": True,
                           "drop_original": anchor})
        result.append(anchors[-1])
        result = self._walkable_offsets(result, fallback)
        result = self.without_drop_spikes(result)
        result = self._simplified(result, fallback)
        if (not any(anchor.get("drop_offset") for anchor in result)
                and len(result) == len(route.anchors)):
            return route
        return replace(route, anchors=tuple(result))

    def _walkable_offsets(self, anchors: list, fallback) -> list:
        """A moved point whose leg to a neighbour leaves the surface goes back."""
        anchors = list(anchors)
        for _ in range(len(anchors)):
            bad = None
            for i in range(1, len(anchors)-1):
                if not anchors[i].get("drop_offset"):
                    continue
                try:
                    instance_id = int(anchors[i].get("instance_id") or fallback)
                    here = self.xyz(anchors[i])
                    if not (self.segment_walkable(instance_id, self.xyz(anchors[i-1]), here)
                            and self.segment_walkable(instance_id, here, self.xyz(anchors[i+1]))):
                        bad = i
                        break
                except (KeyError, TypeError, ValueError):
                    continue
            if bad is None:
                break
            original = anchors[bad]["drop_original"]
            if original.get("drop_densified"):
                del anchors[bad]
            else:
                anchors[bad] = original
        return anchors

    def _simplified(self, anchors: list, fallback) -> list:
        """Drop points a walkable straight chord passes within 1.5 yd of
        (fewer waypoints: less stopping and turning on the way)."""
        if len(anchors) < 3:
            return anchors
        result, i = [anchors[0]], 0
        while i < len(anchors)-1:
            j = i+1
            while j+1 < len(anchors):
                try:
                    instance_id = int(anchors[i].get("instance_id") or fallback)
                    a, b = self.xyz(anchors[i]), self.xyz(anchors[j+1])
                except (KeyError, TypeError, ValueError):
                    break
                length = math.hypot(b[0]-a[0], b[1]-a[1])
                if length <= 1e-6:
                    break
                deviation = max(abs((b[0]-a[0])*(a[1]-float(p["y"])) - (a[0]-float(p["x"]))*(b[1]-a[1])) / length
                                for p in anchors[i+1:j+1])
                if deviation > self.SIMPLIFY_DEVIATION_YARDS or not self.segment_walkable(instance_id, a, b):
                    break
                j += 1
            result.append(anchors[j])
            i = j
        return result

    # Live 2026-10-14 13:35:56-13:36:25 (Hrun's pit): at a tight bend one
    # corner was shifted 6 yd back against the travel direction; the route
    # ran 70,-2240 -> 73.6,-2235 -> 70.9,-2241 and the character turned in
    # place and walked back and forth.  A shift that makes the route reverse
    # at that corner or its neighbours goes back to the navmesh corner.
    DROP_SPIKE_TURN_DEGREES = 110.

    def without_drop_spikes(self, anchors: list) -> list:
        def turn(left, middle, right) -> float:
            ax, ay = float(middle["x"])-float(left["x"]), float(middle["y"])-float(left["y"])
            bx, by = float(right["x"])-float(middle["x"]), float(right["y"])-float(middle["y"])
            norm = math.hypot(ax, ay) * math.hypot(bx, by)
            if norm <= 1e-9:
                return 0.
            return math.degrees(math.acos(max(-1., min(1., (ax*bx + ay*by) / norm))))

        anchors = list(anchors)
        for _ in range(len(anchors)):
            spike = None
            for i in range(1, len(anchors)-1):
                if not anchors[i].get("drop_offset"):
                    continue
                corners = [k for k in (i-1, i, i+1) if 0 < k < len(anchors)-1]
                if any(turn(anchors[k-1], anchors[k], anchors[k+1]) > self.DROP_SPIKE_TURN_DEGREES
                       for k in corners):
                    spike = i
                    break
            if spike is None:
                break
            original = anchors[spike]["drop_original"]
            if original.get("drop_densified"):
                del anchors[spike]              # a split point is not needed unshifted
            else:
                anchors[spike] = original
        return [{key: value for key, value in anchor.items() if key != "drop_original"}
                for anchor in anchors]
