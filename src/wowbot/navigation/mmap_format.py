"""Checked Trinity MMAP v16 / Detour v7 serialization, shared by both routers.

The wrapper order is magic, dtVersion, mmapVersion, byte count, liquid/padding;
these two versions are not interchangeable. No route/input authority here.
"""
import math
import struct

MMAP_MAGIC = 0x4D4D4150
DETOUR_MAGIC = 0x444E4156
MMAP_VERSION = 16
DETOUR_VERSION = 7
# Trinity's reviewed generator stores `1 << DT_POLY_BITS` (31) in the signed
# dtNavMeshParams.maxPolys slot. The resulting 0x80000000 is capacity metadata,
# not a polygon count/allocation. DT_POLYREF64 init uses fixed reference bits.
TRINITY_POLY_CAPACITY = -(1 << 31)


class MMapFormatError(ValueError):
    def __init__(self, reason, *, version=False):
        super().__init__(reason)
        self.reason = reason
        self.status = 'VERSION_MISMATCH' if version else 'ERROR'

    def diagnostic(self):
        return {'geometry_status':self.status, 'reason':self.reason}


def map_parameters(data):
    if len(data) < 36:
        raise MMapFormatError('map_header_truncated')
    magic,version = struct.unpack_from('<2I',data)
    if magic != MMAP_MAGIC:
        raise MMapFormatError('map_magic_mismatch')
    if version != MMAP_VERSION:
        raise MMapFormatError('map_version_mismatch',version=True)
    origin = struct.unpack_from('<3f',data,8)
    width,height = struct.unpack_from('<2f',data,20)
    tiles,polys = struct.unpack_from('<2i',data,28)
    if (not all(math.isfinite(v) for v in (*origin,width,height)) or width <= 0 or height <= 0
            or not 0 < tiles <= 2**20
            or not (0 < polys <= 2**24 or polys == TRINITY_POLY_CAPACITY)):
        raise MMapFormatError('map_parameters_invalid')
    # Both the prior 36-byte parameter-only header and the v16 extension
    # carrying OffMeshData[44 bytes] have the same reviewed parameter prefix.
    if len(data) != 36:
        if len(data) < 40:
            raise MMapFormatError('map_extension_truncated')
        count = struct.unpack_from('<I',data,36)[0]
        if count > 1_000_000 or 40+count*44 != len(data):
            raise MMapFormatError('map_offmesh_size_invalid')
    return origin,width,height,tiles,polys


def tile_mesh(data, *, for_native=False):
    if len(data) < 20:
        raise MMapFormatError('tile_header_truncated')
    magic,detour,version,size = struct.unpack_from('<4I',data)
    if magic != MMAP_MAGIC:
        raise MMapFormatError('tile_magic_mismatch')
    if detour != DETOUR_VERSION or version != MMAP_VERSION:
        raise MMapFormatError('tile_version_mismatch',version=True)
    if size < 100 or size+20 > len(data):
        raise MMapFormatError('tile_size_invalid')
    mesh = memoryview(data)[20:20+size]
    header = struct.unpack_from('<15i10f',mesh)
    if header[0] != DETOUR_MAGIC:
        raise MMapFormatError('mesh_magic_mismatch')
    if header[1] != DETOUR_VERSION:
        raise MMapFormatError('mesh_version_mismatch',version=True)
    counts = header[6:14]
    if (any(v < 0 or v > 4_000_000 for v in counts) or not header[6] or not header[7]
            or header[6] > 2_000_000 or not 0 <= header[14] <= header[6]
            or not all(math.isfinite(v) for v in header[15:])):
        raise MMapFormatError('mesh_header_invalid')
    # Detour v7, 64-bit dtPolyRef ABI: poly32/link16/detail12/BV16/offmesh36.
    required = 100+sum(n*width for n,width in zip(counts,(32,12,16,12,12,4,16,36)))
    if required > size:
        raise MMapFormatError('mesh_sections_truncated')
    if for_native and (header[9] != header[14] or header[14]+header[13] != header[6]
                       or header[8] == 0):
        raise MMapFormatError('mesh_native_sections_invalid')
    return mesh,header
