"""Read-only TrinityCore VMAP (``VMAP_4.E``) collision reader: vertical surfaces.

User 2026-10-06 (Z resolver): "VMAP vertical raycast ... gyűjtsük össze az
összes collision surface Z-jét" -- roofs, bridges, ground and cave floors
under/over one X/Y, each to be validated against the navmesh.

Layout (TrinityCore master, extracted from the Retail client):
``vmaps/<map>/<map>_<tx>_<ty>.vmtile``
    magic, uint32 count, then model spawns: uint8 flags, uint8 adtId,
    uint32 id, float pos[3], rot[3] (degrees), scale, [bound lo[3], hi[3]
    when flags & 1], uint32 name length, name.
``vmaps/<name>.vmo``
    magic, ``WMOD`` (uint32 size, root id, flags), ``GMOD`` uint32 count, and
    per group: bound[6], mogp flags, group id, ``VERT`` (size, count,
    float[3]*count), ``TRIM`` (size, count, uint32[3]*count), ``MBIH``
    (a BIH tree, skipped), ``LIQU`` (size, data, skipped).

Positions are in TrinityCore's internal frame: (mid - x, mid - y, z) with
mid = 32 * 533.33333 (VMapManager2::convertPositionToInternalRep).  A model
transform is pos + R * scale * p, R = Rz(rot.y) Ry(rot.x) Rx(rot.z)
(ModelInstance).  Rays are tested against every triangle with numpy, both
faces (TrinityCore's IntersectTriangle uses |det|); no BIH is needed for
one vertical line.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
from pathlib import Path
import struct

import numpy as np

MAGIC = b"VMAP_4.E"
GRID_SIZE = 533.3333333333
MID = 32. * GRID_SIZE
FLAG_HAS_BOUND = 1


@dataclass(frozen=True)
class Spawn:
    flags: int
    model: str
    position: np.ndarray        # internal frame
    rotation: np.ndarray        # degrees
    scale: float
    bound_lo: np.ndarray | None
    bound_hi: np.ndarray | None

    def holds_xy(self, ix: float, iy: float) -> bool:
        if self.bound_lo is None:
            return True
        return bool(self.bound_lo[0] <= ix <= self.bound_hi[0] and self.bound_lo[1] <= iy <= self.bound_hi[1])


@dataclass(frozen=True)
class Group:
    lo: np.ndarray
    hi: np.ndarray
    a: np.ndarray               # triangle corners, (n, 3) each
    b: np.ndarray
    c: np.ndarray


def _rotation(degrees: np.ndarray) -> np.ndarray:
    """G3D Matrix3::fromEulerAnglesZYX(pi*rot.y/180, pi*rot.x/180, pi*rot.z/180)."""
    yaw, pitch, roll = (math.radians(float(degrees[1])), math.radians(float(degrees[0])),
                        math.radians(float(degrees[2])))
    cz, sz, cy, sy, cx, sx = (math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch),
                              math.cos(roll), math.sin(roll))
    rz = np.array([[cz, -sz, 0.], [sz, cz, 0.], [0., 0., 1.]])
    ry = np.array([[cy, 0., sy], [0., 1., 0.], [-sy, 0., cy]])
    rx = np.array([[1., 0., 0.], [0., cx, -sx], [0., sx, cx]])
    return rz @ (ry @ rx)


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.at = data, 0

    def take(self, size: int) -> bytes:
        chunk = self.data[self.at:self.at+size]
        if len(chunk) != size:
            raise ValueError("truncated vmap file")
        self.at += size
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def floats(self, count: int) -> np.ndarray:
        return np.frombuffer(self.take(4*count), dtype="<f4").astype(np.float64)

    def expect(self, tag: bytes) -> None:
        if self.take(len(tag)) != tag:
            raise ValueError(f"vmap chunk {tag!r} expected")

    def skip_bih(self) -> None:
        self.take(24)                                   # bounds
        self.take(4*self.u32())                         # tree
        self.take(4*self.u32())                         # object indices


class TrinityVMaps:
    """Vertical collision surfaces at one world X/Y (all floors, roofs, bridges)."""

    def __init__(self, root: str | Path, *, max_cached_models: int = 256, max_cached_tiles: int = 16):
        self.root = Path(root)
        self._models: OrderedDict[str, tuple[Group, ...]] = OrderedDict()
        self._tiles: OrderedDict[tuple[int, int, int], tuple[Spawn, ...]] = OrderedDict()
        self.max_cached_models, self.max_cached_tiles = max_cached_models, max_cached_tiles
        self.last_diagnostics: dict = {"available": self.root.is_dir()}

    @staticmethod
    def internal(x: float, y: float) -> tuple[float, float]:
        return MID - float(x), MID - float(y)

    @staticmethod
    def tile_of(x: float, y: float) -> tuple[int, int]:
        return math.floor(32. - float(x)/GRID_SIZE), math.floor(32. - float(y)/GRID_SIZE)

    def surfaces_at(self, map_id: int, x: float, y: float, *, top: float = 2000.,
                    bottom: float = -2000.) -> list[float]:
        """Every collision surface height on the vertical line (x, y) between
        ``bottom`` and ``top``, highest first."""
        ix, iy = self.internal(x, y)
        spawns = self._tile(int(map_id), *self.tile_of(x, y))
        heights: list[float] = []
        for spawn in spawns:
            if not spawn.holds_xy(ix, iy):
                continue
            if spawn.bound_lo is not None and (spawn.bound_hi[2] < bottom or spawn.bound_lo[2] > top):
                continue
            heights.extend(self._model_hits(spawn, ix, iy, top, bottom))
        result = sorted({round(float(height), 2) for height in heights if bottom <= height <= top}, reverse=True)
        self.last_diagnostics = {"available": True, "map_id": int(map_id), "spawns": len(spawns),
                                 "surfaces": len(result)}
        return result

    def _model_hits(self, spawn: Spawn, ix: float, iy: float, top: float, bottom: float) -> list[float]:
        groups = self._model(spawn.model)
        if not groups:
            return []
        rotation = _rotation(spawn.rotation)
        inverse = rotation.T
        origin = np.array([ix, iy, top])
        local_origin = inverse @ (origin - spawn.position) / spawn.scale
        local_dir = inverse @ np.array([0., 0., -1.])
        length = (top - bottom) / spawn.scale
        hits: list[float] = []
        for group in groups:
            if not _ray_hits_box(local_origin, local_dir, length, group.lo, group.hi):
                continue
            for t in _ray_triangles(local_origin, local_dir, group.a, group.b, group.c):
                if 0. <= t <= length:
                    hits.append(top - t*spawn.scale)
        return hits

    # -- files -----------------------------------------------------------------
    def _tile(self, map_id: int, tx: int, ty: int) -> tuple[Spawn, ...]:
        key = (map_id, tx, ty)
        if key in self._tiles:
            self._tiles.move_to_end(key)
            return self._tiles[key]
        path = self.root / f"{map_id:04d}" / f"{map_id:04d}_{tx:02d}_{ty:02d}.vmtile"
        if not path.is_file():
            path = self.root / f"{map_id}" / f"{map_id}_{tx:02d}_{ty:02d}.vmtile"
        spawns: tuple[Spawn, ...] = ()
        if path.is_file():
            spawns = self._parse_tile(path.read_bytes())
        self._tiles[key] = spawns
        while len(self._tiles) > self.max_cached_tiles:
            self._tiles.popitem(last=False)
        return spawns

    @staticmethod
    def _parse_tile(data: bytes) -> tuple[Spawn, ...]:
        reader = _Reader(data)
        reader.expect(MAGIC)
        count = reader.u32()
        spawns = []
        for _ in range(count):
            flags = reader.u8()
            reader.u8()                                  # adt id
            reader.u32()                                 # spawn id
            position, rotation = reader.floats(3), reader.floats(3)
            scale = float(reader.floats(1)[0])
            lo = hi = None
            if flags & FLAG_HAS_BOUND:
                lo, hi = reader.floats(3), reader.floats(3)
            name = reader.take(reader.u32()).decode("ascii", "replace")
            spawns.append(Spawn(flags, name, position, rotation, scale or 1., lo, hi))
        return tuple(spawns)

    def _model(self, name: str) -> tuple[Group, ...]:
        if name in self._models:
            self._models.move_to_end(name)
            return self._models[name]
        path = self.root / f"{name}.vmo"
        groups: tuple[Group, ...] = ()
        if path.is_file():
            try:
                groups = self._parse_model(path.read_bytes())
            except (ValueError, struct.error):
                groups = ()
        self._models[name] = groups
        while len(self._models) > self.max_cached_models:
            self._models.popitem(last=False)
        return groups

    @staticmethod
    def _parse_model(data: bytes) -> tuple[Group, ...]:
        reader = _Reader(data)
        reader.expect(MAGIC)
        reader.expect(b"WMOD")
        reader.take(reader.u32())                        # root id (+ flags)
        if reader.take(4) != b"GMOD":
            return ()
        groups = []
        for _ in range(reader.u32()):
            bound = reader.floats(6)
            reader.u32()                                 # mogp flags
            reader.u32()                                 # group wmo id
            reader.expect(b"VERT")
            reader.u32()
            vertex_count = reader.u32()
            if not vertex_count:
                continue                                 # TrinityCore stops reading this group here
            vertices = reader.floats(3*vertex_count).reshape(-1, 3)
            reader.expect(b"TRIM")
            reader.u32()
            triangle_count = reader.u32()
            triangles = np.frombuffer(reader.take(12*triangle_count), dtype="<u4").reshape(-1, 3)
            reader.expect(b"MBIH")
            reader.skip_bih()
            reader.expect(b"LIQU")
            reader.take(reader.u32())
            if len(triangles) and int(triangles.max()) < len(vertices):
                groups.append(Group(bound[:3], bound[3:], vertices[triangles[:, 0]],
                                    vertices[triangles[:, 1]], vertices[triangles[:, 2]]))
        if reader.at < len(data) and reader.take(4) == b"GBIH":
            pass                                         # group tree: not needed
        return tuple(groups)


def _ray_hits_box(origin, direction, length, lo, hi) -> bool:
    t0, t1 = 0., length
    for axis in range(3):
        if abs(direction[axis]) < 1e-12:
            if origin[axis] < lo[axis] - 1e-4 or origin[axis] > hi[axis] + 1e-4:
                return False
            continue
        near, far = (lo[axis]-origin[axis])/direction[axis], (hi[axis]-origin[axis])/direction[axis]
        if near > far:
            near, far = far, near
        t0, t1 = max(t0, near), min(t1, far)
        if t0 > t1 + 1e-4:
            return False
    return True


def _ray_triangles(origin, direction, a, b, c) -> np.ndarray:
    """Möller-Trumbore, both faces: hit distances of one ray against many triangles."""
    e1, e2 = b - a, c - a
    p = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-9
    inv = np.where(ok, 1./np.where(ok, det, 1.), 0.)
    s = origin - a
    u = np.einsum("ij,ij->i", s, p) * inv
    q = np.cross(s, e1)
    v = (q @ direction) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    hit = ok & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1. + 1e-6)
    return t[hit]
