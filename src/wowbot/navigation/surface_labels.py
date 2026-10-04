"""Navmesh surface labels, regions and cave entrances from MAP + MMAP.

Step 4 of docs/NAVIGATION_MULTIRES_LAYERED_DESIGN.md (§10).  No vision and no
DB: for every walkable navmesh polygon the terrain height (TrinityCore maps)
is compared with the polygon height at its vertices.

* COVERED  — terrain well above the polygon everywhere (cave, tunnel, overhang)
* ELEVATED — polygon well above the terrain (bridge, building floor, ledge)
* SURFACE  — on the terrain
* UNKNOWN  — no terrain height (holes); resolved from the neighbours

Connected polygons with the same label form regions; a COVERED region that
touches SURFACE polygons through navmesh edges has entrances there.  Cave
mouths cut terrain holes, which is extra evidence for an entrance.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import math

SURFACE, COVERED, ELEVATED, UNKNOWN = "SURFACE", "COVERED", "ELEVATED", "UNKNOWN"
COVERED_DELTA = 3.5          # terrain above the polygon by more than this (yd)
ELEVATED_DELTA = -3.0        # polygon above the terrain by more than this
CAVE_MIN_AREA = 300.         # yd²; smaller covered regions are overhangs
CAVE_MIN_DEPTH = 8.          # median terrain-above-floor of a cave region (yd)
ENTRANCE_LINK_YARDS = 12.


@dataclass
class SurfaceRegion:
    region_id: int
    label: str
    polygons: list = field(default_factory=list)
    area: float = 0.
    centroid: tuple = (0., 0., 0.)
    kind: str = ""
    entrances: list = field(default_factory=list)
    depth: float = 0.

    def to_dict(self) -> dict:
        return {"region_id": self.region_id, "label": self.label, "kind": self.kind,
                "polygon_count": len(self.polygons), "area_yd2": round(self.area, 1),
                "median_depth_yd": round(self.depth, 1),
                "centroid_world": [round(v, 1) for v in self.centroid],
                "entrances": self.entrances}


@dataclass
class SurfaceLabelMap:
    instance_id: int
    labels: dict
    region_of: dict
    regions: list
    entrances: list
    stats: dict

    def label_at(self, key) -> str:
        return self.labels.get(key, UNKNOWN)

    def to_dict(self) -> dict:
        return {"instance_id": self.instance_id, "stats": self.stats,
                "regions": [region.to_dict() for region in self.regions
                            if region.label != SURFACE or len(region.polygons) >= 50],
                "entrances": self.entrances}


def _world(vertex) -> tuple[float, float, float]:
    """Detour (y-up) vertex -> world (x, y, z)."""
    return vertex[2], vertex[0], vertex[1]


def _area_xz(vertices) -> float:
    total = 0.
    for (ax, _ay, az), (bx, _by, bz) in zip(vertices, vertices[1:] + vertices[:1]):
        total += ax * bz - bx * az
    return abs(total) * .5


def classify_deltas(deltas: list[float]) -> str:
    """Label from terrain-minus-polygon heights at the vertices."""
    values = [value for value in deltas if value is not None]
    if not values:
        return UNKNOWN
    if min(values) > COVERED_DELTA:
        return COVERED
    if max(values) < ELEVATED_DELTA:
        return ELEVATED
    return SURFACE


class SurfaceLabeler:
    def __init__(self, navmesh, terrain) -> None:
        self.navmesh, self.terrain = navmesh, terrain

    def _terrain_height(self, instance_id: int, x: float, y: float, cache: dict):
        key = (round(x * 2), round(y * 2))
        if key not in cache:
            sample = self.terrain.sample(instance_id, x, y)
            cache[key] = (None if sample is None or sample.is_hole else sample.terrain_z,
                          bool(sample is not None and sample.is_hole))
        return cache[key]

    def build(self, instance_id: int, tiles=None) -> SurfaceLabelMap:
        navmesh = self.navmesh
        if tiles is None:
            tiles = sorted({(int(name[5:7]), int(name[8:10]))
                            for name in navmesh.source.names(f"{instance_id:04d}_", ".mmtile")})
        polygons = {}
        for grid_x, grid_y in tiles:
            for poly in navmesh._load_tile(instance_id, grid_x, grid_y):
                if poly.flags & navmesh.allowed_flags:
                    polygons[poly.key] = poly
        adjacency, portals = navmesh._adjacency(polygons)
        cache: dict = {}
        labels, holes, areas, depth = {}, set(), {}, {}
        # Polygons in tile order keep the terrain tile cache warm.
        for key, poly in polygons.items():
            deltas = []
            hole_vertices = 0
            for vertex in poly.vertices:
                x, y, z = _world(vertex)
                height, hole = self._terrain_height(instance_id, x, y, cache)
                hole_vertices += hole
                deltas.append(None if height is None else height - z)
            labels[key] = classify_deltas(deltas)
            known = sorted(value for value in deltas if value is not None)
            depth[key] = known[len(known) // 2] if known else 0.
            if hole_vertices:
                holes.add(key)
            areas[key] = _area_xz(list(poly.vertices))
        raw = Counter(labels.values())
        # Holes / missing terrain and tiny single-polygon outliers take the
        # neighbours' majority (noise filter, design doc §10.1).
        for _ in range(2):
            changed = {}
            for key, label in labels.items():
                neighbours = [labels[other] for other in adjacency[key] if labels[other] != UNKNOWN]
                if not neighbours:
                    continue
                majority, count = Counter(neighbours).most_common(1)[0]
                if label == UNKNOWN or (label != majority and areas[key] < 4.
                                        and count >= max(2, len(neighbours) - 1)):
                    changed[key] = majority
            labels.update(changed)
        region_of, regions = {}, []
        for key in polygons:
            if key in region_of:
                continue
            region = SurfaceRegion(len(regions), labels[key])
            stack = [key]
            region_of[key] = region.region_id
            while stack:
                current = stack.pop()
                region.polygons.append(current)
                for other in adjacency[current]:
                    if other not in region_of and labels[other] == region.label:
                        region_of[other] = region.region_id
                        stack.append(other)
            weights = [areas[k] for k in region.polygons]
            region.area = sum(weights)
            total = region.area or 1.
            centres = [_world(polygons[k].center) for k in region.polygons]
            region.centroid = tuple(sum(c[i] * w for c, w in zip(centres, weights)) / total
                                    for i in range(3))
            region_depths = sorted(depth[k] for k in region.polygons)
            region.depth = region_depths[len(region_depths) // 2]
            regions.append(region)
        surface_linked = {region_of[right] for (left, right) in portals
                          if labels.get(left) == SURFACE and labels.get(right) == COVERED}
        for region in regions:
            if region.label == COVERED:
                # A cave lies deep under the terrain and is big; shallow or
                # small covered patches are overhangs / under bridges.
                region.kind = ("ISOLATED" if region.region_id not in surface_linked
                               else "CAVE" if region.area >= CAVE_MIN_AREA and region.depth >= CAVE_MIN_DEPTH
                               else "UNDERCUT")
            elif region.label == ELEVATED:
                region.kind = "ELEVATED"
        caves = {region.region_id for region in regions if region.kind == "CAVE"}
        entrances = self._entrances(polygons, labels, region_of, regions, portals, holes, caves)
        for region in regions:
            if region.kind == "CAVE":
                region.entrances = [entrance["entrance_id"] for entrance in entrances
                                    if entrance["covered_region"] == region.region_id]
        stats = {"polygons": len(polygons), "raw_labels": dict(raw),
                 "labels": dict(Counter(labels.values())),
                 "regions": dict(Counter(f"{r.label}:{r.kind}" for r in regions)),
                 "entrances": len(entrances), "terrain_hole_polygons": len(holes)}
        return SurfaceLabelMap(instance_id, labels, region_of, regions, entrances, stats)

    @staticmethod
    def _entrances(polygons, labels, region_of, regions, portals, holes, caves) -> list[dict]:
        """Cluster SURFACE<->CAVE navmesh edges into entrances."""
        edges = []
        for (left, right), (first, second) in portals.items():
            if (labels.get(left) == SURFACE and labels.get(right) == COVERED
                    and region_of[right] in caves):
                mid = _world(tuple((a + b) * .5 for a, b in zip(first, second)))
                edges.append((mid, left, right))
        clusters: list[list] = []
        for edge in edges:
            for cluster in clusters:
                if (region_of[cluster[0][2]] == region_of[edge[2]]
                        and any(math.dist(edge[0][:2], other[0][:2]) <= ENTRANCE_LINK_YARDS
                                for other in cluster)):
                    cluster.append(edge)
                    break
            else:
                clusters.append([edge])
        result = []
        for index, cluster in enumerate(clusters):
            points = [edge[0] for edge in cluster]
            centre = tuple(sum(p[i] for p in points) / len(points) for i in range(3))
            inward = [0., 0.]
            for _mid, surface_key, covered_key in cluster:
                s = _world(polygons[surface_key].center)
                c = _world(polygons[covered_key].center)
                inward[0] += c[0] - s[0]
                inward[1] += c[1] - s[1]
            norm = math.hypot(*inward) or 1.
            width = max((math.dist(a[:2], b[:2]) for a in points for b in points), default=0.)
            hole_evidence = any(edge[1] in holes or edge[2] in holes for edge in cluster)
            result.append({
                "entrance_id": index, "centre_world": [round(v, 1) for v in centre],
                "inward_direction": [round(inward[0] / norm, 2), round(inward[1] / norm, 2)],
                "width_yd": round(width, 1), "edge_count": len(cluster),
                "covered_region": region_of[cluster[0][2]],
                "surface_region": region_of[cluster[0][1]],
                "terrain_hole_evidence": hole_evidence, "verified": False})
        return result
