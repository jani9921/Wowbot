"""Shallow liquid fords (user 2026-10-22).

"Allow it, not only lava but every liquid where possible, shallow enough to
walk in; but do not spend long in it, cross it, do not walk along it."  Live
2026-10-22 (Human, Waking Shores lava, MAPS depth = liquid_z - terrain_z):
walking at 1.85 yd, swimming at 2.03 yd; every Life-Binder Conservatory route
across the lava failed with required_navmesh_route_unavailable.
"""
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from wowbot.navigation.mmap_navmesh import (NAV_GROUND, NAV_GROUND_STEEP, NAV_MAGMA_SLIME,
                                            NAV_WADE, NAV_WATER, TrinityMMapNavMesh)
from wowbot.world_geometry.service import WorldGeometryService
from wowbot.world_geometry.terrain_maps import TerrainSample

ROOT = Path(__file__).resolve().parents[1]


class FakeNative:
    has_liquid_wading = True
    tiles = 1

    def __init__(self, polys):
        self.polys = polys            # (ref, flags, Detour vertices)
        self.costs = None
        self.flags = {ref: flags for ref, flags, _ in polys}

    def set_liquid_costs(self, water, magma_slime):
        self.costs = (water, magma_slime)
        return True

    def polys_with_flags(self, bmin, bmax, mask):
        found = []
        for ref, _flags, vertices in self.polys:
            xs, zs = [v[0] for v in vertices], [v[2] for v in vertices]
            if (self.flags[ref] & mask and max(xs) >= bmin[0] and min(xs) <= bmax[0]
                    and max(zs) >= bmin[2] and min(zs) <= bmax[2]):
                found.append((ref, self.flags[ref], vertices))
        return found

    def add_poly_flags(self, refs, flags):
        for ref in refs:
            self.flags[ref] |= flags
        return len(refs)


def square(world_x, world_y, surface):
    """A 4 yd liquid square in Detour coordinates (x = world y, z = world x)."""
    return [(world_y+dy, surface, world_x+dx) for dx, dy in ((0, 0), (4, 0), (4, 4), (0, 4))]


def depth_by_area(instance_id, x, y, surface, *, enough=None, slow=True):
    if x >= 100:                       # a cave's lava: only VMAPS knows its floor
        return math.nan if not slow else 0.9
    if x >= 50:
        return None                    # no floor evidence at all
    return 1.2 if y < 20 else 2.4      # shallow ford, then swimming depth


def test_only_measured_shallow_liquid_is_marked_and_costed(tmp_path):
    mesh = TrinityMMapNavMesh(tmp_path)
    assert mesh.allowed_flags & NAV_WADE and not mesh.allowed_flags & (NAV_WATER | NAV_MAGMA_SLIME)
    mesh.liquid_depth = depth_by_area
    native = FakeNative([(1, NAV_MAGMA_SLIME, square(10, 5, 40.)),     # shallow lava
                         (2, NAV_WATER, square(10, 30, 40.)),          # 2.4 yd: would swim
                         (3, NAV_WATER, square(60, 5, 40.)),           # unknown floor
                         (4, NAV_MAGMA_SLIME, square(110, 5, 40.))])   # cave: VMAPS needed
    start, end = (0., 40., 0.), (40., 40., 120.)
    fast = mesh._mark_wadeable(native, 2444, start, end)
    assert native.costs == (TrinityMMapNavMesh.WADE_WATER_COST, TrinityMMapNavMesh.WADE_MAGMA_SLIME_COST)
    assert native.costs[1] > native.costs[0] > 1.          # lava/slime hurts, water does not
    assert fast["wade_pass"] == "MAPS" and fast["wade_newly_marked"] == 1
    assert native.flags[1] & NAV_WADE and not native.flags[2] & NAV_WADE
    assert not native.flags[3] & NAV_WADE and not native.flags[4] & NAV_WADE
    assert fast["wade_deferred"] == 1
    # Measured once: a second route over the same cells does no work.
    assert mesh._mark_wadeable(native, 2444, start, end)["wade_cells_measured"] == 0
    slow = mesh._mark_wadeable(native, 2444, start, end, slow=True)
    assert slow["wade_pass"] == "VMAPS" and slow["wade_newly_marked"] == 1
    assert native.flags[4] & NAV_WADE and slow["wade_deferred"] == 0


def test_vmaps_pass_runs_only_after_a_failed_route(tmp_path):
    mesh = TrinityMMapNavMesh(tmp_path)
    mesh.liquid_depth = depth_by_area
    native = FakeNative([(4, NAV_MAGMA_SLIME, square(110, 5, 40.))])
    calls = []

    def route(native_, instance_id, start, destination, start_dt, end_dt, wading):
        calls.append(wading["wade_pass"])
        return "path" if native.flags[4] & NAV_WADE else None

    mesh._native_route = route
    result = mesh._native_find_path(native, 2444, {}, {}, (0., 40., 0.), (40., 40., 120.))
    assert result == "path" and calls == ["MAPS", "VMAPS"]
    calls.clear()
    assert mesh._native_find_path(native, 2444, {}, {}, (0., 40., 0.), (40., 40., 120.)) == "path"
    assert calls == ["MAPS"]


