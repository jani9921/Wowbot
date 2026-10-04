"""Surface labels, regions and cave entrances (design doc §10, step 4)."""
from types import SimpleNamespace

from wowbot.navigation.mmap_navmesh import TrinityMMapNavMesh, NavPolygon
from wowbot.navigation.surface_labels import (COVERED, ELEVATED, SURFACE, SurfaceLabeler,
                                              classify_deltas)

TILE = 21750000 + 31 * 100 + 32


def _square(index, x0, z0, height, size=20.):
    """Detour-axis square (x, y=height, z); neighbours are found by shared edges."""
    vertices = ((x0, height, z0), (x0, height, z0 + size), (x0 + size, height, z0 + size),
                (x0 + size, height, z0))
    return NavPolygon((TILE, index), vertices, (0, 0, 0, 0), 1)


class _Terrain:
    """Hill over the cave strip (detour x >= 40), flat ground elsewhere."""

    def sample(self, _instance, world_x, world_y):
        detour_x = world_y              # world y == detour x
        height = 30. if 40. <= detour_x <= 120. else 0.
        return SimpleNamespace(terrain_z=height, is_hole=False)


def _navmesh(polygons):
    mesh = SimpleNamespace(allowed_flags=1, _adjacency=TrinityMMapNavMesh._adjacency,
                           source=SimpleNamespace(names=lambda *_: ["2175_31_32.mmtile"]))
    mesh._load_tile = lambda *_args: tuple(polygons)
    return mesh


def test_classify_deltas():
    assert classify_deltas([0., 1., -1.]) == SURFACE
    assert classify_deltas([12., 15., 9.]) == COVERED
    assert classify_deltas([-8., -6., -5.]) == ELEVATED
    assert classify_deltas([None, None]) == "UNKNOWN"


def test_cave_region_and_its_entrance_from_map_and_mmap():
    surface = [_square(i, 20. * i - 0., 0., 0.) for i in range(2)]                 # x 0..40 on the ground
    cave = [_square(2 + i, 40. + 20. * i, 0., 0.) for i in range(3)]               # x 40..100 under the hill
    bridge = [_square(9, 0., 200., 12.)]                                            # far away, 12 yd up
    label_map = SurfaceLabeler(_navmesh(surface + cave + bridge), _Terrain()).build(2175, tiles=[(31, 32)])
    assert {label_map.label_at((TILE, i)) for i in range(2)} == {SURFACE}
    assert {label_map.label_at((TILE, i)) for i in range(2, 5)} == {COVERED}
    assert label_map.label_at((TILE, 9)) == ELEVATED
    caves = [region for region in label_map.regions if region.kind == "CAVE"]
    assert len(caves) == 1 and caves[0].depth >= 8 and caves[0].area >= 300
    (entrance,) = label_map.entrances
    # The mouth is on the x = 40 edge and leads inward (+x in Detour = +y world).
    assert abs(entrance["centre_world"][1] - 40.) < 1e-6
    assert entrance["inward_direction"][1] > .9
