"""Native Recast/Detour routing over the TrinityCore mmaps (ctypes).

Step 2 of docs/NAVIGATION_MULTIRES_LAYERED_DESIGN.md.  Measured 2026-10-03
on Exile's Reach: the Python polygon A* takes 0.8-1.9 s per cold route and
0.2-0.5 s warm, and picks endpoint polygons by 2D distance when Z is
unknown.  Detour (the library the TrinityCore server itself paths with)
answers in milliseconds and finds endpoint polygons inside a 3D box, so
stacked layers (bridge over path, cave under hill: 2.65 % of walkable x,y
bins on 2175) are never mixed.

``native/bin/aipc_detour_walking_v2.dll`` is built from ``native/detour_shim`` with
DT_POLYREF64 (TrinityCore tiles have 16-byte link records).  v2 (2026-10-22)
adds wadeable-liquid queries and costs; a v1 DLL still routes on land.
Without either DLL, callers keep the Python router.
"""
from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import struct
from zipfile import BadZipFile

from .mmap_format import MMapFormatError, map_parameters, tile_mesh

MMAP_MAGIC = 0x4D4D4150
_BIN = Path(__file__).resolve().parents[3] / "native" / "bin"
# A new name per ABI-compatible feature step: a running agent keeps the old
# DLL loaded (and locked) while the next one is built beside it.
DLL_CANDIDATES = (_BIN / "aipc_detour_walking_v3.dll", _BIN / "aipc_detour_walking_v2.dll",
                  _BIN / "aipc_detour_walking_v1.dll")
DLL_PATH = next((path for path in DLL_CANDIDATES if path.is_file()), DLL_CANDIDATES[0])
EXPECTED_ABI = 100 * 8 + 7          # 64-bit dtPolyRef, DT_NAVMESH_VERSION 7
MAX_POINTS = 2048
MAX_POLYS = 16384
STATUS_SUCCESS = 0x40000000


class NativeDetourUnavailable(RuntimeError):
    pass


def load_library(path: Path = DLL_PATH):
    if os.environ.get("AIPC_NATIVE_DETOUR", "1").strip().lower() in {"0", "false", "off", "no"}:
        raise NativeDetourUnavailable("disabled by AIPC_NATIVE_DETOUR")
    if not Path(path).is_file():
        raise NativeDetourUnavailable(f"missing {path}")
    lib = ctypes.CDLL(str(path))
    lib._aipc_dll_name = Path(path).name
    lib.aipc_abi.restype = ctypes.c_int
    if lib.aipc_abi() != EXPECTED_ABI:
        raise NativeDetourUnavailable(f"ABI {lib.aipc_abi()} != {EXPECTED_ABI}")
    f3 = ctypes.POINTER(ctypes.c_float)
    lib.aipc_nav_create.restype = ctypes.c_void_p
    lib.aipc_nav_create.argtypes = [f3, ctypes.c_float, ctypes.c_float, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.aipc_nav_destroy.argtypes = [ctypes.c_void_p]
    if hasattr(lib, "aipc_nav_walking_policy"):
        lib.aipc_nav_walking_policy.restype = ctypes.c_int
        lib.aipc_nav_walking_policy.argtypes = [ctypes.c_void_p, ctypes.c_float]
    lib.aipc_nav_add_tile.restype = ctypes.c_uint
    lib.aipc_nav_add_tile.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    lib.aipc_nav_nearest.restype = ctypes.c_int
    lib.aipc_nav_nearest.argtypes = [ctypes.c_void_p, f3, f3, ctypes.c_ushort, ctypes.c_ushort,
                                     ctypes.POINTER(ctypes.c_ulonglong), f3]
    lib.aipc_nav_find_path.restype = ctypes.c_int
    lib.aipc_nav_find_path.argtypes = [ctypes.c_void_p, f3, f3, f3, ctypes.c_ushort, ctypes.c_ushort,
                                       ctypes.c_int, f3, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
                                       ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulonglong)]
    lib.aipc_nav_poly_height.restype = ctypes.c_int
    lib.aipc_nav_poly_height.argtypes = [ctypes.c_void_p, ctypes.c_ulonglong, f3, f3]
    # 2026-10-06: a path along the middle of the walkway (user: "the
    # character walked down along the cave wall and fell off the spiral").
    if hasattr(lib, "aipc_nav_find_path_centered"):
        lib.aipc_nav_find_path_centered.restype = ctypes.c_int
        lib.aipc_nav_find_path_centered.argtypes = [
            ctypes.c_void_p, f3, f3, f3, ctypes.c_ushort, ctypes.c_ushort, ctypes.c_int, ctypes.c_float,
            f3, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulonglong)]
    # 2026-10-22 (v2): wadeable liquid polygons (user: shallow lava/water
    # may be crossed where the feet reach the floor; never swum).
    if hasattr(lib, "aipc_nav_liquid_costs"):
        lib.aipc_nav_liquid_costs.restype = ctypes.c_int
        lib.aipc_nav_liquid_costs.argtypes = [ctypes.c_void_p, ctypes.c_float, ctypes.c_float]
    if hasattr(lib, "aipc_nav_polys_with_flags"):
        lib.aipc_nav_polys_with_flags.restype = ctypes.c_int
        lib.aipc_nav_polys_with_flags.argtypes = [
            ctypes.c_void_p, f3, f3, ctypes.c_ushort, ctypes.POINTER(ctypes.c_ulonglong),
            ctypes.POINTER(ctypes.c_ushort), ctypes.POINTER(ctypes.c_ubyte), f3, ctypes.c_int]
    if hasattr(lib, "aipc_nav_add_poly_flags"):
        lib.aipc_nav_add_poly_flags.restype = ctypes.c_int
        lib.aipc_nav_add_poly_flags.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong), ctypes.c_int, ctypes.c_ushort]
    # 2026-10-06 (Z resolver): layer and polygon queries; an older DLL lacks them.
    for name in ("aipc_nav_layers_at", "aipc_nav_polys_near"):
        if hasattr(lib, name):
            function = getattr(lib, name)
            function.restype = ctypes.c_int
            function.argtypes = [ctypes.c_void_p, f3, f3, ctypes.c_ushort, ctypes.c_ushort,
                                 f3, ctypes.POINTER(ctypes.c_ulonglong), ctypes.c_int]
    return lib


