"""Prefer a built staircase to a steep hillside (user 2026-10-23).

"It often struggles up the shortest way on the hillside while a staircase
goes straight up right beside it."  Stairs paid the same slope cost as the
hillside and, for their risers, the cliff penalty too.  Built polygons lie
above the MAPS terrain inside a placed model (the 376944 approach climbed
3-18 yd above it); the native v3 filter charges them a quarter of the slope.
"""
import math

from wowbot.navigation.mmap_navmesh import NAV_GROUND, NAV_STRUCTURE, NavMeshPath, TrinityMMapNavMesh


class FakeNative:
    has_structure_costs = True
    has_layer_queries = True

    def __init__(self, polys):
        self.polys = polys
        self.flags = {ref: flags for ref, flags, _ in polys}

    def polys_with_flags(self, bmin, bmax, mask):
        return [(ref, self.flags[ref], vertices) for ref, _flags, vertices in self.polys
                if self.flags[ref] & mask]

    def add_poly_flags(self, refs, flags):
        for ref in refs:
            self.flags[ref] |= flags
        return len(refs)

    def layers_at(self, point, *, extents, include, exclude=0, limit=64):
        return [(point[1], ref) for ref, flags in self.flags.items() if flags & include]


def ramp(x0, rise, run=4.):
    """A steep Detour quad (x = world y, y = height, z = world x)."""
    return [(0., 0., x0), (2., 0., x0), (2., rise, x0+run), (0., rise, x0+run)]


def terrain(instance_id, x, y):
    """MAPS terrain: flat at 0, except the hillside rising 4 yd from x=20 to 24."""
    return (min(4., max(0., x-20.)) if 20. <= x <= 24. else 0.), False


def test_only_steep_polygons_on_a_placed_model_are_marked(tmp_path):
    nav = TrinityMMapNavMesh(tmp_path)
    nav.terrain_height = terrain
    nav.structure_box = lambda *args: True
    nav.structure_surface = lambda instance_id, x, y, z: x < 50.          # stairs at world x < 50
    stair = [(x, y+3., z) for x, y, z in ramp(0., 4.)]                    # 3-7 yd above terrain
    hillside = ramp(20., 4.)                                              # lies on the terrain
    tree_top = [(x, y+3., z) for x, y, z in ramp(60., 4.)]                # above terrain, no surface
    gentle = [(x, y+3., z) for x, y, z in ramp(80., .5)]                  # built but flat
    native = FakeNative([(1, NAV_GROUND, stair), (2, NAV_GROUND, hillside),
                         (3, NAV_GROUND, tree_top), (4, NAV_GROUND, gentle)])
    report = nav._mark_structures(native, 2444, [((0., 0., 0.), (0., 4., 4.))])
    assert report["structure_newly_marked"] == 1
    assert native.flags[1] & NAV_STRUCTURE
    assert not any(native.flags[ref] & NAV_STRUCTURE for ref in (2, 3, 4))
    # Decided once: a second pass measures nothing new.
    assert nav._mark_structures(native, 2444, [((0., 0., 0.), (0., 4., 4.))])["structure_newly_marked"] == 0


def test_only_steep_climbs_look_for_stairs(tmp_path):
    nav = TrinityMMapNavMesh(tmp_path)
    flat = [{"x": 0., "y": 0., "z": 0.}, {"x": 20., "y": 0., "z": 2.}]
    steep = [{"x": 0., "y": 0., "z": 0.}, {"x": 4., "y": 0., "z": 3.}]
    assert nav._climbs(flat) == []
    assert len(nav._climbs(steep)) == 1
    assert nav._climbs(list(reversed(steep))) == []         # going down is no climb


def test_a_route_with_a_climb_is_planned_again_after_marking(tmp_path):
    nav = TrinityMMapNavMesh(tmp_path)
    nav.terrain_height = terrain
    nav.structure_box = lambda *args: True
    nav.structure_surface = lambda *args: True
    native = FakeNative([(1, NAV_GROUND, [(x, y+3., z) for x, y, z in ramp(0., 4.)])])
    hillside = NavMeshPath(({"x": 0., "y": 0., "z": 0.}, {"x": 4., "y": 0., "z": 3.}), 1, 1, 5.)
    stairs = NavMeshPath(({"x": 0., "y": 0., "z": 0.}, {"x": 9., "y": 2., "z": 3.}), 1, 1, 9.5)
    routes = [hillside, stairs]

    def route(*args):
        nav.last_diagnostics = {"reason": "route_found"}
        return routes.pop(0)

    nav._native_route = route
    nav.allowed_flags = NAV_GROUND
    result = nav._native_find_path(native, 2444, {}, {}, (0., 0., 0.), (0., 3., 4.))
    assert result is stairs and nav.last_diagnostics["structure_newly_marked"] == 1


def test_a_staircase_may_be_steeper_than_terrain(tmp_path):
    nav = TrinityMMapNavMesh(tmp_path)
    climb = [(0., 0., 0.), (2., 2.8, 0.)]                    # 54 degrees, 2.8 yd up
    assert not nav._walking_segments_supported(climb)       # on terrain: no
    nav.__dict__["_route_native"] = FakeNative([(1, NAV_GROUND | NAV_STRUCTURE, [])])
    assert nav._walking_segments_supported(climb)           # on a built stair: yes
    assert not nav._walking_segments_supported([(0., 0., 0.), (1., 2.8, 0.)])   # 70 degrees: no
    assert math.degrees(math.atan2(2.8, 2.)) < TrinityMMapNavMesh.STRUCTURE_MAX_DEGREES
