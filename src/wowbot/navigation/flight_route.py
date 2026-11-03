"""Straight-line flight plans over MAPS terrain and VMAPS models (Steady Flight).

User 2026-10-25: "first plain riding in the air, then vehicles in the air".
A flying mount has no walking route.  The plan is a straight line from the
player to a landing point on the navmesh next to the destination, with the
highest ground under a corridor around it sampled from the TrinityCore MAPS
terrain and the VMAPS collision models (buildings, trees, rocks).  The
movement controller follows it: it climbs to ``clearance`` above the highest
ground of the stretch ahead, cruises, and descends onto the landing point.

Pure geometry: no input, no client state.  Unknown ground (no MAPS tile, no
VMAPS answer) is not assumed flat; such a sample makes the plan fail closed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math

SAMPLE_YARDS = 8.            # along the line
CORRIDOR_YARDS = 6.          # each side of the line
CLEARANCE_YARDS = 12.        # above the highest ground ahead
LOOKAHEAD_YARDS = 60.        # the stretch whose ground sets the target height
DESCENT_YARDS = 45.          # horizontal distance of the final descent
LANDING_SEARCH_YARDS = 12.   # navmesh landing point around the destination
MAX_SAMPLES = 160            # ~1280 yd of line; longer trips are re-planned on the way
MIN_FLIGHT_YARDS = 40.
COVER_YARDS = 3.             # a surface this far above the landing point covers it


@dataclass(frozen=True)
class FlightPlan:
    instance_id: int
    start: dict
    landing: dict
    distance: float
    # (yards along the line, highest ground there)
    profile: tuple[tuple[float, float], ...] = field(default_factory=tuple)
    clearance: float = CLEARANCE_YARDS
    lookahead: float = LOOKAHEAD_YARDS
    descent: float = DESCENT_YARDS
    truncated: bool = False
    # Optional horizontal bends supplied by the shared lateral A* planner.
    # The landing is the final point; these are ordered intermediate corners.
    waypoints: tuple[dict, ...] = field(default_factory=tuple)
    cruise_z: float | None = None

    def horizontal_points(self) -> tuple[dict, ...]:
        return (self.start, *self.waypoints, self.landing)

    def point_at(self, along: float) -> dict:
        remaining = max(0., along)
        for left, right in zip(self.horizontal_points(), self.horizontal_points()[1:]):
            length = math.hypot(right['x']-left['x'], right['y']-left['y'])
            if length > 1e-6 and remaining <= length:
                fraction = remaining/length
                return {key: float(left[key])+(float(right[key])-float(left[key]))*fraction
                        for key in ('x', 'y')}
            remaining -= length
        return {key: float(self.landing[key]) for key in ('x', 'y')}

    def ground_ahead(self, along: float) -> float:
        """Highest ground between ``along`` and ``along + lookahead``."""
        ahead = [z for at, z in self.profile if along - SAMPLE_YARDS <= at <= along + self.lookahead]
        return max(ahead) if ahead else max(z for _at, z in self.profile)

    def target_z(self, along: float) -> float:
        """Height to hold ``along`` yards from the start.

        Cruise ``clearance`` above the ground ahead; inside the final descent
        the height falls linearly to the landing point, never below the
        ground ahead plus a small margin until right above the landing."""
        cruise = self.ground_ahead(along) + self.clearance
        if self.cruise_z is not None:
            cruise = max(cruise, self.cruise_z)
        remaining = self.distance - along
        if not self.truncated and remaining < self.descent + self.lookahead:
            # Live 2026-10-27 16:41 (East Siege Arbalest on a bridge, deck
            # z 247): 70 yd out the ground ahead was the gorge under the
            # bridge (204), the approach came in at ~216 and touched down
            # under the deck.  Approach a raised landing from above it.
            cruise = max(cruise, float(self.landing["z"]) + self.clearance)
        if remaining >= self.descent or self.truncated:
            return cruise          # a truncated plan ends in the air: the next one continues
        landing_z = float(self.landing["z"])
        fraction = max(0., remaining) / self.descent
        glide = landing_z + (cruise - landing_z) * fraction
        floor = self.ground_ahead(along) + (2. if remaining > 6. else 0.)
        return max(glide, min(floor, cruise))

    def along(self, x: float, y: float) -> float:
        """Projection of a point onto the line, in yards from the start."""
        if self.waypoints:
            best, total = None, 0.
            points = self.horizontal_points()
            for left, right in zip(points, points[1:]):
                dx, dy = right['x']-left['x'], right['y']-left['y']
                length = math.hypot(dx, dy)
                fraction = max(0., min(1., ((x-left['x'])*dx+(y-left['y'])*dy)/max(1e-9, length*length)))
                gap = math.hypot(x-left['x']-fraction*dx, y-left['y']-fraction*dy)
                if best is None or gap < best[0]:
                    best = (gap, total+fraction*length)
                total += length
            return best[1] if best is not None else 0.
        sx, sy = float(self.start["x"]), float(self.start["y"])
        lx, ly = float(self.landing["x"]) - sx, float(self.landing["y"]) - sy
        length = math.hypot(lx, ly)
        if length <= 1e-6:
            return 0.
        return max(0., min(length, ((x-sx)*lx + (y-sy)*ly) / length))

    def to_dict(self) -> dict:
        value = asdict(self)
        value["profile"] = [list(row) for row in self.profile]
        return value

    @classmethod
    def from_dict(cls, value: dict) -> "FlightPlan":
        return cls(int(value["instance_id"]), dict(value["start"]), dict(value["landing"]),
                   float(value["distance"]), tuple((float(a), float(z)) for a, z in value["profile"]),
                   float(value.get("clearance", CLEARANCE_YARDS)), float(value.get("lookahead", LOOKAHEAD_YARDS)),
                   float(value.get("descent", DESCENT_YARDS)), bool(value.get("truncated", False)),
                   tuple(dict(point) for point in value.get('waypoints') or ()),
                   float(value['cruise_z']) if value.get('cruise_z') is not None else None)


SKYRIDING_LEG_YARDS = 160.       # a waypoint every this far along the line
SKYRIDING_EXTRA_YARDS = 20.      # above the Steady cruise height: room to dive for speed
SKYRIDING_PASS_YARDS = 15.       # a travel waypoint is passed this close, or once crossed
SKYRIDING_APPROACH_YARDS = 90.   # the final glide onto the landing starts this far before it
SKYRIDING_DESCENT_CLEARANCE = 4.


SKYRIDING_OFF_MESH_LANDING_YARDS = 6.   # a touchdown this close to an off-mesh landing arrives


def skyriding_path(plan: FlightPlan) -> dict:
    """The same terrain plan as a Skyriding FlightPath (user 2026-10-25: fly
    from one quest to the next this way too, not only through lesson rings).

    Each waypoint holds the highest Steady target height of its leg plus
    SKYRIDING_EXTRA_YARDS.  The last one starts a straight glide onto the
    navmesh landing point, raised until that glide clears every terrain sample
    under it.  The waypoints are geometric (no checkpoint signal); a
    truncated plan ends in the air (``end_in_air``)."""
    sx, sy = float(plan.start["x"]), float(plan.start["y"])
    landing = {k: float(plan.landing[k]) for k in ("x", "y", "z")}
    distance = plan.distance
    ux, uy = ((landing["x"]-sx)/distance, (landing["y"]-sy)/distance) if distance > 1e-3 else (0., 0.)
    cruise_end = distance if plan.truncated else max(0., distance - SKYRIDING_APPROACH_YARDS)
    bend_stops, total = [], 0.
    points = plan.horizontal_points()
    for index, (left, right) in enumerate(zip(points, points[1:])):
        total += math.hypot(right['x']-left['x'], right['y']-left['y'])
        if index < len(plan.waypoints):
            bend_stops.append(total)
    if bend_stops and not plan.truncated:
        cruise_end = max(cruise_end, bend_stops[-1])
    stops = []
    along = SKYRIDING_LEG_YARDS
    while along < cruise_end - SKYRIDING_LEG_YARDS/3:
        stops.append(along)
        along += SKYRIDING_LEG_YARDS
    if cruise_end > 0 and not plan.truncated:
        stops.append(cruise_end)
    stops = sorted(set([*stops, *bend_stops]))
    waypoints, previous = [], 0.
    for stop in stops:
        heights = [plan.target_z(at) for at, _z in plan.profile if previous < at <= stop] or [plan.target_z(stop)]
        waypoints.append({**plan.point_at(stop), "z": max(heights) + SKYRIDING_EXTRA_YARDS})
        previous = stop
    if waypoints and not plan.truncated:
        # The final glide is a straight line: lift its start until no ground
        # sample under it comes closer than the clearance.
        start_z = waypoints[-1]["z"]
        span = distance - cruise_end
        for at, ground in plan.profile:
            fraction = (at - cruise_end) / span if span > 1e-3 else 1.
            if 0 < fraction < .9:
                needed = (ground + SKYRIDING_DESCENT_CLEARANCE - landing["z"]*fraction) / (1. - fraction)
                start_z = max(start_z, needed)
        waypoints[-1]["z"] = start_z
    if plan.truncated:
        landing["z"] = max(landing["z"], plan.target_z(distance) + SKYRIDING_EXTRA_YARDS)
    return {"instance_id": int(plan.instance_id), "mode": "SKYRIDING", "waypoints": waypoints,
            "landing": landing, "checkpoint_conditions": [None]*len(waypoints),
            "radius": SKYRIDING_PASS_YARDS, "end_in_air": bool(plan.truncated),
            "landing_on_navmesh": plan.landing.get("navmesh", True) is not False,
            **({"landing_radius": SKYRIDING_OFF_MESH_LANDING_YARDS}
               if plan.landing.get("navmesh", True) is False else {})}


def ground_height(geometry, instance_id: int, x: float, y: float) -> float | None:
    """Highest known collision surface at one X/Y: MAPS terrain or a VMAPS model."""
    heights = []
    terrain, hole = geometry.terrain_height(instance_id, x, y)
    if terrain is not None and not hole:
        heights.append(float(terrain))
    surfaces = geometry.vmap_surfaces_at(instance_id, {"x": x, "y": y})
    if surfaces:
        heights.append(float(max(surfaces)))
    return max(heights) if heights else None


LAYER_MATCH_YARDS = 2.5      # a navmesh point this close in height is the destination's layer
LANDING_WIDE_YARDS = 40.     # ... and an open spot on its layer this far out
LAYER_WIDE_YARDS = 6.


def landing_candidates(geometry, instance_id: int, destination: dict) -> list[dict]:
    """Landing points at the destination, best first.

    A destination with a known height lands on that layer.  Live 2026-10-25
    21:23 (Lord Andestrasz, server z 363.2 on the Skytop dome): the projection
    without that height chose the rock under the dome (359.8), the dome became
    a "cover" and no flight was planned at all.  Without a height the
    projection comes first, then every walkable layer nearby (a covered one is
    skipped by ``plan_flight``).  A known height with no navmesh point on its
    layer lands on the destination itself (``navmesh`` False): touching down
    there is the arrival, no walking leg follows."""
    z = destination.get("z")
    known = type(z) in {int, float} and math.isfinite(z) and destination.get("z_known") is not False
    result = []
    projected = geometry.project_position(instance_id, {"x": destination["x"], "y": destination["y"],
                                                         **({"z": z} if known else {})})
    if (projected is not None and projected.get("z") is not None
            and (not known or abs(float(projected["z"]) - z) <= LAYER_MATCH_YARDS)):
        result.append({"x": float(projected["x"]), "y": float(projected["y"]), "z": float(projected["z"])})
    near = geometry.walkable_points_near(instance_id, destination, LANDING_SEARCH_YARDS)
    if known:
        near = [point for point in near if abs(float(point["z"]) - z) <= LAYER_MATCH_YARDS]
    near.sort(key=lambda point: math.hypot(point["x"]-destination["x"], point["y"]-destination["y"]))
    result.extend({"x": float(p["x"]), "y": float(p["y"]), "z": float(p["z"])} for p in near)
    if known:
        # Live 2026-10-26 17:22-17:34 (the Proto-Fight turn-in, z 95 under a
        # platform at z 183-188): every point within LANDING_SEARCH_YARDS was
        # covered, no flight was planned and the agent stood on the platform.
        # Farther out on the same layer: an open spot to land on and walk
        # in from (there: 23 yd away, with a navmesh path to the point).
        wide = [point for point in geometry.walkable_points_near(instance_id, destination, LANDING_WIDE_YARDS)
                if abs(float(point["z"]) - z) <= LAYER_WIDE_YARDS
                and math.hypot(point["x"]-destination["x"], point["y"]-destination["y"]) > LANDING_SEARCH_YARDS]
        wide.sort(key=lambda point: math.hypot(point["x"]-destination["x"], point["y"]-destination["y"]))
        result.extend({"x": float(p["x"]), "y": float(p["y"]), "z": float(p["z"])} for p in wide)
    if known and not result:
        result.append({"x": float(destination["x"]), "y": float(destination["y"]), "z": float(z), "navmesh": False})
    return result


def landing_point(geometry, instance_id: int, destination: dict) -> dict | None:
    """The best landing candidate (see ``landing_candidates``)."""
    candidates = landing_candidates(geometry, instance_id, destination)
    return candidates[0] if candidates else None


def covered(geometry, instance_id: int, point: dict) -> bool:
    """A surface above (a roof, a cave ceiling, a hillside): reached on foot."""
    terrain, _hole = geometry.terrain_height(instance_id, point["x"], point["y"])
    roofs = [height for height in geometry.vmap_surfaces_at(instance_id, point) if height > point["z"] + COVER_YARDS]
    return bool(roofs) or (terrain is not None and terrain > point["z"] + COVER_YARDS)


def plan_flight(geometry, instance_id: int, start: dict, destination: dict, *,
                clearance: float = CLEARANCE_YARDS,
                min_distance: float | None = None) -> tuple[FlightPlan | None, str]:
    """(plan, reason).  ``None`` with a reason when flying there is not planned.

    ``min_distance``: shorter trips walk (default ``MIN_FLIGHT_YARDS``); an
    airborne character passes 0 -- it has to land however short the way."""
    if geometry is None or not geometry.supports(instance_id):
        return None, "no_world_geometry"
    try:
        sx, sy = float(start["x"]), float(start["y"])
    except (KeyError, TypeError, ValueError):
        return None, "no_start"
    candidates = landing_candidates(geometry, instance_id, destination)
    if not candidates:
        return None, "no_landing_point"
    # A landing point under terrain (a cave) or under a roof is reached on
    # foot: the vertical descent would end on the roof or in the hillside.
    landing = next((point for point in candidates if not covered(geometry, instance_id, point)), None)
    if landing is None:
        return None, "landing_under_cover"
    dx, dy = landing["x"]-sx, landing["y"]-sy
    distance = math.hypot(dx, dy)
    if distance < (MIN_FLIGHT_YARDS if min_distance is None else min_distance):
        return None, "too_short"
    if distance < 1e-3:
        # Already above the landing point: a plan of one sample, straight down.
        ground = ground_height(geometry, instance_id, sx, sy)
        return FlightPlan(int(instance_id), {"x": sx, "y": sy, "z": start.get("z")}, landing, 0.,
                          ((0., ground if ground is not None else landing["z"]),), clearance), "planned"
    ux, uy = dx/distance, dy/distance
    nx, ny = -uy, ux
    steps = int(math.ceil(distance / SAMPLE_YARDS))
    truncated = steps > MAX_SAMPLES
    profile = []
    for index in range(min(steps, MAX_SAMPLES) + 1):
        along = min(distance, index * SAMPLE_YARDS)
        cx, cy = sx + ux*along, sy + uy*along
        heights = [ground_height(geometry, instance_id, cx + nx*side, cy + ny*side)
                   for side in (-CORRIDOR_YARDS, 0., CORRIDOR_YARDS)]
        known = [height for height in heights if height is not None]
        if not known:
            return None, f"unknown_ground_at_{int(along)}_yd"
        profile.append((along, max(known)))
    if truncated:
        # Plan the first stretch; the next MOVE re-plans from there.
        distance = profile[-1][0]
        landing = {"x": sx + ux*distance, "y": sy + uy*distance, "z": profile[-1][1] + clearance}
    start_z = start.get("z")
    plan = FlightPlan(int(instance_id),
                      {"x": sx, "y": sy, "z": float(start_z) if start_z is not None else None},
                      landing, distance, tuple(profile), clearance, truncated=truncated)
    return plan, "planned"
