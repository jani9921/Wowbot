"""A rejected centered segment may get a bounded, fully routed alternative."""
import pytest

from wowbot.navigation.mmap_navmesh import TrinityMMapNavMesh
from test_mmap_navmesh import _tile


A, B = (0., 0., 0.), (20., 0., 0.)
BAD = [A, (10., 4., 0.), (11., 0., 0.), B]


class Native:
    tiles = 1

    def __init__(self, *, usable=True, mismatch=False, gap=False, pivot_mismatch=False):
        self.usable, self.mismatch, self.gap = usable, mismatch, gap
        self.pivot_mismatch = pivot_mismatch
        self.calls, self.projections = [], []

    def nearest(self, point, **kwargs):
        self.projections.append((point, kwargs))
        return 30, point

    def find_path(self, start, end, **kwargs):
        self.calls.append((start, end, kwargs))
        if start == A and end == B:
            return 1, BAD, 4, (10, 20)
        if not self.usable:
            return 2, [start, end], 2, (10, 20)
        if start == A:
            return 1, [start, end], 2, (99 if self.mismatch else 10, 30)
        pivot = (start[0]+.2, start[1], start[2]) if self.gap else start
        return 1, [pivot, end], 2, (31 if self.pivot_mismatch else 30, 20)


def mesh(tmp_path):
    (tmp_path/"test.mmtile").write_bytes(_tile())
    return TrinityMMapNavMesh(tmp_path)


def test_bad_centered_edge_gets_a_safe_connected_mesh_detour_with_unchanged_end_layers(tmp_path):
    nav, native = mesh(tmp_path), Native()
    try:
        route = nav._native_find_path(native, 2444, {"z": 0.}, {"z": 0.}, A, B)
        assert route is not None
        assert nav.last_diagnostics["walking_detour_verified"] is True
        assert nav.last_diagnostics["walking_detour_trials"] <= 6
        points = [nav._world_to_detour(a) for a in route.anchors]
        assert points[0] == A and points[-1] == B
        assert nav._walking_segments_supported(points)
        for _, _, kwargs in native.calls:
            assert kwargs["include"] == nav.allowed_flags
            assert kwargs.get("margin", 0.) >= nav.PATH_CENTER_MARGIN
    finally:
        nav.close()


@pytest.mark.parametrize("kind", ["partial", "endpoint_layer", "disconnected_join", "pivot_layer"])
def test_uncertain_or_incomplete_pivot_routes_are_not_accepted(tmp_path, kind):
    nav = mesh(tmp_path)
    native = Native(usable=kind!="partial", mismatch=kind=="endpoint_layer",
                    gap=kind=="disconnected_join", pivot_mismatch=kind=="pivot_layer")
    try:
        assert nav._native_find_path(native, 2444, {"z":0.}, {"z":0.}, A, B) is None
        assert len(native.projections) <= 6
        assert len(native.calls) <= 15
        assert nav.last_diagnostics["reason"] == "walking_segment_grade_rejected"
    finally:
        nav.close()


def test_a_normal_valid_path_does_not_pay_for_pivot_queries(tmp_path):
    nav = mesh(tmp_path)
    native = Native()
    native.find_path = lambda start, end, **kwargs: (1, [A, B], 2, (10, 20))
    try:
        assert nav._native_find_path(native, 2444, {"z":0.}, {"z":0.}, A, B)
        assert native.projections == []
    finally:
        nav.close()
