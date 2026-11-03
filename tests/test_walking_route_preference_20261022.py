"""Native route comfort is geometry evidence, not a fabricated road network."""
from types import SimpleNamespace
import math

import pytest

from wowbot.navigation.detour_native import NativeDetourMap
from wowbot.navigation.mmap_navmesh import TrinityMMapNavMesh
from wowbot.navigation.service import NavigationService
from test_mmap_navmesh import _tile


def mesh(tmp_path):
    (tmp_path/'test.mmtile').write_bytes(_tile())
    return TrinityMMapNavMesh(tmp_path)


@pytest.mark.parametrize('points, valid', [
    ([(0.,0.,0.), (10.,1.,0.)], True),
    ([(0.,0.,0.), (1.,3.,0.)], False),
    ([(0.,3.,0.), (1.,0.,0.)], False),
    ([(0.,0.,0.), (.1,.5,0.)], True),
])
def test_final_anchor_validation_checks_directional_grade_and_small_steps(tmp_path, points, valid):
    nav = mesh(tmp_path)
    try:
        assert nav._walking_segments_supported(points) is valid
    finally:
        nav.close()


@pytest.mark.parametrize('valid_alternative', [True, False])
def test_bad_centering_gets_bounded_same_endpoint_clearance_trials(tmp_path, valid_alternative):
    nav = mesh(tmp_path)
    calls = []
    bad = [(0.,0.,0.), (1.,3.,0.), (10.,0.,0.)]
    good = [(0.,0.,0.), (5.,1.,2.), (10.,0.,0.)]

    def path(start, end, **kwargs):
        calls.append((start, end, kwargs))
        points = good if valid_alternative and kwargs.get('margin') == 4. else bad
        return 1, points, 3, (1, 3)

    native = SimpleNamespace(find_path=path, tiles=1)
    try:
        result = nav._native_find_path(native, 1, {'z':0.}, {'z':0.}, (0.,0.,0.), (10.,0.,0.))
        if valid_alternative:
            assert result is not None
            assert nav.last_diagnostics['centered_margin'] == 4.
            assert nav.last_diagnostics['road_labels'] is False
            assert len(calls) == 2
        else:
            assert result is None and len(calls) == 3
        for start, end, _ in calls:
            assert start == (0.,0.,0.) and end == (10.,0.,0.)
    finally:
        nav.close()


def test_an_old_dll_cannot_claim_the_new_native_walking_policy():
    native = object.__new__(NativeDetourMap)
    native.lib, native.handle = SimpleNamespace(), 123
    assert native.set_walking_policy(44.) is False


def test_walking_slope_setting_is_passed_to_the_exact_native_map_handle():
    calls = []
    native = object.__new__(NativeDetourMap)
    native.lib = SimpleNamespace(aipc_nav_walking_policy=lambda handle, slope: calls.append((handle, slope)) or 1)
    native.handle = 123
    assert native.set_walking_policy(35.) is True
    assert calls == [(123,35.)]


def test_service_cannot_reintroduce_a_steep_shortcut_after_native_route_validation():
    geometry = SimpleNamespace(max_walkable_slope_degrees=44.)
    nav = NavigationService(navmesh=geometry)
    # A surface-height match alone does not prove the character can climb it.
    nav._z._layers_at = lambda instance, x, y: [3.*x]
    assert nav._segment_walkable(2444, (0.,0.,0.), (1.,0.,3.)) is False


@pytest.mark.parametrize('slope', [20., 35., 44.])
def test_gentle_grade_threshold_remains_configurable_per_mesh(tmp_path, slope):
    nav = mesh(tmp_path)
    nav._max_walkable_slope_ratio = math.tan(math.radians(slope))
    try:
        grade = math.tan(math.radians(slope+2.))
        assert not nav._walking_segments_supported([(0.,0.,0.), (10.,10.*grade,0.)])
    finally:
        nav.close()
