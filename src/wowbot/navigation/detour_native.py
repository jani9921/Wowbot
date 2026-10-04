"""Native Recast/Detour routing over the TrinityCore mmaps (ctypes).

Step 2 of docs/NAVIGATION_MULTIRES_LAYERED_DESIGN.md.  Measured 2026-10-03
on Exile's Reach: the Python polygon A* takes 0.8-1.9 s per cold route and
0.2-0.5 s warm, and picks endpoint polygons by 2D distance when Z is
unknown.  Detour (the library the TrinityCore server itself paths with)
answers in milliseconds and finds endpoint polygons inside a 3D box, so
stacked layers (bridge over path, cave under hill: 2.65 % of walkable x,y
bins on 2175) are never mixed.

``native/bin/aipc_detour.dll`` is built from ``native/detour_shim`` with
DT_POLYREF64 (TrinityCore tiles have 16-byte link records).  Without the
DLL, callers keep the Python router.
"""
from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import struct

MMAP_MAGIC = 0x4D4D4150
DLL_PATH = Path(__file__).resolve().parents[3] / "native" / "bin" / "aipc_detour.dll"
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
    lib.aipc_abi.restype = ctypes.c_int
    if lib.aipc_abi() != EXPECTED_ABI:
        raise NativeDetourUnavailable(f"ABI {lib.aipc_abi()} != {EXPECTED_ABI}")
    f3 = ctypes.POINTER(ctypes.c_float)
    lib.aipc_nav_create.restype = ctypes.c_void_p
    lib.aipc_nav_create.argtypes = [f3, ctypes.c_float, ctypes.c_float, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.aipc_nav_destroy.argtypes = [ctypes.c_void_p]
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
    return lib


def _vec(values) -> ctypes.Array:
    return (ctypes.c_float * 3)(*values)


class NativeDetourMap:
    """One map's Detour navmesh with every mmtile of that map loaded."""

    def __init__(self, lib, source, instance_id: int) -> None:
        self.lib, self.instance_id = lib, int(instance_id)
        header = source.read(f"{self.instance_id:04d}.mmap")
        magic, _version = struct.unpack_from("<2I", header)
        if magic != MMAP_MAGIC:
            raise NativeDetourUnavailable("bad .mmap header")
        origin = struct.unpack_from("<3f", header, 8)
        tile_width, tile_height = struct.unpack_from("<2f", header, 20)
        max_tiles, max_polys = struct.unpack_from("<2i", header, 28)
        self.handle = lib.aipc_nav_create(_vec(origin), tile_width, tile_height,
                                          max_tiles, max_polys, 65535)
        if not self.handle:
            raise NativeDetourUnavailable("dtNavMesh init failed")
        prefix = f"{self.instance_id:04d}_"
        self.tiles = self.failed_tiles = 0
        for name in sorted(source.names(prefix, ".mmtile")):
            data = source.read(name)
            if len(data) < 20:
                continue
            tile_magic, _mv, _dv, size, _liquids = struct.unpack_from("<5I", data)
            if tile_magic != MMAP_MAGIC or size + 20 > len(data):
                self.failed_tiles += 1
                continue
            status = lib.aipc_nav_add_tile(self.handle, data[20:20 + size], size)
            if status & STATUS_SUCCESS:
                self.tiles += 1
            else:
                self.failed_tiles += 1

    def close(self) -> None:
        if self.handle:
            self.lib.aipc_nav_destroy(self.handle)
            self.handle = None

    def find_path(self, start: tuple, end: tuple, *, extents: tuple, include: int,
                  exclude: int = 0) -> tuple[int, list[tuple[float, float, float]], int, tuple[int, int]]:
        points = (ctypes.c_float * (MAX_POINTS * 3))()
        count, poly_count = ctypes.c_int(0), ctypes.c_int(0)
        refs = (ctypes.c_ulonglong * 2)()
        code = self.lib.aipc_nav_find_path(
            self.handle, _vec(start), _vec(end), _vec(extents), include, exclude, MAX_POLYS,
            points, MAX_POINTS, ctypes.byref(count), ctypes.byref(poly_count), refs)
        corners = [(points[3 * i], points[3 * i + 1], points[3 * i + 2]) for i in range(count.value)]
        return code, corners, poly_count.value, (refs[0], refs[1])

    def nearest(self, position: tuple, *, extents: tuple, include: int,
                exclude: int = 0) -> tuple[int, tuple[float, float, float]] | None:
        ref = ctypes.c_ulonglong(0)
        point = (ctypes.c_float * 3)()
        if not self.lib.aipc_nav_nearest(self.handle, _vec(position), _vec(extents), include,
                                         exclude, ctypes.byref(ref), point):
            return None
        return ref.value, (point[0], point[1], point[2])


def path_cost(points) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))
