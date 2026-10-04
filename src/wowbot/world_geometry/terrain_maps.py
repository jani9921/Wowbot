"""Bounded, read-only reader for TrinityCore ``maps/*.map`` terrain tiles.

The binary layout and interpolation deliberately mirror TrinityCore's
``MapDefines.h`` and ``GridMap.cpp``.  MAPS is terrain/liquid evidence; it is
not a path planner and never owns input.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
from pathlib import Path
import struct


MAP_MAGIC = b"MAPS"
MAP_VERSION = 10
HEIGHT_MAGIC = b"MHGT"
LIQUID_MAGIC = b"MLIQ"
SIZE_OF_GRIDS = 533.3333
MAP_RESOLUTION = 128
CENTER_GRID_ID = 32
INVALID_HEIGHT = -100000.0

HEIGHT_NO_HEIGHT = 0x01
HEIGHT_AS_INT16 = 0x02
HEIGHT_AS_INT8 = 0x04
LIQUID_NO_TYPE = 0x01
LIQUID_NO_HEIGHT = 0x02


@dataclass(frozen=True, slots=True)
class TerrainSample:
    instance_id: int
    tile_x: int
    tile_y: int
    terrain_z: float | None
    liquid_z: float | None
    liquid_type: int
    liquid_flags: int
    is_hole: bool
    source: str = "TRINITYCORE_MAPS"

    @property
    def has_liquid(self) -> bool:
        return self.liquid_flags != 0 and self.liquid_z is not None

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "tile_x": self.tile_x,
            "tile_y": self.tile_y,
            "terrain_z": self.terrain_z,
            "liquid_z": self.liquid_z,
            "liquid_type": self.liquid_type,
            "liquid_flags": self.liquid_flags,
            "has_liquid": self.has_liquid,
            "is_hole": self.is_hole,
            "source": self.source,
        }


@dataclass(slots=True)
class _TerrainTile:
    tile_x: int
    tile_y: int
    grid_height: float
    grid_max_height: float
    height_flags: int
    v9: tuple[float | int, ...] | None
    v8: tuple[float | int, ...] | None
    holes: bytes | None
    liquid_level: float | None
    liquid_flags_global: int
    liquid_type_global: int
    liquid_off_x: int
    liquid_off_y: int
    liquid_width: int
    liquid_height: int
    liquid_entries: tuple[int, ...] | None
    liquid_flags: bytes | None
    liquid_map: tuple[float, ...] | None

    def _indices(self, world_x: float, world_y: float) -> tuple[int, int, float, float]:
        gx = MAP_RESOLUTION * (CENTER_GRID_ID - world_x / SIZE_OF_GRIDS)
        gy = MAP_RESOLUTION * (CENTER_GRID_ID - world_y / SIZE_OF_GRIDS)
        gx_int = int(gx)
        gy_int = int(gy)
        return gx_int & 127, gy_int & 127, gx - gx_int, gy - gy_int

    def is_hole(self, row: int, col: int) -> bool:
        if self.holes is None:
            return False
        cell_row, cell_col = row // 8, col // 8
        hole_row, hole_col = row % 8, col % 8
        return bool(self.holes[cell_row * 16 * 8 + cell_col * 8 + hole_row] & (1 << hole_col))

    def terrain_height(self, world_x: float, world_y: float) -> tuple[float | None, bool]:
        row, col, x, y = self._indices(world_x, world_y)
        hole = self.is_hole(row, col)
        if hole:
            return None, True
        if self.v8 is None or self.v9 is None:
            return float(self.grid_height), False
        p = row * 129 + col
        q = row * 128 + col
        if x + y < 1.0:
            if x > y:
                h1, h2, h5 = self.v9[p], self.v9[p + 129], 2 * self.v8[q]
                a, b, c = h2 - h1, h5 - h1 - h2, h1
            else:
                h1, h3, h5 = self.v9[p], self.v9[p + 1], 2 * self.v8[q]
                a, b, c = h5 - h1 - h3, h3 - h1, h1
        elif x > y:
            h2, h4, h5 = self.v9[p + 129], self.v9[p + 130], 2 * self.v8[q]
            a, b, c = h2 + h4 - h5, h4 - h2, h5 - h4
        else:
            h3, h4, h5 = self.v9[p + 1], self.v9[p + 130], 2 * self.v8[q]
            a, b, c = h4 - h3, h3 + h4 - h5, h5 - h4
        value = float(a * x + b * y + c)
        if self.height_flags & HEIGHT_AS_INT16:
            value = value * ((self.grid_max_height - self.grid_height) / 65535.0) + self.grid_height
        elif self.height_flags & HEIGHT_AS_INT8:
            value = value * ((self.grid_max_height - self.grid_height) / 255.0) + self.grid_height
        return value, False

    def liquid_at(self, world_x: float, world_y: float) -> tuple[float | None, int, int]:
        row, col, _, _ = self._indices(world_x, world_y)
        cell_index = (row >> 3) * 16 + (col >> 3)
        flags = self.liquid_flags[cell_index] if self.liquid_flags is not None else self.liquid_flags_global
        entry = self.liquid_entries[cell_index] if self.liquid_entries is not None else self.liquid_type_global
        if flags == 0:
            return None, int(entry), int(flags)
        if self.liquid_map is None:
            return self.liquid_level, int(entry), int(flags)
        # This intentionally follows GridMap::getLiquidLevel; the extracted
        # header's X/Y offsets are transposed relative to the array axes.
        liquid_row = row - self.liquid_off_y
        liquid_col = col - self.liquid_off_x
        if not (0 <= liquid_row < self.liquid_height and 0 <= liquid_col < self.liquid_width):
            return None, int(entry), int(flags)
        return float(self.liquid_map[liquid_row * self.liquid_width + liquid_col]), int(entry), int(flags)


class MapDataSource:
    """Resolve either a Retail root directory or its ``maps`` directory."""

    def __init__(self, path: str | Path):
        root = Path(path).expanduser().resolve()
        maps = root / "maps" if (root / "maps").is_dir() else root
        if not maps.is_dir():
            raise FileNotFoundError(maps)
        self.root = root
        self.maps = maps

    def tile_path(self, instance_id: int, tile_x: int, tile_y: int) -> Path:
        return self.maps / f"{int(instance_id):04d}_{int(tile_x):02d}_{int(tile_y):02d}.map"


class TrinityMapTerrain:
    """Lazy MAPS height/liquid sampler with a strict bounded tile cache."""

    def __init__(self, source: str | Path, *, max_cached_tiles: int = 12):
        self.source = MapDataSource(source)
        self.max_cached_tiles = max(1, int(max_cached_tiles))
        self._cache: OrderedDict[tuple[int, int, int], _TerrainTile] = OrderedDict()
        self.last_diagnostics: dict = {"available": True, "source": str(self.source.maps)}

    @staticmethod
    def world_tile(world_x: float, world_y: float) -> tuple[int, int] | None:
        if not all(math.isfinite(float(v)) for v in (world_x, world_y)):
            return None
        tile_x = int(CENTER_GRID_ID - float(world_x) / SIZE_OF_GRIDS)
        tile_y = int(CENTER_GRID_ID - float(world_y) / SIZE_OF_GRIDS)
        if not (0 <= tile_x < 64 and 0 <= tile_y < 64):
            return None
        return tile_x, tile_y

    def sample(self, instance_id: int, world_x: float, world_y: float) -> TerrainSample | None:
        coords = self.world_tile(world_x, world_y)
        if coords is None:
            self.last_diagnostics = {"available": False, "reason": "invalid_world_xy"}
            return None
        tile = self._load_tile(int(instance_id), *coords)
        if tile is None:
            return None
        terrain_z, hole = tile.terrain_height(float(world_x), float(world_y))
        liquid_z, liquid_type, liquid_flags = tile.liquid_at(float(world_x), float(world_y))
        sample = TerrainSample(int(instance_id), coords[0], coords[1], terrain_z,
                               liquid_z, liquid_type, liquid_flags, hole)
        self.last_diagnostics = {"available": True, "reason": "sampled", **sample.to_dict()}
        return sample

    def _load_tile(self, instance_id: int, tile_x: int, tile_y: int) -> _TerrainTile | None:
        key = (instance_id, tile_x, tile_y)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        path = self.source.tile_path(*key)
        if not path.is_file():
            self.last_diagnostics = {"available": False, "reason": "tile_missing",
                                     "instance_id": instance_id, "tile": (tile_x, tile_y)}
            return None
        try:
            tile = self._parse_tile(path.read_bytes(), tile_x, tile_y)
        except (ValueError, struct.error) as exc:
            self.last_diagnostics = {"available": False, "reason": "invalid_tile",
                                     "path": str(path), "error": str(exc)}
            return None
        self._cache[key] = tile
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_cached_tiles:
            self._cache.popitem(last=False)
        return tile

    @staticmethod
    def _parse_tile(data: bytes, tile_x: int, tile_y: int) -> _TerrainTile:
        if len(data) < 44:
            raise ValueError("short MAPS header")
        (magic, version, _build, area_off, area_size, height_off, height_size,
         liquid_off, liquid_size, holes_off, holes_size) = struct.unpack_from("<4s10I", data)
        if magic != MAP_MAGIC or version != MAP_VERSION:
            raise ValueError(f"unsupported MAPS header {magic!r} v{version}")
        for offset, size in ((area_off, area_size), (height_off, height_size),
                             (liquid_off, liquid_size), (holes_off, holes_size)):
            if offset and (offset < 44 or size < 0 or offset + size > len(data)):
                raise ValueError("section outside MAPS file")

        grid_height = grid_max_height = INVALID_HEIGHT
        height_flags = HEIGHT_NO_HEIGHT
        v9 = v8 = None
        if height_off:
            magic_h, height_flags, grid_height, grid_max_height = struct.unpack_from("<4sIff", data, height_off)
            if magic_h != HEIGHT_MAGIC:
                raise ValueError("invalid MHGT magic")
            cursor = height_off + 16
            if not height_flags & HEIGHT_NO_HEIGHT:
                if height_flags & HEIGHT_AS_INT16:
                    v9 = struct.unpack_from(f"<{129*129}H", data, cursor)
                    cursor += 129 * 129 * 2
                    v8 = struct.unpack_from(f"<{128*128}H", data, cursor)
                elif height_flags & HEIGHT_AS_INT8:
                    v9 = tuple(data[cursor:cursor + 129 * 129])
                    cursor += 129 * 129
                    v8 = tuple(data[cursor:cursor + 128 * 128])
                else:
                    v9 = struct.unpack_from(f"<{129*129}f", data, cursor)
                    cursor += 129 * 129 * 4
                    v8 = struct.unpack_from(f"<{128*128}f", data, cursor)

        (liquid_level, liquid_flags_global, liquid_type_global, liquid_off_x,
         liquid_off_y, liquid_width, liquid_height, liquid_entries,
         liquid_flags, liquid_map) = (None, 0, 0, 0, 0, 0, 0, None, None, None)
        if liquid_off:
            values = struct.unpack_from("<4sBBHBBBBf", data, liquid_off)
            if values[0] != LIQUID_MAGIC:
                raise ValueError("invalid MLIQ magic")
            _, flags, liquid_flags_global, liquid_type_global, liquid_off_x, liquid_off_y, liquid_width, liquid_height, liquid_level = values
            cursor = liquid_off + 16
            if not flags & LIQUID_NO_TYPE:
                liquid_entries = struct.unpack_from("<256H", data, cursor)
                cursor += 512
                liquid_flags = data[cursor:cursor + 256]
                cursor += 256
            if not flags & LIQUID_NO_HEIGHT:
                count = liquid_width * liquid_height
                liquid_map = struct.unpack_from(f"<{count}f", data, cursor)

        holes = data[holes_off:holes_off + holes_size] if holes_off and holes_size else None
        if holes is not None and len(holes) != 16 * 16 * 8:
            raise ValueError("unsupported holes section size")
        return _TerrainTile(tile_x, tile_y, float(grid_height), float(grid_max_height),
                            int(height_flags), v9, v8, holes, liquid_level,
                            int(liquid_flags_global), int(liquid_type_global),
                            int(liquid_off_x), int(liquid_off_y), int(liquid_width),
                            int(liquid_height), liquid_entries, liquid_flags, liquid_map)
