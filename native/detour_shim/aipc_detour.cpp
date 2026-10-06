// Flat C API over Recast/Detour for the agent (ctypes).
//
// TrinityCore mmaps are Detour tiles built with 64-bit polygon references
// (DT_POLYREF64; measured 2026-10-03: link records are 16 bytes).  The
// Python side strips TrinityCore's 20-byte mmtile wrapper and passes the raw
// Detour tile data.  Coordinates are Detour coordinates (y is up).
#include <cstring>

#include "DetourCommon.h"
#include "DetourNavMesh.h"
#include "DetourNavMeshQuery.h"

#define AIPC_API extern "C" __declspec(dllexport)

namespace {
struct AipcNav {
    dtNavMesh* mesh = nullptr;
    dtNavMeshQuery* query = nullptr;
};

dtQueryFilter make_filter(unsigned short include, unsigned short exclude) {
    dtQueryFilter filter;
    filter.setIncludeFlags(include);
    filter.setExcludeFlags(exclude);
    return filter;
}
}  // namespace

// 100 * sizeof(dtPolyRef) + DT_NAVMESH_VERSION: lets Python verify the ABI.
AIPC_API int aipc_abi() { return 100 * static_cast<int>(sizeof(dtPolyRef)) + DT_NAVMESH_VERSION; }

AIPC_API void* aipc_nav_create(const float* origin, float tile_width, float tile_height,
                               int max_tiles, int max_polys, int max_nodes) {
    dtNavMeshParams params;
    std::memset(&params, 0, sizeof(params));
    dtVcopy(params.orig, origin);
    params.tileWidth = tile_width;
    params.tileHeight = tile_height;
    params.maxTiles = max_tiles;
    params.maxPolys = max_polys;
    AipcNav* nav = new AipcNav();
    nav->mesh = dtAllocNavMesh();
    if (!nav->mesh || dtStatusFailed(nav->mesh->init(&params))) {
        dtFreeNavMesh(nav->mesh);
        delete nav;
        return nullptr;
    }
    nav->query = dtAllocNavMeshQuery();
    if (!nav->query || dtStatusFailed(nav->query->init(nav->mesh, max_nodes))) {
        dtFreeNavMeshQuery(nav->query);
        dtFreeNavMesh(nav->mesh);
        delete nav;
        return nullptr;
    }
    return nav;
}

AIPC_API void aipc_nav_destroy(void* handle) {
    AipcNav* nav = static_cast<AipcNav*>(handle);
    if (!nav) return;
    dtFreeNavMeshQuery(nav->query);
    dtFreeNavMesh(nav->mesh);
    delete nav;
}

// Returns the dtStatus (0x40000000 = success).
AIPC_API unsigned int aipc_nav_add_tile(void* handle, const unsigned char* data, int size) {
    AipcNav* nav = static_cast<AipcNav*>(handle);
    if (!nav || !data || size <= 0) return DT_FAILURE | DT_INVALID_PARAM;
    unsigned char* copy = static_cast<unsigned char*>(dtAlloc(size, DT_ALLOC_PERM));
    if (!copy) return DT_FAILURE | DT_OUT_OF_MEMORY;
    std::memcpy(copy, data, size);
    dtStatus status = nav->mesh->addTile(copy, size, DT_TILE_FREE_DATA, 0, nullptr);
    if (dtStatusFailed(status)) dtFree(copy);
    return status;
}

// Nearest polygon inside a 3D box (half extents): stacked layers are never
// mixed the way a 2D-nearest search does.  Returns 1 when found.
AIPC_API int aipc_nav_nearest(void* handle, const float* position, const float* extents,
                              unsigned short include, unsigned short exclude,
                              unsigned long long* out_ref, float* out_point) {
    AipcNav* nav = static_cast<AipcNav*>(handle);
    if (!nav) return 0;
    dtQueryFilter filter = make_filter(include, exclude);
    dtPolyRef ref = 0;
    float nearest[3] = {0, 0, 0};
    if (dtStatusFailed(nav->query->findNearestPoly(position, extents, &filter, &ref, nearest)) || !ref)
        return 0;
    *out_ref = static_cast<unsigned long long>(ref);
    dtVcopy(out_point, nearest);
    return 1;
}

