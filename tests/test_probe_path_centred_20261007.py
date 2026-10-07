"""Live 2026-10-07 12:06 (user: "alapból már a szélére kormányoz teljesen").

Routes to a destination without a known height (minimap quest dot, floor
cue) took ``_probe_reachable_layer``'s path, which was requested without the
centring margin: Detour's string-pulled path touches the inner edge of every
bend, i.e. the rim of Hrun's spiral over the pit, and the character walked
along it until a badly timed steer dropped it to the bottom.
"""
from wowbot.navigation.mmap_navmesh import TrinityMMapNavMesh


class _Native:
    def __init__(self):
        self.calls = []

    def nearest(self, position, *, extents, include, exclude=0):
        # Two walkable layers at the target X/Y, one at the start.
        x, height, z = position
        layer = 60. if height < 80. else 95.
        return (int(layer), (x, layer, z))

    def find_path(self, start, end, *, extents, include, exclude=0, margin=None):
        self.calls.append(margin)
        if abs(end[1]-60.) > 1.:
            return (2, [start, end], 3, (0, 0))              # the upper layer is not reachable
        rim = [start, (start[0]+5., 70., start[2]), end]
        middle = [start, (start[0]+5., 70., start[2]+2.5), end]
        return (1, middle if margin else rim, 9, (1, 2))


def test_the_probed_layer_route_is_the_centred_path():
    mesh = TrinityMMapNavMesh.__new__(TrinityMMapNavMesh)
    native = _Native()
    result = mesh._probe_reachable_layer(native, (0., 95., 0.), (10., 95., 10.), 3,
                                         start_z_known=True)
    assert result[0] == 1
    assert result[1][1] == (5., 70., 2.5)                  # centred, not on the rim
    assert native.calls[-1] == mesh.PATH_CENTER_MARGIN
    assert all(margin is None for margin in native.calls[:-1])   # layer choice stays fast


def test_a_failing_centred_path_keeps_the_probed_one():
    class _NoCentre(_Native):
        def find_path(self, start, end, *, extents, include, exclude=0, margin=None):
            if margin:
                self.calls.append(margin)
                return (-3, [], 0, (0, 0))
            return super().find_path(start, end, extents=extents, include=include)
    mesh = TrinityMMapNavMesh.__new__(TrinityMMapNavMesh)
    result = mesh._probe_reachable_layer(_NoCentre(), (0., 95., 0.), (10., 95., 10.), 3,
                                         start_z_known=True)
    assert result[0] == 1 and result[1][1] == (5., 70., 0.)
