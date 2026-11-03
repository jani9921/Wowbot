// Offline deterministic cost/filter checks; no game process or input.
#include <cstdio>
#include "walking_filter.h"

int main() {
    AipcWalkingFilter filter(44.f);
    filter.setIncludeFlags(1);
    float flat_vertices[] = {0.f,0.f,0.f, 10.f,0.f,0.f, 0.f,0.f,10.f};
    float rough_vertices[] = {0.f,0.f,0.f, 10.f,6.f,0.f, 0.f,0.f,10.f};
    dtPoly flat = {}, rough = {};
    flat.vertCount = rough.vertCount = 3;
    flat.flags = rough.flags = 1;
    flat.verts[0] = rough.verts[0] = 0;
    flat.verts[1] = rough.verts[1] = 1;
    flat.verts[2] = rough.verts[2] = 2;
    flat.neis[0] = flat.neis[1] = flat.neis[2] = 1;
    rough.neis[0] = rough.neis[1] = rough.neis[2] = 1;
    dtNavMesh mesh;
    dtNavMeshParams params = {};
    params.tileWidth = params.tileHeight = 20.f;
    params.maxTiles = 2;
    params.maxPolys = 8;
    if (dtStatusFailed(mesh.init(&params))) return 10;
    const dtNavMesh& view = mesh;
    dtMeshTile* flat_tile = const_cast<dtMeshTile*>(view.getTile(0));
    dtMeshTile* rough_tile = const_cast<dtMeshTile*>(view.getTile(1));
    flat_tile->verts = flat_vertices;
    rough_tile->verts = rough_vertices;
    float start[] = {0.f,0.f,0.f}, longer[] = {14.f,0.f,0.f}, shorter[] = {10.f,0.f,0.f};
    float steep[] = {1.f,3.f,0.f};
    auto cost = [&](const float* end, const dtMeshTile* tile, const dtPoly* poly) {
        return filter.getCost(start, end, 0, nullptr, nullptr, 1, tile, poly, 0, nullptr, nullptr);
    };
    if (!(cost(longer, flat_tile, &flat) < cost(shorter, rough_tile, &rough))) return 1;
    if (!(cost(shorter, flat_tile, &flat) >= dtVdist(start, shorter))) return 2;
    if (!(cost(steep, flat_tile, &flat) > 100.f)) return 3;
    const float open_cost = cost(shorter, flat_tile, &flat);
    flat.neis[0] = 0; // known boundary along the planned segment
    if (!(cost(shorter, flat_tile, &flat) > open_cost)) return 7;
    // Surface inclination alone does not forbid travelling along a contour.
    if (!filter.passFilter(1, rough_tile, &rough)) return 4;
    flat.flags = 4; // water is never silently admitted by comfort preference
    if (filter.passFilter(1, flat_tile, &flat)) return 5;
    flat.flags = 1;
    filter.setExcludeFlags(1);
    if (filter.passFilter(1, flat_tile, &flat)) return 6;
    // 2026-10-22: a wadeable liquid polygon costs a multiple of the same
    // ground walk; damaging magma/slime more than harmless water.
    AipcWalkingFilter wading(44.f, 3.f, 10.f);
    wading.setIncludeFlags(1 | AIPC_NAV_WATER | AIPC_NAV_MAGMA_SLIME);
    const float ground_cost = wading.getCost(start, shorter, 0, nullptr, nullptr, 1, flat_tile, &flat,
                                             0, nullptr, nullptr);
    flat.flags = AIPC_NAV_WATER;
    const float water_cost = wading.getCost(start, shorter, 0, nullptr, nullptr, 1, flat_tile, &flat,
                                            0, nullptr, nullptr);
    flat.flags = AIPC_NAV_MAGMA_SLIME;
    const float magma_cost = wading.getCost(start, shorter, 0, nullptr, nullptr, 1, flat_tile, &flat,
                                            0, nullptr, nullptr);
    flat.flags = 1;
    if (!(water_cost > 2.9f * ground_cost && magma_cost > 3.f * water_cost)) return 8;
    // 2026-10-23: a built stair beside a hillside of the same slope is cheaper.
    AipcWalkingFilter stairs(44.f);
    stairs.setIncludeFlags(1 | AIPC_NAV_STRUCTURE);
    rough.flags = 1;
    const float hillside = stairs.getCost(start, steep, 0, nullptr, nullptr, 1, rough_tile, &rough,
                                          0, nullptr, nullptr);
    rough.flags = 1 | AIPC_NAV_STRUCTURE;
    const float stair = stairs.getCost(start, steep, 0, nullptr, nullptr, 1, rough_tile, &rough,
                                       0, nullptr, nullptr);
    rough.flags = 1;
    if (!(stair * 3.f < hillside && stair >= dtVdist(start, steep))) return 9;
    std::puts("Walking geometry costs, no shortcut reward, contour, and flag guards passed.");
    return 0;
}
