"""Observed ledge falls as route hazards (REV4 NavigationService split).

Moved out of ``NavigationService`` (SRC_MELY_AUDIT 4.3, HazardAwareRouteValidator
family: "drop/fall safe passage ne vesszen el"). A real fall from a route is
remembered at the *upper route* height, scoped by floor and instance, for ten
minutes; a later ground route through that point on that floor is refused.
The player still standing at the "ledge" on its floor proves it was no drop
(live 2026-10-11 15:15). The owner decides which height a fall is booked at.
"""
from __future__ import annotations

import math

from wowbot.value_helpers import number


class FallHazardMemory:
    # The observed drop can already be several yards beyond the planned
    # centerline (live 2026-10-08: ~4.7 yd). Quarantine the approach segment,
    # not just the exact landing pixel.
    FALL_HAZARD_RADIUS_YARDS = 8.
    FALL_HAZARD_LAYER_YARDS = 6.
    FALL_HAZARD_TTL_SECONDS = 600.

    def __init__(self) -> None:
        self.items: list[dict[str, float | int | None]] = []

    def _expire(self, now: float) -> None:
        self.items[:] = [item for item in self.items if item["expires_at"] > now]

    def remember(self, x: float, y: float, z: float | None, instance: int, now: float) -> None:
        self._expire(now)
        if any(item["instance_id"] == instance
               and math.hypot(float(item["x"])-x, float(item["y"])-y) < 2.
               and (item["z"] is None or z is None or abs(float(item["z"])-z) < 6.)
               for item in self.items):
            return
        self.items.append({"x": x, "y": y, "z": z, "instance_id": instance,
                           "expires_at": now + self.FALL_HAZARD_TTL_SECONDS})

    def blocks(self, route, instance: int, px: float | None, py: float | None,
               player_z: float | None, now: float) -> bool:
        if len(route.anchors) < 2 or not self.items or route.anchors[-1].get("flight_plan"):
            return False
        self._expire(now)
        for hazard in self.items:
            if hazard["instance_id"] != instance:
                continue
            if (px is not None and py is not None
                    and math.hypot(float(hazard["x"])-px, float(hazard["y"])-py)
                    < self.FALL_HAZARD_RADIUS_YARDS
                    and (player_z is None or hazard["z"] is None
                         or abs(player_z-float(hazard["z"])) < self.FALL_HAZARD_LAYER_YARDS)):
                # Live 2026-10-11 15:15: the player still stands at the
                # "ledge" on its floor -- it was no drop.  Blocking every
                # route that starts here left the agent waiting; a real fall
                # put the player on a lower floor, where this is skipped.
                continue
            for left, right in zip(route.anchors, route.anchors[1:]):
                ax, ay = float(left["x"]), float(left["y"])
                dx, dy = float(right["x"])-ax, float(right["y"])-ay
                length_sq = dx*dx + dy*dy
                t = (0. if length_sq <= 1e-9 else max(0., min(1.,
                     ((float(hazard["x"])-ax)*dx + (float(hazard["y"])-ay)*dy)/length_sq)))
                if math.hypot(ax+t*dx-float(hazard["x"]),
                              ay+t*dy-float(hazard["y"])) >= self.FALL_HAZARD_RADIUS_YARDS:
                    continue
                az, bz = number(left.get("z")), number(right.get("z"))
                route_z = az+t*(bz-az) if az is not None and bz is not None else None
                if (route_z is None or hazard["z"] is None
                        or abs(route_z-float(hazard["z"])) < self.FALL_HAZARD_LAYER_YARDS):
                    return True
        return False
