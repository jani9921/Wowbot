"""Native Detour router (docs/NAVIGATION_MULTIRES_LAYERED_DESIGN.md step 2).

Measured 2026-10-03 on Exile's Reach: 0.2-1.7 ms per route natively versus
0.8-1.3 s in the Python A*, same or slightly shorter paths.
"""
import json
import os
from pathlib import Path

import pytest

NATIVE_OFF = os.environ.get("AIPC_NATIVE_DETOUR", "1").strip().lower() in {"0", "false", "off", "no"}

from wowbot.navigation import detour_native
from wowbot.navigation.mmap_navmesh import TrinityMMapNavMesh

ROOT = Path(__file__).resolve().parents[1]


def _real_mmaps():
    try:
        path = json.loads((ROOT / "output/agent/agent_gui.json").read_text(encoding="utf-8"))["mmap_path"]
    except (OSError, ValueError, KeyError):
        return None
    return path if path and Path(path).exists() else None


def test_dll_abi_is_64_bit_polyrefs():
    if NATIVE_OFF or not detour_native.DLL_PATH.is_file():
        pytest.skip("native/bin/aipc_detour.dll not built")
    assert detour_native.load_library().aipc_abi() == detour_native.EXPECTED_ABI


def test_missing_dll_keeps_the_python_router(tmp_path, monkeypatch):
    monkeypatch.setattr(detour_native, "DLL_PATH", tmp_path / "missing.dll")
    with pytest.raises(detour_native.NativeDetourUnavailable):
        detour_native.load_library(tmp_path / "missing.dll")


@pytest.mark.skipif(_real_mmaps() is None or NATIVE_OFF, reason="real mmaps / native Detour not available")
def test_real_exiles_reach_route_is_native_fast_and_layer_safe():
    mesh = TrinityMMapNavMesh(_real_mmaps())
    try:
        polys = [p for p in mesh._load_tile(2175, 31, 32) if p.flags & mesh.allowed_flags]
        first, second = polys[0], polys[len(polys) // 2]
        start = mesh._detour_to_world(first.center, 2175)
        goal = mesh._detour_to_world(second.center, 2175)
        path = mesh.find_path(2175, start, goal)
        assert path is not None and mesh.last_diagnostics["router"] == "native_detour"
        assert mesh.last_diagnostics["endpoint_layer"] == "known"
        # An endpoint without Z is flagged, never silently snapped in 2D.
        flat = {key: value for key, value in goal.items() if key != "z"}
        mesh.find_path(2175, start, flat)
        # 2026-10-04: an unknown target layer is resolved by probing every
        # walkable layer there for the shortest complete path (Torgok's POI
        # had 3 layers); still flagged, never a silent 2D snap.
        assert mesh.last_diagnostics["endpoint_layer"] in {"assumed_start_height",
                                                           "shortest_reachable_layer"}
    finally:
        mesh.close()


@pytest.mark.skipif(_real_mmaps() is None, reason="real mmaps not available")
def test_surface_projection_keeps_the_layer_without_a_route_hint():
    """Stacked walkable layers (2.65 % of 2175's x,y): after one hinted
    projection the next unhinted one must stay on the same layer."""
    import collections
    mesh = TrinityMMapNavMesh(_real_mmaps())
    try:
        bins = collections.defaultdict(list)
        for gx, gy in ((31, 32), (32, 32), (31, 31), (32, 31), (30, 32), (31, 33)):
            for poly in mesh._load_tile(2175, gx, gy):
                if poly.flags & mesh.allowed_flags:
                    x, y, z = poly.center
                    bins[(round(x), round(z))].append(poly)
        stacked = next((polys for polys in bins.values()
                        if max(p.center[1] for p in polys) - min(p.center[1] for p in polys) > 8), None)
        if stacked is None:
            pytest.skip("no stacked layer near the sampled tiles")
        low = min(stacked, key=lambda p: p.center[1])
        high = max(stacked, key=lambda p: p.center[1])
        point = mesh._detour_to_world(low.center, 2175)
        first = mesh.project_position(2175, point, z_hint=low.center[1])
        assert abs(first["z"] - low.center[1]) < 3 and abs(first["z"] - high.center[1]) > 5
        again = mesh.project_position(2175, {**point, "z": 0.})
        assert abs(again["z"] - first["z"]) < 3
        assert mesh.last_surface_projection["layer_hint_source"] == "continuity"
    finally:
        mesh.close()


@pytest.mark.skipif(_real_mmaps() is None, reason="real mmaps not available")
def test_unknown_target_height_takes_the_reachable_floor_inside_the_ogre_ruins():
    # Live 2026-10-04: Torgok's quest POI (244, -2243) has walkable layers at
    # 80.9 / 83.8 / 122.0; assuming the start height gave only a partial path.
    mesh = TrinityMMapNavMesh(_real_mmaps())
    try:
        path = mesh.find_path(2175, {"x": 269.73, "y": -2300.38, "instance_id": 2175},
                              {"x": 243.99990844727, "y": -2243.0, "instance_id": 2175})
        assert path is not None, mesh.last_diagnostics
        assert mesh.last_diagnostics["endpoint_layer"] == "shortest_reachable_layer"
        last = path.anchors[-1]
        assert abs(last["x"]-244.) < 1. and abs(last["y"]+2243.) < 1. and 83. < last["z"] < 85.
        assert path.cost < 80.
    finally:
        mesh.close()


@pytest.mark.skipif(_real_mmaps() is None, reason="real mmaps not available")
def test_estimated_terrain_height_under_a_building_falls_back_to_the_reachable_floor():
    # Live 2026-10-04 18:52: the maps terrain height (80.9) under Torgok's
    # building was passed as a known Z; Detour gave a partial path only.
    mesh = TrinityMMapNavMesh(_real_mmaps())
    try:
        path = mesh.find_path(2175, {"x": 268.01, "y": -2299.67, "instance_id": 2175},
                              {"x": 243.99990844727, "y": -2243.0, "z": 80.9, "z_known": True,
                               "z_estimated": True, "z_source": "TRINITYCORE_MAPS_TERRAIN",
                               "instance_id": 2175})
        assert path is not None, mesh.last_diagnostics
        assert mesh.last_diagnostics["endpoint_layer"] == "estimated_z_unreachable_shortest_layer"
        assert 83. < path.anchors[-1]["z"] < 85.
    finally:
        mesh.close()


@pytest.mark.skipif(_real_mmaps() is None, reason="real mmaps not available")
def test_leaving_torgoks_room_does_not_start_on_the_island_under_the_building():
    # Live 2026-10-04 18:44: inside Torgok's room the player got the terrain
    # height under the building (80.9, an isolated layer) and every turn-in
    # MOVE failed with required_navmesh_route_unavailable.
    from wowbot.world_geometry.service import WorldGeometryService
    geo = WorldGeometryService.from_paths(_real_mmaps())
    try:
        path = geo.find_path(2175, {"x": 243.37, "y": -2246.61, "instance_id": 2175, "z_known": False},
                             {"x": 227.99993896484, "y": -2294.0002441406, "instance_id": 2175,
                              "z_known": False})
        assert path is not None, geo.last_diagnostics
        assert 83. < path.anchors[0]["z"] < 85.
    finally:
        geo.close()
