"""Read-only TrinityCore mmap routing for verified WORLD_YARDS positions.

The loader understands the Recast/Detour tile representation written by
TrinityCore.  It never manufactures world coordinates from map pixels and it
owns no input.  Its only product is a sequence of walkable world-space route
anchors consumed by the canonical NavigationService.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
from functools import lru_cache
import heapq
import math
import os
from pathlib import Path
import struct
from typing import Iterable
import zipfile


MMAP_MAGIC = 0x4D4D4150
DETOUR_NAVMESH_MAGIC = 0x444E4156
DT_EXT_LINK = 0x8000
DT_POLYTYPE_GROUND = 0
NAV_GROUND = 0x01
NAV_GROUND_STEEP = 0x02
NAV_WATER = 0x04
NAV_MAGMA_SLIME = 0x08
GRID_SIZE = 533.3333333333334
SURFACE_BIN_SIZE = 8.0
# Live Retail collision rejected a 45-degree mmap transition at the Quilboar
# Briarpatch even though the polygon graph exposed it as connected.  Keep a
# small evidence-based margin below that failure angle and let A* select a
# gentler supported corridor.
DEFAULT_MAX_WALKABLE_SLOPE_DEGREES = 44.0


@dataclass(frozen=True, slots=True)
class NavPolygon:
    key: tuple[int, int]
    vertices: tuple[tuple[float, float, float], ...]  # Detour X,Y,Z
    neighbours: tuple[int, ...]
    flags: int

    @property
    def center(self) -> tuple[float, float, float]:
        count = len(self.vertices)
        return tuple(sum(point[axis] for point in self.vertices) / count
                     for axis in range(3))  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class NavMeshPath:
    anchors: tuple[dict[str, float | int | str], ...]
    polygon_count: int
    tile_count: int
    cost: float


class MMapDataSource:
    """Random-access source backed by either a directory or the original zip."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self._zip = zipfile.ZipFile(self.path) if self.path.is_file() else None
        self._names = frozenset(self._zip.namelist()) if self._zip else None

    def exists(self, name: str) -> bool:
        return name in self._names if self._names is not None else (self.path / name).is_file()

    def names(self, prefix: str = "", suffix: str = "") -> list[str]:
        """File names (zip members or folder entries) with a prefix/suffix."""
        names = (self._names if self._names is not None
                 else (item.name for item in self.path.iterdir()))
        return [name for name in names if name.startswith(prefix) and name.endswith(suffix)]

    def read(self, name: str) -> bytes:
        if self._zip is not None:
            return self._zip.read(name)
        return (self.path / name).read_bytes()

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()