def test_wading_can_be_switched_off(tmp_path, monkeypatch):
    mesh = TrinityMMapNavMesh(tmp_path)
    mesh.liquid_depth = depth_by_area
    native = FakeNative([(1, NAV_MAGMA_SLIME, square(10, 5, 40.))])
    monkeypatch.setenv("AIPC_LIQUID_WADING", "0")
    assert mesh._mark_wadeable(native, 2444, (0., 40., 0.), (40., 40., 120.)) == {"liquid_wading": False}
    assert not native.flags[1] & NAV_WADE
    land_only = TrinityMMapNavMesh(tmp_path, allowed_flags=NAV_GROUND | NAV_GROUND_STEEP)
    land_only.liquid_depth = depth_by_area
    land_only._native_route = lambda *args: args[-1]
    assert land_only._native_find_path(native, 2444, {}, {}, (0., 40., 0.), (40., 40., 120.))[
        "liquid_wading"] is False


class FakeTerrain:
    def __init__(self, samples):
        self.samples = samples

    def sample(self, instance_id, x, y):
        terrain, liquid, flags, hole = self.samples[(x, y)]
        return TerrainSample(instance_id, 0, 0, terrain, liquid, 0, flags, hole)


class FakeVMaps:
    def __init__(self, surfaces):
        self.surfaces, self.calls = surfaces, 0

    def surfaces_above(self, map_id, x, y, bottom):
        self.calls += 1
        return [height for height in self.surfaces.get((x, y), []) if height >= bottom]


def test_depth_from_maps_and_vmaps():
    terrain = FakeTerrain({
        (1., 1.): (36.43, 37.68, 4, False),      # live lava ford: 1.25 yd, MAPS alone
        (2., 2.): (35.04, 37.07, 4, False),      # live: the Human swam here (2.03 yd)
        (3., 3.): (38.50, 37.68, 4, False),      # bank above the lava: no liquid there
        (4., 4.): (40.00, None, 0, False),       # shore vertex just outside the liquid cell
        (5., 5.): (112.1, None, 0, False),       # cave lava 70 yd under the hill
        (6., 6.): (10.00, -2000., 1, False),     # TrinityCore's "no liquid" height
        (7., 7.): (None, None, 0, True),         # terrain hole, no floor anywhere
    })
    geometry = WorldGeometryService(navmesh=SimpleNamespace(), terrain=terrain)
    vmaps = geometry.vmaps = FakeVMaps({(5., 5.): [94.35, 38.7, 36.6]})
    assert geometry.liquid_depth(2444, 1., 1., 37.75) == pytest.approx(1.25)
    assert geometry.liquid_depth(2444, 2., 2., 37.21) == pytest.approx(2.03)
    assert geometry.liquid_depth(2444, 3., 3., 37.75) == 0.
    assert geometry.liquid_depth(2444, 4., 4., 37.75, enough=1.6) == 0.
    assert math.isnan(geometry.liquid_depth(2444, 5., 5., 39.7, enough=1.6, slow=False))
    assert vmaps.calls == 0
    assert geometry.liquid_depth(2444, 5., 5., 39.7, enough=1.6) == pytest.approx(1.0)
    assert geometry.liquid_depth(2444, 6., 6., 10.5, enough=1.6) == pytest.approx(.5)
    assert geometry.liquid_depth(2444, 7., 7., 10.5) is None


def _real_sources():
    try:
        mmaps = json.loads((ROOT / "output/agent/agent_gui.json").read_text(encoding="utf-8"))["mmap_path"]
    except (OSError, ValueError, KeyError):
        return None
    retail = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_")
    return mmaps if mmaps and Path(mmaps).exists() and (retail / "maps").is_dir() else None


@pytest.mark.skipif(_real_sources() is None, reason="real mmaps/maps not available")
def test_life_binder_conservatory_lava_ford_live_20261022():
    """Live 2026-10-22 22:57: the kill target across the lava had no route."""
    geometry = WorldGeometryService.from_paths(_real_sources())
    try:
        native = geometry.navmesh._native_map(2444)
        if native is None or not native.has_liquid_wading:
            pytest.skip("native Detour v2 not available")
        start = {"x": 4045.62, "y": 252.28, "z": 54.14, "z_known": True, "z_observed": True}
        target = {"x": 4102.47, "y": 157.74, "z": 41.25, "z_known": True}
        path = geometry.find_path(2444, start, target)
        diagnostics = geometry.navmesh.last_diagnostics
        assert path is not None and diagnostics["liquid_wading"] is True
        assert 0. < diagnostics["wade_yards"] < 20.      # a short crossing, not a walk in lava
        geometry.navmesh.allowed_flags = NAV_GROUND | NAV_GROUND_STEEP
        assert geometry.find_path(2444, start, target) is None
    finally:
        geometry.close()
