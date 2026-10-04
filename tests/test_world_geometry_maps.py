from pathlib import Path
import struct

import pytest

from wowbot.world_geometry import TrinityMapTerrain, WorldGeometryService


def _maps_tile(*, ground=100.0, liquid=110.0) -> bytes:
    area = struct.pack("<4sHH", b"AREA", 1, 0)
    height = struct.pack("<4sIff", b"MHGT", 1, ground, ground)
    liquid = (struct.pack("<4sBBHBBBBf", b"MLIQ", 3, 0, 0, 0, 0, 0, 0, -2000.0)
              if liquid is None else
              struct.pack("<4sBBHBBBBf", b"MLIQ", 3, 1, 1, 0, 0, 128, 128, liquid))
    area_off = 44
    height_off = area_off + len(area)
    liquid_off = height_off + len(height)
    header = struct.pack("<4s10I", b"MAPS", 10, 69933,
                         area_off, len(area), height_off, len(height),
                         liquid_off, len(liquid), 0, 0)
    return header + area + height + liquid


def test_maps_reader_returns_flat_terrain_and_liquid(tmp_path: Path):
    (tmp_path / "2175_31_36.map").write_bytes(_maps_tile())
    maps = TrinityMapTerrain(tmp_path)

    sample = maps.sample(2175, 80.88, -2271.34)

    assert sample is not None
    assert (sample.tile_x, sample.tile_y) == (31, 36)
    assert sample.terrain_z == 100.0
    assert sample.liquid_z == 110.0
    assert sample.has_liquid is True


def test_maps_reader_rejects_incompatible_version(tmp_path: Path):
    data = bytearray(_maps_tile())
    struct.pack_into("<I", data, 4, 99)
    (tmp_path / "2175_31_36.map").write_bytes(data)

    assert TrinityMapTerrain(tmp_path).sample(2175, 80.88, -2271.34) is None


class _Navmesh:
    last_surface_projection = {"status": "PROJECTED"}
    last_diagnostics = {"reason": "route_found"}

    def __init__(self):
        self.project_calls = []
        self.path_calls = []

    def supports(self, instance_id):
        return True

    def close(self):
        pass

    def project_position(self, instance_id, point, *, z_hint=None):
        self.project_calls.append((instance_id, point, z_hint))
        return {**point, "z": z_hint, "z_known": True}

    def find_path(self, instance_id, start, destination):
        self.path_calls.append((instance_id, start, destination))
        return "route"


def test_geometry_service_uses_maps_as_z_hint_but_mmaps_as_route_authority(tmp_path: Path):
    (tmp_path / "2175_31_36.map").write_bytes(_maps_tile(ground=98.0, liquid=None))
    navmesh = _Navmesh()
    service = WorldGeometryService(navmesh=navmesh, terrain=TrinityMapTerrain(tmp_path))
    point = {"x": 80.88, "y": -2271.34, "z_known": False}

    projected = service.project_position(2175, point)
    assert projected["z"] == 98.0
    assert projected["surface_layer_hint_source"] == "TRINITYCORE_MAPS"

    assert service.find_path(2175, point, point) == "route"
    assert navmesh.path_calls[0][1]["z_source"] == "TRINITYCORE_MAPS_TERRAIN"


def test_geometry_service_does_not_use_submerged_terrain_as_layer_hint(tmp_path: Path):
    (tmp_path / "2175_31_36.map").write_bytes(_maps_tile(ground=90.0, liquid=92.0))
    navmesh = _Navmesh()
    service = WorldGeometryService(navmesh=navmesh, terrain=TrinityMapTerrain(tmp_path))
    point = {"x": 80.88, "y": -2271.34, "z_known": False}

    projected = service.project_position(2175, point)

    assert navmesh.project_calls[0][2] is None
    assert projected["surface_layer_hint_source"] == "NONE"
    service.find_path(2175, point, point)
    assert "z" not in navmesh.path_calls[0][1]


@pytest.mark.skipif(
    not Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\maps\2175_31_36.map").is_file(),
    reason="local TrinityCore Retail maps are not installed",
)
def test_real_exiles_reach_maps_tile_matches_known_upper_surface():
    maps = TrinityMapTerrain(r"C:\Program Files (x86)\World of Warcraft\_retail_")
    sample = maps.sample(2175, 80.88, -2271.34)
    assert sample is not None
    assert sample.is_hole is False
    assert sample.terrain_z == pytest.approx(98.18, abs=.5)