class TrinityMMapNavMesh:
    """Lazy tile parser and bounded polygon A* router."""

    def __init__(self, source: str | Path, *, tile_padding: int = 1,
                 max_expansions: int = 250_000,
                 allowed_flags: int = NAV_GROUND | NAV_GROUND_STEEP,
                 max_walkable_slope_degrees: float = DEFAULT_MAX_WALKABLE_SLOPE_DEGREES):
        self.source = MMapDataSource(source)
        self.tile_padding = max(0, int(tile_padding))
        self.max_expansions = max(1, int(max_expansions))
        # Player walking uses land/steep-land only. Swimming is a separate
        # capability and must be opted into explicitly; magma/slime is never
        # silently treated as ordinary walkable terrain.
        self.allowed_flags = int(allowed_flags)
        self.max_walkable_slope_degrees = max(
            0., min(89., float(max_walkable_slope_degrees)))
        self._max_walkable_slope_ratio = math.tan(
            math.radians(self.max_walkable_slope_degrees))
        self._graph_cache: OrderedDict[tuple, tuple[dict, dict, dict, int]] = OrderedDict()
        # Surface projection used to test every polygon in a 3x3 tile window
        # (about 39k polygons on Exile's Reach) for every FAST position.  Keep
        # a bounded horizontal spatial index per tile window instead.  This is
        # query acceleration only; it neither changes walkability flags nor
        # manufactures a different surface.
        self._surface_index_cache: OrderedDict[
            tuple[int, int, int], tuple[dict[tuple[int, int], tuple[NavPolygon, ...]],
                                       tuple[NavPolygon, ...]]] = OrderedDict()
        self.last_diagnostics: dict = {"available": True, "source": str(self.source.path)}
        self.last_surface_projection: dict = {}

    @classmethod
    def from_environment(cls) -> TrinityMMapNavMesh | None:
        value = os.getenv("WOWBOT_MMAP_PATH", "").strip()
        if not value:
            return None
        try:
            return cls(value)
        except (OSError, zipfile.BadZipFile, ValueError):
            return None

    def close(self) -> None:
        self.source.close()

    def supports(self, instance_id: int) -> bool:
        return self.source.exists(f"{int(instance_id):04d}.mmap")

    def project_position(self, instance_id: int, point: dict, *,
                         z_hint: float | None = None) -> dict | None:
        """Project fresh world X/Y onto the corresponding mmap surface.

        The returned Z is authoritative *for the selected navmesh surface*,
        not an observation from the Retail client.  When stacked polygons
        share the same X/Y, the active corridor's nearest anchor supplies the
        layer hint so successive waypoint updates cannot jump floors.
        """
        instance_id = int(instance_id)
        if not self.supports(instance_id):
            self.last_surface_projection = {
                "status": "UNAVAILABLE", "reason": "map_header_missing",
                "instance_id": instance_id}
            return None
        dt = self._world_to_detour(point)
        grid = self._world_grid(point)
        if dt is None or grid is None:
            self.last_surface_projection = {
                "status": "UNAVAILABLE", "reason": "invalid_world_xy",
                "instance_id": instance_id}
            return None
        hint = float(z_hint) if isinstance(z_hint, (int, float)) and math.isfinite(float(z_hint)) else None
        hint_source = "route" if hint is not None else None
        last = self.__dict__.get("_last_surface")
        if (hint is None and last is not None and last[0] == instance_id
                and math.hypot(last[1]-float(point["x"]), last[2]-float(point["y"])) <= self.SURFACE_CONTINUITY_YARDS):
            # Track the own surface continuously (design doc §4.3): without a
            # route hint the previous projected height keeps the layer, so a
            # cave floor cannot flip to the hill above it between samples.
            hint, hint_source = last[3], "continuity"
        native = self._native_map(instance_id) if hint is not None else None
        if native is not None:
            projected = self._native_project(native, instance_id, point, dt, hint, hint_source)
            if projected is not None:
                return projected
        surface_index, polygons = self._surface_index(instance_id, grid)
        if not polygons:
            self.last_surface_projection = {
                "status": "UNAVAILABLE", "reason": "no_nearby_walkable_polygon",
                "instance_id": instance_id}
            return None
        bin_key = self._surface_bin(dt[0], dt[2])
        local_polygons = surface_index.get(bin_key, ())
        contained = [(poly, self._polygon_height_at(poly, dt[0], dt[2]))
                     for poly in local_polygons]
        contained = [(poly, height) for poly, height in contained if height is not None]
        # A point exactly on a bin boundary can be absent because of floating
        # point rounding in the bbox-to-bin conversion.  Neighbouring bins are
        # still a tiny bounded set and preserve the old nearest fallback.
        nearby = local_polygons
        if not contained:
            nearby = tuple(dict.fromkeys(
                poly for bx in range(bin_key[0]-1, bin_key[0]+2)
                for bz in range(bin_key[1]-1, bin_key[1]+2)
                for poly in surface_index.get((bx, bz), ())))
        candidates = contained or [(poly, poly.center[1]) for poly in nearby or polygons]

        def score(item):
            poly, height = item
            center = poly.center
            horizontal = math.hypot(center[0]-dt[0], center[2]-dt[2])
            return horizontal + (abs(height-hint)*3. if hint is not None else 0.)

        selected, height = min(candidates, key=score)
        heights = sorted({round(value, 2) for _, value in contained})
        ambiguous = len(heights) > 1 and heights[-1]-heights[0] > 3.
        result = {
            "x": float(point["x"]), "y": float(point["y"]), "z": float(height),
            "instance_id": instance_id, "coordinate_space": "WORLD_YARDS",
            "source": "TRINITYCORE_MMAP_SURFACE", "z_source": "NAVMESH_SURFACE",
            "z_known": True, "z_observed": False, "z_estimated": True,
            "surface_polygon": selected.key, "surface_layer_ambiguous": ambiguous,
            "surface_layer_hint_used": hint is not None,
        }
        self.last_surface_projection = {
            "status": "PROJECTED", "instance_id": instance_id,
            "polygon": selected.key, "z": float(height),
            "candidate_heights": heights[:12], "layer_ambiguous": ambiguous,
            "layer_hint": hint, "layer_hint_source": hint_source,
            "contained_candidates": len(contained),
            "surface_index_candidates": len(local_polygons),
        }
        self.__dict__["_last_surface"] = (instance_id, float(point["x"]), float(point["y"]), float(height))
        return result

    def walkable_points_near(self, instance_id: int, point: dict, radius: float) -> list[dict]:
        """Centres of the walkable polygons within ``radius`` yards, every layer.

        Planning-only geometry for destination-layer selection (design doc
        §5: a quest POI on a pit rim, its objective far below).  No state is
        changed, unlike ``project_position``'s continuity tracking.
        """
        instance_id = int(instance_id)
        dt, grid = self._world_to_detour(point), self._world_grid(point)
        if dt is None or grid is None or not self.supports(instance_id):
            return []
        native = self._native_map(instance_id)
        if native is not None and native.has_layer_queries:
            return [self._detour_to_world(centre, instance_id) for _ref, centre in native.polys_near(
                (dt[0], 0., dt[2]), extents=(radius, self.NATIVE_LAYER_HALF_HEIGHT, radius),
                include=self.allowed_flags)
                if math.hypot(centre[0]-dt[0], centre[2]-dt[2]) <= radius]
        index, _polygons = self._surface_index(instance_id, grid)
        low = self._surface_bin(dt[0]-radius, dt[2]-radius)
        high = self._surface_bin(dt[0]+radius, dt[2]+radius)
        found: dict = {}
        for bx in range(low[0], high[0]+1):
            for bz in range(low[1], high[1]+1):
                for poly in index.get((bx, bz), ()):
                    centre = poly.center
                    if poly.key not in found and math.hypot(centre[0]-dt[0], centre[2]-dt[2]) <= radius:
                        found[poly.key] = self._detour_to_world(centre, instance_id)
        return list(found.values())

    def walkable_heights_at(self, instance_id: int, point: dict, radius: float = 2.5) -> list[float]:
        """Heights of every walkable layer at one X/Y (or within ``radius``).

        Planning-only: after a fall the player is re-placed on the layer
        below without disturbing ``project_position``'s continuity state.
        """
        instance_id = int(instance_id)
        dt, grid = self._world_to_detour(point), self._world_grid(point)
        if dt is None or grid is None or not self.supports(instance_id):
            return []
        native = self._native_map(instance_id)
        if native is not None and native.has_layer_queries:
            # Detour itself (C++): the same polygons the routes use.
            layers = native.layers_at((dt[0], 0., dt[2]), extents=(.5, self.NATIVE_LAYER_HALF_HEIGHT, .5),
                                      include=self.allowed_flags)
            if not layers and radius > 0:
                layers = [(centre[1], ref) for ref, centre in native.polys_near(
                    (dt[0], 0., dt[2]), extents=(radius, self.NATIVE_LAYER_HALF_HEIGHT, radius),
                    include=self.allowed_flags)
                    if math.hypot(centre[0]-dt[0], centre[2]-dt[2]) <= radius]
            return sorted({round(float(height), 2) for height, _ref in layers})
        index, _polygons = self._surface_index(instance_id, grid)
        bin_key = self._surface_bin(dt[0], dt[2])
        heights = {round(height, 2) for poly in index.get(bin_key, ())
                   for height in (self._polygon_height_at(poly, dt[0], dt[2]),)
                   if height is not None}
        if not heights:
            heights = {round(float(item["z"]), 2) for item in self.walkable_points_near(instance_id, point, radius)
                       if isinstance(item.get("z"), (int, float))}
        return sorted(heights)

    def walkable_layers_at(self, instance_id: int, point: dict, radius: float = 2.5) -> list[dict]:
        """Read-only floor candidates with polygon identity at one X/Y.

        Heights alone cannot distinguish two adjacent/interior navmesh
        surfaces at nearly the same Z.  This does not mutate the active route
        or the surface projection's continuity cache.
        """
        instance_id = int(instance_id)
        dt, grid = self._world_to_detour(point), self._world_grid(point)
        if dt is None or grid is None or not self.supports(instance_id):
            return []
        native = self._native_map(instance_id)
        if native is not None and native.has_layer_queries:
            layers = native.layers_at((dt[0], 0., dt[2]),
                                      extents=(.5, self.NATIVE_LAYER_HALF_HEIGHT, .5),
                                      include=self.allowed_flags)
            if layers:
                return [{"z": float(height), "layer_id": ("detour", int(ref))}
                        for height, ref in layers]
        index, _polygons = self._surface_index(instance_id, grid)
        return [{"z": float(height), "layer_id": poly.key}
                for poly in index.get(self._surface_bin(dt[0], dt[2]), ())
                for height in (self._polygon_height_at(poly, dt[0], dt[2]),)
                if height is not None]

    SURFACE_CONTINUITY_YARDS = 15.
    NATIVE_LAYER_HALF_HEIGHT = 1500.
    # Keep up to this far from the walkway's edges (walls, drops) where it is
    # wide enough; every portal crossing is a waypoint (user 2026-10-06).
    PATH_CENTER_MARGIN = 2.5
    NATIVE_SURFACE_EXTENTS = ((1.5, 4., 1.5), (3., 10., 3.))

    def _native_project(self, native, instance_id: int, point: dict, dt: tuple,
                        hint: float, hint_source: str | None) -> dict | None:
        """Nearest polygon in a 3D box around (x, hinted height, y)."""
        for extents in self.NATIVE_SURFACE_EXTENTS:
            found = native.nearest((dt[0], hint, dt[2]), extents=extents, include=self.allowed_flags)
            if found is not None:
                break
        else:
            return None
        ref, nearest = found
        height = float(nearest[1])
        result = {
            "x": float(point["x"]), "y": float(point["y"]), "z": height,
            "instance_id": instance_id, "coordinate_space": "WORLD_YARDS",
            "source": "TRINITYCORE_MMAP_SURFACE", "z_source": "NAVMESH_SURFACE",
            "z_known": True, "z_observed": False, "z_estimated": True,
            "surface_polygon": ("detour", ref), "surface_layer_ambiguous": None,
            "surface_layer_hint_used": True,
        }
        self.last_surface_projection = {
            "status": "PROJECTED", "router": "native_detour", "instance_id": instance_id,
            "polygon": ref, "z": height, "layer_hint": hint, "layer_hint_source": hint_source}
        self.__dict__["_last_surface"] = (instance_id, float(point["x"]), float(point["y"]), height)
        return result

    @staticmethod
    def _surface_bin(x: float, z: float) -> tuple[int, int]:
        return (math.floor(x / SURFACE_BIN_SIZE),
                math.floor(z / SURFACE_BIN_SIZE))

    def _surface_index(self, instance_id: int, grid: tuple[int, int]):
        key = (instance_id, grid[0], grid[1])
        cached = self._surface_index_cache.get(key)
        if cached is not None:
            self._surface_index_cache.move_to_end(key)
            return cached
        polygons = tuple(
            poly for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            for poly in self._load_tile(instance_id, grid[0]+dx, grid[1]+dy)
            if poly.flags & self.allowed_flags)
        bins: dict[tuple[int, int], list[NavPolygon]] = {}
        for poly in polygons:
            xs = [vertex[0] for vertex in poly.vertices]
            zs = [vertex[2] for vertex in poly.vertices]
            low = self._surface_bin(min(xs), min(zs))
            high = self._surface_bin(max(xs), max(zs))
            for bx in range(low[0], high[0]+1):
                for bz in range(low[1], high[1]+1):
                    bins.setdefault((bx, bz), []).append(poly)
        result = ({cell: tuple(values) for cell, values in bins.items()}, polygons)
        self._surface_index_cache[key] = result
        self._surface_index_cache.move_to_end(key)
        while len(self._surface_index_cache) > 6:
            self._surface_index_cache.popitem(last=False)
        return result

    def find_path(self, instance_id: int, start: dict, destination: dict) -> NavMeshPath | None:
        instance_id = int(instance_id)
        if not self.supports(instance_id):
            self.last_diagnostics = {"available": False, "reason": "map_header_missing",
                                     "instance_id": instance_id}
            return None
        start_dt = self._world_to_detour(start)
        end_dt = self._world_to_detour(destination)
        if start_dt is None or end_dt is None:
            self.last_diagnostics = {"available": True, "reason": "invalid_world_endpoint",
                                     "instance_id": instance_id}
            return None
        native = self._native_map(instance_id)
        if native is not None:
            return self._native_find_path(native, instance_id, start, destination, start_dt, end_dt)
        tile_coords = self._corridor_tiles(start, destination)
        graph_key = (instance_id, tile_coords)
        graph = self._graph_cache.get(graph_key)
        graph_cache_hit = graph is not None
        if graph is None:
            tiles = []
            for grid_x, grid_y in tile_coords:
                tile = self._load_tile(instance_id, grid_x, grid_y)
                if tile:
                    tiles.append(tile)
            polygons = {poly.key: poly for tile in tiles for poly in tile
                        if poly.flags & self.allowed_flags}
            adjacency, portals = self._adjacency(polygons)
            graph = (polygons, adjacency, portals, len(tiles))
            self._graph_cache[graph_key] = graph
            self._graph_cache.move_to_end(graph_key)
            while len(self._graph_cache) > 3:
                self._graph_cache.popitem(last=False)
        polygons, adjacency, portals, tile_count = graph
        if not polygons:
            self.last_diagnostics = {"available": True, "reason": "no_route_tiles",
                                     "instance_id": instance_id,
                                     "requested_tiles": len(tile_coords)}
            return None
        start_z_known = start.get("z_known") is not False and "z" in start
        end_z_known = destination.get("z_known") is not False and "z" in destination
        start_key = self._nearest_polygon(polygons.values(), start_dt,
                                          use_vertical=start_z_known)
        end_key = self._nearest_polygon(polygons.values(), end_dt,
                                        use_vertical=end_z_known)
        if start_key is None or end_key is None:
            self.last_diagnostics = {"available": True, "reason": "endpoint_not_on_mesh",
                                     "instance_id": instance_id, "tile_count": tile_count}
            return None
        # C_Map.GetWorldPosFromMapPos deliberately provides only X/Y. Snap
        # that endpoint onto the selected walkable polygon instead of
        # inventing Z=0, which could select a wrong elevation or emit a bogus
        # final anchor. Multi-floor ambiguity remains a transition problem.
        if not start_z_known:
            start_dt = (start_dt[0], polygons[start_key].center[1], start_dt[2])
        if not end_z_known:
            end_dt = (end_dt[0], polygons[end_key].center[1], end_dt[2])
        chain = self._a_star(polygons, adjacency, start_key, end_key)
        if not chain:
            self.last_diagnostics = {"available": True, "reason": "no_polygon_path",
                                     "instance_id": instance_id, "tile_count": tile_count,
                                     "polygon_count": len(polygons)}
            return None
        anchors_dt = self._string_pull(chain, polygons, portals, start_dt, end_dt)
        anchors = tuple(self._detour_to_world(point, instance_id) for point in anchors_dt)
        cost = sum(math.dist((a["x"], a["y"], a["z"]),
                             (b["x"], b["y"], b["z"]))
                   for a, b in zip(anchors, anchors[1:]))
        result = NavMeshPath(anchors, len(chain), tile_count, cost)
        self.last_diagnostics = {"available": True, "reason": "route_found",
                                 "instance_id": instance_id, "tile_count": tile_count,
                                 "loaded_polygon_count": len(polygons),
                                 "route_polygon_count": len(chain),
                                 "anchor_count": len(anchors), "cost": cost,
                                 "graph_cache_hit": graph_cache_hit,
                                 "allowed_flags": self.allowed_flags,
                                 "max_walkable_slope_degrees": self.max_walkable_slope_degrees}
        return result

    # ----- native Detour (docs/NAVIGATION_MULTIRES_LAYERED_DESIGN.md step 2) -----
    KNOWN_Z_EXTENTS = ((3., 6., 3.), (8., 20., 8.))
    UNKNOWN_Z_VERTICAL = 400.

    def _native_map(self, instance_id: int):
        """Lazily load every tile of the map into native Detour; None = fallback."""
        cache = self.__dict__.setdefault("_native_maps", {})
        if instance_id in cache:
            return cache[instance_id]
        if not self.__dict__.get("use_native", True):
            return None
        try:
            from .detour_native import NativeDetourMap, load_library
            library = self.__dict__.get("_native_library") or load_library()
            self.__dict__["_native_library"] = library
            native = NativeDetourMap(library, self.source, instance_id)
            if native.tiles == 0:
                native.close()
                native = None
        except Exception as error:   # missing DLL / ABI: keep the Python router
            self.__dict__["native_error"] = f"{type(error).__name__}: {error}"
            native = None
        cache[instance_id] = native
        return native

    LAYER_PROBE_BELOW = 60.
    LAYER_PROBE_ABOVE = 80.
    LAYER_PROBE_STEP = 3.

    def _layers_at(self, native, dt: tuple, include: int, around: float) -> list[tuple]:
        """Every walkable layer under/over one X/Y (Detour points)."""
        layers, seen = [], set()
        height = around-self.LAYER_PROBE_BELOW
        while height <= around+self.LAYER_PROBE_ABOVE:
            hit = native.nearest((dt[0], height, dt[2]), extents=(2., self.LAYER_PROBE_STEP/2+.5, 2.),
                                 include=include)
            if hit is not None and hit[0] not in seen:
                seen.add(hit[0])
                layers.append(hit[1])
            height += self.LAYER_PROBE_STEP
        return layers

    def _probe_reachable_layer(self, native, start_dt: tuple, end_dt: tuple, include: int,
                               *, start_z_known: bool, probe_start: bool = False,
                               probe_end: bool = True):
        """Shortest complete path between walkable layers at start and target.

        Live 2026-10-04 (Torgok in the Ogre Ruins): the quest POI had three
        layers (80.9 / 83.8 / 122.0).  With no target Z the start height was
        assumed, which picked the 80.9 layer: Detour found only a partial
        path.  The 83.8 floor inside the building was reachable in 66 yd.
        Leaving the building afterwards the *player* got the terrain height
        under the building (80.9, an isolated island) as its Z; with
        ``probe_start`` the start layers are tried as well, preferring the
        layer the player was last projected onto (continuity).
        """
        anchor = start_dt
        if not start_z_known:
            hit = native.nearest(start_dt, extents=(3., self.UNKNOWN_Z_VERTICAL, 3.), include=include)
            if hit is None:
                return None
            anchor = hit[1]
        starts = self._layers_at(native, anchor, include, anchor[1]) if probe_start else [anchor]
        if not starts:
            starts = [anchor]
        ends = self._layers_at(native, end_dt, include, anchor[1]) if probe_end else [end_dt]
        last = self.__dict__.get("_last_surface")
        continuity = None
        if probe_start and last is not None:
            # _last_surface is (instance, world x, world y, height); Detour x/z are world y/x.
            if math.hypot(last[2]-anchor[0], last[1]-anchor[2]) <= self.SURFACE_CONTINUITY_YARDS:
                continuity = last[3]
        complete = []
        for start_point in starts:
            for point in ends:
                result = native.find_path(start_point, point, extents=(2., 4., 2.), include=include)
                if result[0] == 1 and result[1]:
                    cost = sum(math.dist(a, b) for a, b in zip(result[1], result[1][1:]))
                    jump = abs(start_point[1]-continuity) if continuity is not None else 0.
                    complete.append((jump > 3., cost, abs(point[1]-start_point[1]), result))
        if not complete:
            return None
        return min(complete, key=lambda entry: entry[:3])[3]

    def _native_find_path(self, native, instance_id: int, start: dict, destination: dict,
                          start_dt: tuple, end_dt: tuple) -> NavMeshPath | None:
        start_z_known = start.get("z_known") is not False and "z" in start
        end_z_known = destination.get("z_known") is not False and "z" in destination
        layer_note = "known"
        if not end_z_known:
            # Without a Z the endpoint layer is unknown.  Never pick a layer by
            # 2D distance: take the one nearest the start's height (usually
            # the ground the player walks on) and say so in diagnostics.
            end_dt = (end_dt[0], start_dt[1], end_dt[2])
            layer_note = "assumed_start_height"
        include = self.allowed_flags
        result = None
        if not end_z_known:
            probed = self._probe_reachable_layer(native, start_dt, end_dt, include,
                                                 start_z_known=start_z_known)
            if probed is not None:
                result, layer_note = probed, "shortest_reachable_layer"
        for extents in (() if result is not None else self.KNOWN_Z_EXTENTS):
            extents_used = (extents if end_z_known and start_z_known
                            else (extents[0], self.UNKNOWN_Z_VERTICAL, extents[2]))
            result = native.find_path(start_dt, end_dt, extents=extents_used, include=include,
                                      margin=self.PATH_CENTER_MARGIN)
            if result[0] not in (-1, -2):
                break
        def estimated(point: dict, known: bool) -> bool:
            return (not known or (point.get("z_observed") is not True
                                  and bool(point.get("z_estimated") or point.get("z_source"))))
        if (result is not None and result[0] != 1
                and (estimated(destination, end_z_known) or estimated(start, start_z_known))):
            # Live 2026-10-04 18:52: the terrain (maps) height under Torgok's
            # building (80.9) was injected as a "known" Z for the quest POI;
            # Detour gave only a partial path and every MOVE failed with
            # required_navmesh_route_unavailable.  An *estimated* target
            # height is a hint: if it has no complete path, take the shortest
            # complete path to any walkable layer there (here the 83.8 floor).
            probed = self._probe_reachable_layer(
                native, start_dt, end_dt, include, start_z_known=start_z_known,
                probe_start=estimated(start, start_z_known),
                probe_end=estimated(destination, end_z_known))
            if probed is not None:
                result, layer_note = probed, "estimated_z_unreachable_shortest_layer"
        code, corners, poly_count, _refs = result
        base = {"available": True, "router": "native_detour", "instance_id": instance_id,
                "tile_count": native.tiles, "endpoint_layer": layer_note,
                "allowed_flags": self.allowed_flags,
                "max_walkable_slope_degrees": self.max_walkable_slope_degrees}
        if code in (-1, -2):
            self.last_diagnostics = {**base, "reason": "endpoint_not_on_mesh",
                                     "endpoint": "start" if code == -1 else "destination"}
            return None
        if code != 1 or len(corners) < 1:
            self.last_diagnostics = {**base, "reason": "no_polygon_path",
                                     "partial": code == 2, "route_polygon_count": poly_count}
            return None
        anchors = tuple(self._detour_to_world(point, instance_id) for point in corners)
        cost = sum(math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))
                   for a, b in zip(anchors, anchors[1:]))
        self.last_diagnostics = {**base, "reason": "route_found", "route_polygon_count": poly_count,
                                 "anchor_count": len(anchors), "cost": cost}
        return NavMeshPath(anchors, poly_count, native.tiles, cost)

    @lru_cache(maxsize=96)
    def _load_tile(self, instance_id: int, grid_x: int,
                   grid_y: int) -> tuple[NavPolygon, ...]:
        name = f"{instance_id:04d}_{grid_x:02d}_{grid_y:02d}.mmtile"
        if not self.source.exists(name):
            return ()
        # Deterministic per-map tile identity; Python's salted hash would make
        # diagnostics and route construction needlessly process-dependent.
        tile_key = instance_id * 10_000 + grid_x * 100 + grid_y
        return self._parse_tile(self.source.read(name), tile_key)

    @staticmethod
    def _parse_tile(data: bytes, tile_key: int) -> tuple[NavPolygon, ...]:
        if len(data) < 116:
            return ()
        magic, mmap_version, detour_version, data_size, _uses_liquids = struct.unpack_from("<5I", data)
        if magic != MMAP_MAGIC or data_size + 20 > len(data):
            return ()
        mesh = memoryview(data)[20:20 + data_size]
        # Current TrinityCore tiles use the Detour header variant containing
        # x, y and layer before userId (15 ints total).
        header = struct.unpack_from("<15i10f", mesh, 0)
        # The tile wrapper records both Trinity's mmap serialization version
        # and the Detour ABI version. dtMeshHeader.version is the serialized
        # mesh format (the former), not DT_NAVMESH_VERSION from the wrapper.
        if header[0] != DETOUR_NAVMESH_MAGIC or header[1] != mmap_version:
            return ()
        poly_count, vert_count = header[6], header[7]
        if poly_count <= 0 or vert_count <= 0 or poly_count > 2_000_000 or vert_count > 4_000_000:
            return ()
        vertex_offset = 100
        polygon_offset = vertex_offset + vert_count * 12
        if polygon_offset + poly_count * 32 > len(mesh):
            return ()
        raw_vertices = struct.unpack_from(f"<{vert_count * 3}f", mesh, vertex_offset)
        vertices = tuple(tuple(raw_vertices[index:index+3])
                         for index in range(0, len(raw_vertices), 3))
        result = []
        for index in range(poly_count):
            offset = polygon_offset + index * 32
            _first_link = struct.unpack_from("<I", mesh, offset)[0]
            refs = struct.unpack_from("<6H", mesh, offset + 4)
            neighbours = struct.unpack_from("<6H", mesh, offset + 16)
            flags, vertex_count, area_and_type = struct.unpack_from("<HBB", mesh, offset + 28)
            if (area_and_type >> 6) != DT_POLYTYPE_GROUND or vertex_count < 3 or vertex_count > 6:
                continue
            if any(ref >= vert_count for ref in refs[:vertex_count]):
                continue
            result.append(NavPolygon(
                (tile_key, index), tuple(vertices[ref] for ref in refs[:vertex_count]),
                tuple(neighbours[:vertex_count]), flags))
        return tuple(result)

    def _corridor_tiles(self, start: dict, destination: dict) -> tuple[tuple[int, int], ...]:
        left = self._world_grid(start)
        right = self._world_grid(destination)
        if left is None or right is None:
            return ()
        line = self._grid_line(left, right)
        return tuple(sorted({(x+dx, y+dy) for x, y in line
                             for dx in range(-self.tile_padding, self.tile_padding+1)
                             for dy in range(-self.tile_padding, self.tile_padding+1)
                             if 0 <= x+dx <= 99 and 0 <= y+dy <= 99}))

    @staticmethod
    def _world_grid(point: dict) -> tuple[int, int] | None:
        try:
            x, y = float(point["x"]), float(point["y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        return math.floor(32. - x / GRID_SIZE), math.floor(32. - y / GRID_SIZE)

    @staticmethod
    def _grid_line(left: tuple[int, int], right: tuple[int, int]) -> tuple[tuple[int, int], ...]:
        x0, y0 = left
        x1, y1 = right
        dx, dy = abs(x1-x0), -abs(y1-y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        error, points = dx+dy, []
        while True:
            points.append((x0, y0))
            if (x0, y0) == (x1, y1):
                return tuple(points)
            twice = 2*error
            if twice >= dy:
                error += dy
                x0 += sx
            if twice <= dx:
                error += dx
                y0 += sy

    @staticmethod
    def _adjacency(polygons: dict) -> tuple[dict, dict]:
        adjacency = {key: set() for key in polygons}
        portals = {}
        edge_index = {}
        external_edges = {}
        for key, poly in polygons.items():
            for edge_index_in_poly, neighbour in enumerate(poly.neighbours):
                if neighbour and not neighbour & DT_EXT_LINK:
                    other = (key[0], neighbour-1)
                    if other in polygons:
                        adjacency[key].add(other)
                first = poly.vertices[edge_index_in_poly]
                second = poly.vertices[(edge_index_in_poly+1) % len(poly.vertices)]
                if neighbour & DT_EXT_LINK:
                    axis = (0 if abs(first[0]-second[0]) <= abs(first[2]-second[2])
                            else 2)
                    line_coordinate = (first[axis]+second[axis])*.5
                    external_edges.setdefault((axis, round(line_coordinate*100)), []).append(
                        (key, first, second))
                edge_key = tuple(sorted((TrinityMMapNavMesh._quantized(first),
                                         TrinityMMapNavMesh._quantized(second))))
                previous = edge_index.get(edge_key)
                if previous and previous[0] != key:
                    other, other_edge = previous
                    adjacency[key].add(other)
                    adjacency[other].add(key)
                    portals[(key, other)] = (first, second)
                    portals[(other, key)] = other_edge
                else:
                    edge_index[edge_key] = (key, (first, second))
        # Border polygons in adjacent mmtile files need not split their
        # collinear portal edges at identical vertices (T-junctions are
        # normal). Match the overlapping interval rather than requiring the
        # two raw edge endpoint pairs to be equal.
        for entries in external_edges.values():
            for index, (left_key, left_a, left_b) in enumerate(entries):
                for right_key, right_a, right_b in entries[index+1:]:
                    if left_key[0] == right_key[0]:
                        continue
                    axis = 0 if abs(left_a[0]-left_b[0]) <= abs(left_a[2]-left_b[2]) else 2
                    varying = 2 if axis == 0 else 0
                    low = max(min(left_a[varying], left_b[varying]),
                              min(right_a[varying], right_b[varying]))
                    high = min(max(left_a[varying], left_b[varying]),
                               max(right_a[varying], right_b[varying]))
                    if high-low <= .01:
                        continue
                    midpoint = (low+high)*.5
                    left_y = TrinityMMapNavMesh._edge_height(left_a, left_b, varying, midpoint)
                    right_y = TrinityMMapNavMesh._edge_height(right_a, right_b, varying, midpoint)
                    if abs(left_y-right_y) > 3.0:
                        continue
                    fixed = (left_a[axis]+left_b[axis]+right_a[axis]+right_b[axis])*.25
                    y = (left_y+right_y)*.5
                    first = [0., y, 0.]
                    second = [0., y, 0.]
                    first[axis] = second[axis] = fixed
                    first[varying], second[varying] = low, high
                    portal = (tuple(first), tuple(second))
                    adjacency[left_key].add(right_key)
                    adjacency[right_key].add(left_key)
                    portals[(left_key, right_key)] = portal
                    portals[(right_key, left_key)] = (portal[1], portal[0])
        return adjacency, portals

    @staticmethod
    def _edge_height(first, second, varying_axis: int, value: float) -> float:
        span = second[varying_axis]-first[varying_axis]
        ratio = 0. if abs(span) < 1e-9 else (value-first[varying_axis])/span
        return first[1] + (second[1]-first[1])*ratio

    @staticmethod
    def _polygon_height_at(poly: NavPolygon, x: float, z: float) -> float | None:
        """Interpolate Detour Y on a convex polygon fan at horizontal X/Z."""
        vertices = poly.vertices
        if len(vertices) < 3:
            return None
        a = vertices[0]
        for index in range(1, len(vertices)-1):
            b, c = vertices[index], vertices[index+1]
            denominator = ((b[2]-c[2])*(a[0]-c[0])
                           + (c[0]-b[0])*(a[2]-c[2]))
            if abs(denominator) < 1e-9:
                continue
            wa = ((b[2]-c[2])*(x-c[0]) + (c[0]-b[0])*(z-c[2])) / denominator
            wb = ((c[2]-a[2])*(x-c[0]) + (a[0]-c[0])*(z-c[2])) / denominator
            wc = 1.-wa-wb
            if min(wa, wb, wc) >= -1e-5:
                return wa*a[1] + wb*b[1] + wc*c[1]
        return None

    @staticmethod
    def _quantized(point: tuple[float, float, float]) -> tuple[int, int, int]:
        return tuple(round(value * 1000) for value in point)  # type: ignore[return-value]

    @staticmethod
    def _nearest_polygon(polygons: Iterable[NavPolygon],
                         point: tuple[float, float, float], *,
                         use_vertical: bool = True) -> tuple[int, int] | None:
        best_key, best_score = None, math.inf
        for poly in polygons:
            center = poly.center
            horizontal = math.hypot(center[0]-point[0], center[2]-point[2])
            vertical = abs(center[1]-point[1]) if use_vertical else 0.
            score = horizontal + vertical * 3.
            if score < best_score:
                best_key, best_score = poly.key, score
        return best_key

    def _a_star(self, polygons: dict, adjacency: dict,
                start, destination) -> tuple[tuple[int, int], ...]:
        if start == destination:
            return (start,)
        target = polygons[destination].center
        open_set = [(0., start)]
        parent = {}
        cost = {start: 0.}
        expanded = 0
        while open_set and expanded < self.max_expansions:
            _, current = heapq.heappop(open_set)
            expanded += 1
            if current == destination:
                chain = [current]
                while current in parent:
                    current = parent[current]
                    chain.append(current)
                return tuple(reversed(chain))
            center = polygons[current].center
            for neighbour in adjacency.get(current, ()):
                if not self._walkable_transition(center, polygons[neighbour].center):
                    continue
                step = math.dist(center, polygons[neighbour].center)
                candidate = cost[current] + step
                if candidate >= cost.get(neighbour, math.inf):
                    continue
                cost[neighbour] = candidate
                parent[neighbour] = current
                heuristic = math.dist(polygons[neighbour].center, target)
                heapq.heappush(open_set, (candidate + heuristic, neighbour))
        return ()

    def _walkable_transition(self, first, second) -> bool:
        """Require a polygon link to stay below the live walkable slope.

        Detour adjacency describes generated topology, but it can still
        expose a cliff-like ground link that the Retail character controller
        cannot climb. This only removes unsupported graph edges; it never
        invents a detour or world coordinate.
        """
        horizontal = math.hypot(second[0]-first[0], second[2]-first[2])
        if horizontal <= 1e-6:
            return abs(second[1]-first[1]) <= 1e-6
        return abs(second[1]-first[1]) <= horizontal * self._max_walkable_slope_ratio

    @classmethod
    def _string_pull(cls, chain, polygons, portals, start, destination):
        """Return corridor corners with the standard simple-stupid funnel.

        Detour polygons are convex. Shared edges therefore form portals whose
        funnel yields a collision-free shortest polyline inside the selected
        corridor, avoiding the robotic turn at every polygon midpoint.
        """
        corridor = [(start, start)]
        for current, following in zip(chain, chain[1:]):
            edge = portals.get((current, following))
            if edge is None:
                point = polygons[following].center
                corridor.append((point, point))
                continue
            first, second = edge
            source, target = polygons[current].center, polygons[following].center
            midpoint = tuple((first[axis]+second[axis])*.5 for axis in range(3))
            direction = (target[0]-source[0], target[2]-source[2])
            first_side = (direction[0]*(first[2]-midpoint[2])
                          - direction[1]*(first[0]-midpoint[0]))
            # Detour's X/Z plane is opposite-handed to the WoW X/Y view used
            # by the controller; a positive side is therefore the right
            # endpoint for the funnel's (left, right) convention.
            corridor.append((second, first) if first_side >= 0 else (first, second))
        corridor.append((destination, destination))
        apex = left = right = start
        apex_index = left_index = right_index = 0
        result = [start]
        index = 1
        while index < len(corridor):
            next_left, next_right = corridor[index]
            if cls._triangle_area(apex, right, next_right) <= 0.:
                if cls._same_point(apex, right) or cls._triangle_area(apex, left, next_right) > 0.:
                    right, right_index = next_right, index
                else:
                    result.append(left)
                    apex, apex_index = left, left_index
                    left = right = apex
                    left_index = right_index = apex_index
                    index = apex_index + 1
                    continue
            if cls._triangle_area(apex, left, next_left) >= 0.:
                if cls._same_point(apex, left) or cls._triangle_area(apex, right, next_left) < 0.:
                    left, left_index = next_left, index
                else:
                    result.append(right)
                    apex, apex_index = right, right_index
                    left = right = apex
                    left_index = right_index = apex_index
                    index = apex_index + 1
                    continue
            index += 1
        if not cls._same_point(result[-1], destination):
            result.append(destination)
        return cls._remove_collinear(result)

    @staticmethod
    def _triangle_area(first, second, third) -> float:
        return ((second[0]-first[0])*(third[2]-first[2])
                - (third[0]-first[0])*(second[2]-first[2]))

    @staticmethod
    def _same_point(first, second) -> bool:
        return ((first[0]-second[0])**2 + (first[2]-second[2])**2) < 1e-8

    @staticmethod
    def _remove_collinear(points: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
        if len(points) < 3:
            return points
        result = [points[0]]
        for current, following in zip(points[1:-1], points[2:]):
            previous = result[-1]
            ax, az = current[0]-previous[0], current[2]-previous[2]
            bx, bz = following[0]-current[0], following[2]-current[2]
            cross = abs(ax*bz-az*bx)
            scale = max(1., math.hypot(ax, az)*math.hypot(bx, bz))
            if cross/scale > .015:
                result.append(current)
        result.append(points[-1])
        return result

    @staticmethod
    def _world_to_detour(point: dict) -> tuple[float, float, float] | None:
        try:
            x, y, z = float(point["x"]), float(point["y"]), float(point.get("z", 0.))
        except (KeyError, TypeError, ValueError):
            return None
        if not all(math.isfinite(value) for value in (x, y, z)):
            return None
        return y, z, x

    @staticmethod
    def _detour_to_world(point: tuple[float, float, float], instance_id: int) -> dict:
        return {"x": point[2], "y": point[0], "z": point[1],
                "instance_id": instance_id, "coordinate_space": "WORLD_YARDS",
                "source": "TRINITYCORE_MMAP"}
