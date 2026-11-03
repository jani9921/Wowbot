"""Unknown/missing/partial geometry is never a traversable path."""
from types import SimpleNamespace
import pytest

from wowbot.geometry_contracts import GeometryResult, GeometryStatus, query_path
from wowbot.navigation.mmap_navmesh import NavMeshPath

START = {"x": 0., "y": 0., "z": 0., "coordinate_space": "WORLD_YARDS"}
END = {"x": 10., "y": 0., "z_known": False}


@pytest.mark.parametrize("diagnostics,status", [
    ({"reason": "map_header_missing"}, "MISSING_DATA"),
    ({"reason": "no_route_tiles"}, "MISSING_DATA"),
    ({"reason": "no_polygon_path"}, "NO_ROUTE"),
    ({"reason": "no_polygon_path", "partial": True}, "PARTIAL"),
    ({"reason": "walking_segment_grade_rejected"}, "NO_ROUTE"),
    ({"reason": "tile_version_mismatch"}, "VERSION_MISMATCH"),
    ({"reason": "route_found"}, "UNKNOWN"),
])
def test_failures_remain_distinguishable_without_manufacturing_paths(diagnostics, status):
    provider = SimpleNamespace(find_path=lambda *args: None, last_diagnostics=diagnostics)
    result = query_path(provider, 0, START, END)
    assert result.status.value == status and not result.ready and result.value is None


def test_zero_map_height_and_zero_cost_are_valid_and_query_does_not_modify_points():
    path = NavMeshPath((dict(START), dict(START)), 1, 1, 0.)
    provider = SimpleNamespace(find_path=lambda *args: path, last_diagnostics={})
    result = query_path(provider, 0, START, START)
    assert result.ready and result.value is path
    assert START["z"] == 0.


@pytest.mark.parametrize("point", [{"x": True, "y": 0.}, {"x": float('nan'), "y": 0.},
    {"x": 0., "y": 0., "coordinate_space": "SCREEN_NORMALIZED"}])
def test_malformed_or_screen_coordinates_do_not_reach_geometry(point):
    def forbidden(*args):pytest.fail('invalid coordinates reached provider')
    assert query_path(SimpleNamespace(find_path=forbidden), 2444, START, point).status is GeometryStatus.INVALID_INPUT


def test_partial_result_with_anchors_still_has_no_actionable_path():
    provider = SimpleNamespace(find_path=lambda *args: NavMeshPath((START, END), 2, 1, 10.),
                               last_diagnostics={"reason": "no_polygon_path", "partial": True})
    assert query_path(provider, 2444, START, END).status is GeometryStatus.PARTIAL


def test_missing_capability_and_failing_provider_are_not_no_route_proofs():
    assert query_path(None, 2444, START, END).status is GeometryStatus.UNSUPPORTED
    def broken(*args):raise OSError('missing files')
    assert query_path(SimpleNamespace(find_path=broken), 2444, START, END).status is GeometryStatus.ERROR


def test_non_ready_contract_cannot_carry_an_actionable_value():
    with pytest.raises(ValueError):GeometryResult(GeometryStatus.MISSING_DATA, value=object())


@pytest.mark.parametrize('path,map_id', [
    (SimpleNamespace(anchors=(), cost=0.), 2444),
    (SimpleNamespace(anchors=(START, {'x': float('nan'), 'y': 0.}), cost=1.), 2444),
    (SimpleNamespace(anchors=(START, END), cost=1.), 0),
])
def test_typed_ready_status_cannot_bypass_path_and_world_validation(path, map_id):
    provider = SimpleNamespace(query_path=lambda *args: GeometryResult(
        GeometryStatus.READY, path, world_map_id=map_id))
    result = query_path(provider, 2444, START, END)
    assert result.status is GeometryStatus.ERROR and result.value is None
