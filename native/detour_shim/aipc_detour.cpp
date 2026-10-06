// Flat C API over Recast/Detour for the agent (ctypes).
//
// TrinityCore mmaps are Detour tiles built with 64-bit polygon references
// (DT_POLYREF64; measured 2026-10-03: link records are 16 bytes).  The
// Python side strips TrinityCore's 20-byte mmtile wrapper and passes the raw
// Detour tile data.  Coordinates are Detour coordinates (y is up).
#include <cmath>
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

// The shared edge of two neighbouring polygons (dtNavMeshQuery's own
// getPortalPoints is private); a partial tile-border link is narrowed.
bool portal_points(const dtNavMesh* mesh, dtPolyRef from, dtPolyRef to, float* left, float* right) {
    const dtMeshTile* tile = nullptr;
    const dtPoly* poly = nullptr;
    if (dtStatusFailed(mesh->getTileAndPolyByRef(from, &tile, &poly)) || !poly
            || poly->getType() != DT_POLYTYPE_GROUND) return false;
    for (unsigned int i = poly->firstLink; i != DT_NULL_LINK; i = tile->links[i].next) {
        const dtLink& link = tile->links[i];
        if (link.ref != to || link.edge >= poly->vertCount) continue;
        const float* a = &tile->verts[poly->verts[link.edge] * 3];
        const float* b = &tile->verts[poly->verts[(link.edge + 1) % poly->vertCount] * 3];
        if (link.side != 0xff && (link.bmin != 0 || link.bmax != 255)) {
            const float scale = 1.0f / 255.0f;
            dtVlerp(left, a, b, link.bmin * scale);
            dtVlerp(right, a, b, link.bmax * scale);
        } else {
            dtVcopy(left, a);
            dtVcopy(right, b);
        }
        return true;
    }
    return false;
}

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