def _vec(values) -> ctypes.Array:
    return (ctypes.c_float * 3)(*values)


class NativeDetourMap:
    """One map's Detour navmesh with every mmtile of that map loaded."""

    def __init__(self, lib, source, instance_id: int) -> None:
        self.lib, self.instance_id = lib, int(instance_id)
        header = source.read(f"{self.instance_id:04d}.mmap")
        origin,tile_width,tile_height,max_tiles,max_polys = map_parameters(header)
        self.handle = lib.aipc_nav_create(_vec(origin), tile_width, tile_height,
                                          max_tiles, max_polys, 65535)
        if not self.handle:
            raise NativeDetourUnavailable("dtNavMesh init failed")
        prefix = f"{self.instance_id:04d}_"
        self.tiles = self.failed_tiles = 0
        self.data_errors = []
        for name in sorted(source.names(prefix, ".mmtile")):
            try:
                mesh,_header = tile_mesh(source.read(name),for_native=True)
            except (MMapFormatError, OSError, BadZipFile) as error:
                self.failed_tiles += 1
                if len(self.data_errors) < 16:
                    diagnostic = (error.diagnostic() if isinstance(error,MMapFormatError)
                                  else {'geometry_status':'ERROR','reason':'tile_read_failed'})
                    self.data_errors.append({**diagnostic,'tile':name})
                continue
            status = lib.aipc_nav_add_tile(self.handle, bytes(mesh), len(mesh))
            if status & STATUS_SUCCESS:
                self.tiles += 1
            else:
                self.failed_tiles += 1
                if len(self.data_errors) < 16:
                    self.data_errors.append({'geometry_status':'ERROR','reason':'native_tile_rejected',
                                             'tile':name})

    def close(self) -> None:
        if self.handle:
            self.lib.aipc_nav_destroy(self.handle)
            self.handle = None

    def find_path(self, start: tuple, end: tuple, *, extents: tuple, include: int,
                  exclude: int = 0, margin: float | None = None,
                  ) -> tuple[int, list[tuple[float, float, float]], int, tuple[int, int]]:
        points = (ctypes.c_float * (MAX_POINTS * 3))()
        count, poly_count = ctypes.c_int(0), ctypes.c_int(0)
        refs = (ctypes.c_ulonglong * 2)()
        if margin is not None and hasattr(self.lib, "aipc_nav_find_path_centered"):
            code = self.lib.aipc_nav_find_path_centered(
                self.handle, _vec(start), _vec(end), _vec(extents), include, exclude, MAX_POLYS,
                float(margin), points, MAX_POINTS, ctypes.byref(count), ctypes.byref(poly_count), refs)
        else:
            code = self.lib.aipc_nav_find_path(
                self.handle, _vec(start), _vec(end), _vec(extents), include, exclude, MAX_POLYS,
                points, MAX_POINTS, ctypes.byref(count), ctypes.byref(poly_count), refs)
        corners = [(points[3 * i], points[3 * i + 1], points[3 * i + 2]) for i in range(count.value)]
        return code, corners, poly_count.value, (refs[0], refs[1])

    def set_walking_policy(self, max_slope_degrees: float) -> bool:
        """Only an explicitly capable DLL may claim native slope enforcement."""
        setter = getattr(self.lib, "aipc_nav_walking_policy", None)
        return bool(setter and setter(self.handle, float(max_slope_degrees)))

    def nearest(self, position: tuple, *, extents: tuple, include: int,
                exclude: int = 0) -> tuple[int, tuple[float, float, float]] | None:
        ref = ctypes.c_ulonglong(0)
        point = (ctypes.c_float * 3)()
        if not self.lib.aipc_nav_nearest(self.handle, _vec(position), _vec(extents), include,
                                         exclude, ctypes.byref(ref), point):
            return None
        return ref.value, (point[0], point[1], point[2])

    @property
    def has_structure_costs(self) -> bool:
        """v3 (2026-10-23): NAV_STRUCTURE polygons pay a quarter of the slope cost."""
        return getattr(self.lib, "_aipc_dll_name", "").endswith("_v3.dll") and self.has_liquid_wading

    @property
    def has_liquid_wading(self) -> bool:
        return all(hasattr(self.lib, name) for name in (
            "aipc_nav_liquid_costs", "aipc_nav_polys_with_flags", "aipc_nav_add_poly_flags"))

    def set_liquid_costs(self, water: float, magma_slime: float) -> bool:
        setter = getattr(self.lib, "aipc_nav_liquid_costs", None)
        return bool(setter and setter(self.handle, float(water), float(magma_slime)))

    def polys_with_flags(self, bmin: tuple, bmax: tuple, mask: int, *, limit: int = 4096,
                         ) -> list[tuple[int, int, list[tuple[float, float, float]]]]:
        """(ref, flags, vertices) of the ground polygons with ``mask`` flags
        whose X/Z bounds overlap a Detour box; heights are ignored."""
        while True:
            refs = (ctypes.c_ulonglong * limit)()
            flags = (ctypes.c_ushort * limit)()
            counts = (ctypes.c_ubyte * limit)()
            verts = (ctypes.c_float * (limit * 18))()
            found = self.lib.aipc_nav_polys_with_flags(self.handle, _vec(bmin), _vec(bmax), int(mask),
                                                       refs, flags, counts, verts, limit)
            if found <= limit:
                break
            limit = found
        return [(refs[i], flags[i], [(verts[(i*6+v)*3], verts[(i*6+v)*3+1], verts[(i*6+v)*3+2])
                                     for v in range(counts[i])])
                for i in range(found)]

    def add_poly_flags(self, refs, flags: int) -> int:
        refs = list(refs)
        if not refs:
            return 0
        array = (ctypes.c_ulonglong * len(refs))(*refs)
        return int(self.lib.aipc_nav_add_poly_flags(self.handle, array, len(refs), int(flags)))

    @property
    def has_layer_queries(self) -> bool:
        return hasattr(self.lib, "aipc_nav_layers_at") and hasattr(self.lib, "aipc_nav_polys_near")

    def layers_at(self, position: tuple, *, extents: tuple, include: int,
                  exclude: int = 0, limit: int = 64) -> list[tuple[float, int]]:
        """(height, polygon ref) of every walkable layer at a Detour position."""
        heights = (ctypes.c_float * limit)()
        refs = (ctypes.c_ulonglong * limit)()
        count = self.lib.aipc_nav_layers_at(self.handle, _vec(position), _vec(extents), include,
                                            exclude, heights, refs, limit)
        return [(heights[i], refs[i]) for i in range(count)]

    def polys_near(self, center: tuple, *, extents: tuple, include: int,
                   exclude: int = 0, limit: int = 2048) -> list[tuple[int, tuple[float, float, float]]]:
        """(polygon ref, centre) of the walkable polygons in a box (Detour coordinates)."""
        points = (ctypes.c_float * (3 * limit))()
        refs = (ctypes.c_ulonglong * limit)()
        count = self.lib.aipc_nav_polys_near(self.handle, _vec(center), _vec(extents), include,
                                             exclude, points, refs, limit)
        return [(refs[i], (points[3*i], points[3*i+1], points[3*i+2])) for i in range(count)]


def path_cost(points) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))
