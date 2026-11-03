"""Binary format failures remain distinct from a proven unreachable route."""
import struct
import zipfile

import pytest

from wowbot.geometry_contracts import GeometryStatus, query_path
from wowbot.navigation.mmap_navmesh import MMapDataSource, TrinityMMapNavMesh
from wowbot.navigation.mmap_format import MMapFormatError, map_parameters, tile_mesh
from wowbot.navigation.detour_native import NativeDetourMap
from test_mmap_navmesh import _tile, _map_header

START={'x':-449.7,'y':-2614.,'z':0.}
END={'x':-448.3,'y':-2614.,'z':0.}


def changed(data, offset, value, fmt='I'):
    result=bytearray(data)
    struct.pack_into('<'+fmt,result,offset,value)
    return bytes(result)


def mesh(tmp_path, *, header=None, tile=None):
    (tmp_path/'2175.mmap').write_bytes(_map_header() if header is None else header)
    if tile is not None:(tmp_path/'2175_32_36.mmtile').write_bytes(tile)
    owner=TrinityMMapNavMesh(tmp_path,tile_padding=0)
    owner.use_native=False
    return owner


@pytest.mark.parametrize('data,status,reason',[
    (b'short',GeometryStatus.ERROR,'map_header_truncated'),
    (changed(_map_header(),0,0),GeometryStatus.ERROR,'map_magic_mismatch'),
    (changed(_map_header(),4,999),GeometryStatus.VERSION_MISMATCH,'map_version_mismatch'),
    (changed(_map_header(),8,float('nan'),'f'),GeometryStatus.ERROR,'map_parameters_invalid'),
    (changed(_map_header(),36,1),GeometryStatus.ERROR,'map_offmesh_size_invalid'),
])
def test_bad_map_header_cannot_fall_back_to_unchecked_python_route(tmp_path,data,status,reason):
    owner=mesh(tmp_path,header=data,tile=_tile())
    result=query_path(owner,2175,START,END)
    assert result.status is status and result.reason==reason and result.value is None
    assert owner.project_position(2175,START) is None
    assert owner.last_surface_projection['reason']==reason
    owner.close()


@pytest.mark.parametrize('data,status,reason',[
    (b'short',GeometryStatus.ERROR,'tile_header_truncated'),
    (changed(_tile(),0,0),GeometryStatus.ERROR,'tile_magic_mismatch'),
    (changed(_tile(),4,8),GeometryStatus.VERSION_MISMATCH,'tile_version_mismatch'),
    (changed(_tile(),8,17),GeometryStatus.VERSION_MISMATCH,'tile_version_mismatch'),
    (changed(_tile(),24,16),GeometryStatus.VERSION_MISMATCH,'mesh_version_mismatch'),
    (_tile()[:-1],GeometryStatus.ERROR,'tile_size_invalid'),
    (changed(_tile(),20+8*4,99999),GeometryStatus.ERROR,'mesh_sections_truncated'),
    (changed(_tile(),120,float('nan'),'f'),GeometryStatus.ERROR,'mesh_vertices_nonfinite'),
])
def test_bad_tile_returns_specific_format_failure_including_on_cached_graph(tmp_path,data,status,reason):
    owner=mesh(tmp_path,tile=data)
    for _ in range(2):
        result=query_path(owner,2175,START,END)
        assert result.status is status and result.reason==reason and result.value is None
    owner.close()


def test_missing_tile_disallowed_water_and_complete_route_have_distinct_results(tmp_path):
    owner=mesh(tmp_path)
    assert query_path(owner,2175,START,END).status is GeometryStatus.MISSING_DATA
    owner.close()
    water=tmp_path/'water';water.mkdir()
    owner=mesh(water,tile=_tile(flags=4))
    assert query_path(owner,2175,START,END).status is GeometryStatus.NO_ROUTE
    owner.close()
    land=tmp_path/'land';land.mkdir()
    owner=mesh(land,tile=_tile())
    assert query_path(owner,2175,START,END).status is GeometryStatus.READY
    owner.close()


def test_trinity_wrapper_and_mesh_versions_are_not_swapped():
    _,header=tile_mesh(_tile())
    assert header[1]==7  # dtMeshHeader.version, not mmapVersion=16
    assert map_parameters(_map_header())==map_parameters(_map_header()[:36])
    with pytest.raises(MMapFormatError):tile_mesh(changed(_tile(),4,16))


@pytest.mark.parametrize('header',[
    '50414d4d10000000ffff60c600008000ffff79c65555054455550544980400000000008000000000',
    '50414d4d100000005555e9c500008000545569c65555054455550544b20400000000008000000000',
    '50414d4d10000000ffff15c600008000ffff15c65555054455550544620600000000008000000000',
])
def test_actual_trinity_headers_preserve_signed_31_bit_capacity(header):
    # The user's reviewed 0000/2175/2444 headers, not invented positive limits.
    values=map_parameters(bytes.fromhex(header))
    assert values[-1]==-(1<<31) and values[-2]>0


@pytest.mark.parametrize('capacity',[-1,-2,-2147483647,0,2**24+1])
def test_accepting_exact_trinity_capacity_does_not_accept_other_invalid_limits(capacity):
    with pytest.raises(MMapFormatError,match='map_parameters_invalid'):
        map_parameters(changed(_map_header(),32,capacity,'i'))


def test_real_capacity_allows_the_checked_python_route_without_disabling_validation(tmp_path):
    owner=mesh(tmp_path,header=changed(_map_header(),32,-(1<<31),'i'),tile=_tile())
    try:
        assert query_path(owner,2175,START,END).status is GeometryStatus.READY
    finally:
        owner.close()


def test_native_loader_preserves_capacity_without_treating_it_as_an_allocation(tmp_path):
    mesh(tmp_path,header=changed(_map_header(),32,-(1<<31),'i')).close()
    class Library:
        parameters=None
        def aipc_nav_create(self,*args):self.parameters=args;return 1
        def aipc_nav_destroy(self,*args):pass
    source=MMapDataSource(tmp_path)
    lib=Library()
    native=NativeDetourMap(lib,source,2175)
    try:
        assert lib.parameters[3:5]==(4096,-(1<<31))
    finally:
        native.close();source.close()


def test_native_loader_rejects_unknown_version_before_calling_dll(tmp_path):
    mesh(tmp_path,tile=changed(_tile(),8,17)).close()
    class Library:
        calls=0
        def aipc_nav_create(self,*args):return 1
        def aipc_nav_add_tile(self,*args):self.calls+=1;return 1<<30
        def aipc_nav_destroy(self,*args):pass
    source=MMapDataSource(tmp_path)
    lib=Library()
    native=NativeDetourMap(lib,source,2175)
    assert lib.calls==0 and native.tiles==0 and native.failed_tiles==1
    assert native.data_errors[0]['geometry_status']=='VERSION_MISMATCH'
    native.close();source.close()


def test_corrupted_archive_member_is_data_error_instead_of_no_route(tmp_path,monkeypatch):
    owner=mesh(tmp_path,tile=_tile())
    read=owner.source.read
    def damaged(name):
        if name.endswith('.mmtile'):raise zipfile.BadZipFile('CRC failure')
        return read(name)
    monkeypatch.setattr(owner.source,'read',damaged)
    result=query_path(owner,2175,START,END)
    assert result.status is GeometryStatus.ERROR and result.reason=='tile_read_failed'
    owner.close()