// Path along the middle of the walkway (user 2026-10-06, Hrun's spiral: "the
// character walked down along the cave wall and fell off the spiral").  The
// string-pulled path touches polygon edges at every bend.  Here every portal
// crossing is a point (DT_STRAIGHTPATH_ALL_CROSSINGS), pushed toward its
// portal's midpoint by up to ``margin`` (never past the middle); heights come
// from the polygon the point lies in; nearly straight runs are thinned.
// Return codes as aipc_nav_find_path.
AIPC_API int aipc_nav_find_path_centered(void* handle, const float* start, const float* end,
                                         const float* extents, unsigned short include, unsigned short exclude,
                                         int max_polys, float margin, float* out_points, int max_points,
                                         int* out_point_count, int* out_poly_count, unsigned long long* out_refs) {
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
    if (complete) dtVcopy(target, end_point);
    else nav->query->closestPointOnPoly(polys[poly_count - 1], end_point, target, nullptr);
    const int capacity = max_points * 4 + 16;
    float* raw = new float[capacity * 3];
    unsigned char* flags = new unsigned char[capacity];
    dtPolyRef* refs = new dtPolyRef[capacity];
    int raw_count = 0;
    status = nav->query->findStraightPath(start_point, target, polys, poly_count, raw, flags, refs,
                                          &raw_count, capacity, DT_STRAIGHTPATH_ALL_CROSSINGS);
    *out_poly_count = poly_count;
    out_refs[0] = static_cast<unsigned long long>(start_ref);
    out_refs[1] = static_cast<unsigned long long>(end_ref);
    if (dtStatusFailed(status) || raw_count <= 0) {
        delete[] polys; delete[] raw; delete[] flags; delete[] refs;
        return -3;
    }
    // Centre each crossing on its portal (between the previous point's
    // polygon and this point's polygon); keep the start and the end.
    for (int i = 1; i + 1 < raw_count; ++i) {
        float left[3], right[3];
        if (!portal_points(nav->mesh, refs[i - 1], refs[i], left, right)) continue;
        float mid[3];
        dtVlerp(mid, left, right, 0.5f);
        float to_mid[3];
        dtVsub(to_mid, mid, &raw[i * 3]);
        to_mid[1] = 0;
        float distance = dtVlen(to_mid);
        float half_width = 0.5f * dtVdist2D(left, right);
        float shift = margin < half_width * 0.7f ? margin : half_width * 0.7f;
        if (distance > 1e-4f) {
            if (shift > distance) shift = distance;
            dtVmad(&raw[i * 3], &raw[i * 3], to_mid, shift / distance);
        }
        // User 2026-10-06 ("a spirálon ... eléggé a szélén megy, jobb lenne ha
        // bentebb menne"): a portal is a short polygon edge, so its midpoint
        // is not the walkway's middle.  Push the point away from the nearest
        // navmesh boundary (wall or drop) until it has ``margin`` clearance,
        // sliding on the mesh; a narrow walkway stops where clearance no
        // longer improves.
        for (int pass = 0; pass < 3 && margin > 0.f; ++pass) {
            float hit_dist = 0.f, hit_pos[3], hit_normal[3];
            if (dtStatusFailed(nav->query->findDistanceToWall(refs[i], &raw[i * 3], margin, &filter,
                                                              &hit_dist, hit_pos, hit_normal))
                    || hit_dist >= margin * 0.95f)
                break;
            hit_normal[1] = 0.f;
            float normal_length = dtVlen(hit_normal);
            if (normal_length < 1e-4f) break;
            float wanted[3];
            dtVmad(wanted, &raw[i * 3], hit_normal, (margin - hit_dist) / normal_length);
            float moved[3];
            dtPolyRef visited[16];
            int visited_count = 0;
            if (dtStatusFailed(nav->query->moveAlongSurface(refs[i], &raw[i * 3], wanted, &filter, moved,
                                                            visited, &visited_count, 16))
                    || visited_count <= 0)
                break;
            float again = 0.f, again_pos[3], again_normal[3];
            dtPolyRef moved_ref = visited[visited_count - 1];
            if (dtStatusFailed(nav->query->findDistanceToWall(moved_ref, moved, margin, &filter,
                                                              &again, again_pos, again_normal))
                    || again <= hit_dist + 0.05f)
                break;
            dtVcopy(&raw[i * 3], moved);
            refs[i] = moved_ref;
        }
        float height = raw[i * 3 + 1];
        if (dtStatusSucceed(nav->query->getPolyHeight(refs[i], &raw[i * 3], &height))) raw[i * 3 + 1] = height;
    }
    // Thin nearly straight, level runs; keep every bend of the walkway.
    int written = 0;
    for (int i = 0; i < raw_count && written < max_points; ++i) {
        bool keep = i == 0 || i + 1 == raw_count;
        if (!keep && written > 0) {
            const float* a = &out_points[(written - 1) * 3];
            const float* b = &raw[i * 3];
            const float* c = &raw[(i + 1) * 3];
            float ab[3], bc[3];
            dtVsub(ab, b, a);
            dtVsub(bc, c, b);
            float lab = sqrtf(ab[0] * ab[0] + ab[2] * ab[2]);
            float lbc = sqrtf(bc[0] * bc[0] + bc[2] * bc[2]);
            float cosine = (lab > 1e-4f && lbc > 1e-4f) ? (ab[0] * bc[0] + ab[2] * bc[2]) / (lab * lbc) : 1.0f;
            float climb = fabsf(bc[1] / (lbc > 0.5f ? lbc : 0.5f) - ab[1] / (lab > 0.5f ? lab : 0.5f));
            keep = cosine < 0.985f || climb > 0.25f || lab > 12.0f;   // ~10 degrees, slope change, long run
        }
        if (keep) {
            dtVcopy(&out_points[written * 3], &raw[i * 3]);
            ++written;
        }
    }
    *out_point_count = written;
    delete[] polys; delete[] raw; delete[] flags; delete[] refs;
    return complete ? 1 : 2;
}