// Path between two positions.  Return codes: 1 complete, 2 partial (the
// end polygon was not reached), -1 no start polygon, -2 no end polygon,
// -3 search failed.  out_points receives the string-pulled corners.
AIPC_API int aipc_nav_find_path(void* handle, const float* start, const float* end,
                                const float* extents, unsigned short include, unsigned short exclude,
                                int max_polys, float* out_points, int max_points, int* out_point_count,
                                int* out_poly_count, unsigned long long* out_refs) {
    AipcNav* nav = static_cast<AipcNav*>(handle);
    if (!nav) return -3;
    *out_point_count = 0;
    *out_poly_count = 0;
    dtQueryFilter filter = make_filter(include, exclude);
    dtPolyRef start_ref = 0, end_ref = 0;
    float start_point[3], end_point[3];
    if (dtStatusFailed(nav->query->findNearestPoly(start, extents, &filter, &start_ref, start_point)) || !start_ref)
        return -1;
    if (dtStatusFailed(nav->query->findNearestPoly(end, extents, &filter, &end_ref, end_point)) || !end_ref)
        return -2;
    if (max_polys > 65536) max_polys = 65536;
    dtPolyRef* polys = new dtPolyRef[max_polys];
    int poly_count = 0;
    dtStatus status = nav->query->findPath(start_ref, end_ref, start_point, end_point, &filter,
                                           polys, &poly_count, max_polys);
    if (dtStatusFailed(status) || poly_count <= 0) {
        delete[] polys;
        return -3;
    }
    bool complete = polys[poly_count - 1] == end_ref;
    float target[3];
    if (complete) {
        dtVcopy(target, end_point);
    } else {
        // Partial: stop at the closest point of the last reached polygon.
        nav->query->closestPointOnPoly(polys[poly_count - 1], end_point, target, nullptr);
    }
    unsigned char* flags = new unsigned char[max_points];
    dtPolyRef* corner_refs = new dtPolyRef[max_points];
    int corner_count = 0;
    status = nav->query->findStraightPath(start_point, target, polys, poly_count, out_points, flags,
                                          corner_refs, &corner_count, max_points, 0);
    delete[] flags;
    delete[] corner_refs;
    *out_poly_count = poly_count;
    out_refs[0] = static_cast<unsigned long long>(start_ref);
    out_refs[1] = static_cast<unsigned long long>(end_ref);
    delete[] polys;
    if (dtStatusFailed(status)) return -3;
    *out_point_count = corner_count;
    return complete ? 1 : 2;
}

// Height of a polygon at a position (for surface tracking).  Returns 1 on success.
AIPC_API int aipc_nav_poly_height(void* handle, unsigned long long ref, const float* position, float* out_height) {
    AipcNav* nav = static_cast<AipcNav*>(handle);
    if (!nav) return 0;
    float height = 0;
    if (dtStatusFailed(nav->query->getPolyHeight(static_cast<dtPolyRef>(ref), position, &height))) return 0;
    *out_height = height;
    return 1;
}

// Every walkable layer under/over one position (Z resolver, 2026-10-06):
// the polygons of a tall box around ``position`` whose footprint contains
// it, with the height of each at that X/Z.  Returns the number written.
AIPC_API int aipc_nav_layers_at(void* handle, const float* position, const float* extents,
                                unsigned short include, unsigned short exclude,
                                float* out_heights, unsigned long long* out_refs, int max_out) {
    AipcNav* nav = static_cast<AipcNav*>(handle);
    if (!nav || max_out <= 0) return 0;
    dtQueryFilter filter = make_filter(include, exclude);
    dtPolyRef polys[512];
    int count = 0;
    if (dtStatusFailed(nav->query->queryPolygons(position, extents, &filter, polys, &count, 512))) return 0;
    int written = 0;
    for (int i = 0; i < count && written < max_out; ++i) {
        float height = 0;
        if (dtStatusFailed(nav->query->getPolyHeight(polys[i], position, &height))) continue;
        out_heights[written] = height;
        out_refs[written] = static_cast<unsigned long long>(polys[i]);
        ++written;
    }
    return written;
}

// Centres of the walkable polygons in a box (planning-only destination
// candidates).  Returns the number written; out_points holds x,y,z triples.
AIPC_API int aipc_nav_polys_near(void* handle, const float* center, const float* extents,
                                 unsigned short include, unsigned short exclude,
                                 float* out_points, unsigned long long* out_refs, int max_out) {
    AipcNav* nav = static_cast<AipcNav*>(handle);
    if (!nav || max_out <= 0) return 0;
    dtQueryFilter filter = make_filter(include, exclude);
    const int capacity = 2048;
    dtPolyRef* polys = new dtPolyRef[capacity];
    int count = 0;
    if (dtStatusFailed(nav->query->queryPolygons(center, extents, &filter, polys, &count, capacity))) {
        delete[] polys;
        return 0;
    }
    int written = 0;
    for (int i = 0; i < count && written < max_out; ++i) {
        const dtMeshTile* tile = nullptr;
        const dtPoly* poly = nullptr;
        if (dtStatusFailed(nav->mesh->getTileAndPolyByRef(polys[i], &tile, &poly)) || !poly
                || poly->getType() != DT_POLYTYPE_GROUND || poly->vertCount == 0) continue;
        float sum[3] = {0, 0, 0};
        for (int v = 0; v < poly->vertCount; ++v) dtVadd(sum, sum, &tile->verts[poly->verts[v] * 3]);
        dtVscale(&out_points[written * 3], sum, 1.0f / poly->vertCount);
        out_refs[written] = static_cast<unsigned long long>(polys[i]);
        ++written;
    }
    delete[] polys;
    return written;
}
