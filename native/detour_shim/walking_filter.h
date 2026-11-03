// Project-owned, geometry-only walking preference. No invented ROAD label.
#pragma once

#include <algorithm>
#include <cmath>
#include <limits>
#include "DetourCommon.h"
#include "DetourNavMesh.h"
#include "DetourNavMeshQuery.h"

// TrinityCore NavTerrainFlag values (MapDefines.h).  A liquid polygon lies
// on the liquid surface; it is only admitted when the caller marked it
// wadeable (shallow enough to walk) with a project flag of its own.
constexpr unsigned short AIPC_NAV_WATER = 0x04;
constexpr unsigned short AIPC_NAV_MAGMA_SLIME = 0x08;
// Project flag (2026-10-23): a sloped polygon lying above the ADT terrain --
// built stairs, ramps, bridges.  Made for climbing: the slope costs a
// quarter, and a stair riser is no cliff.
constexpr unsigned short AIPC_NAV_STRUCTURE = 0x20;

class AipcWalkingFilter final : public dtQueryFilter {
public:
    explicit AipcWalkingFilter(float max_slope_degrees = 44.f,
                               float water_cost = 1.f, float magma_slime_cost = 1.f)
        : max_grade(std::tan(max_slope_degrees * 0.01745329252f)),
          water_cost(std::max(1.f, water_cost)),
          magma_slime_cost(std::max(1.f, magma_slime_cost)) {}

    static float grade(const dtMeshTile* tile, const dtPoly* poly) {
        if (!tile || !poly || poly->vertCount < 3) return 0.f;
        const float* a = &tile->verts[poly->verts[0] * 3];
        float steepest = 0.f;
        for (int i = 1; i + 1 < poly->vertCount; ++i) {
            float ab[3], ac[3], normal[3];
            dtVsub(ab, &tile->verts[poly->verts[i] * 3], a);
            dtVsub(ac, &tile->verts[poly->verts[i + 1] * 3], a);
            dtVcross(normal, ab, ac);
            const float horizontal = std::hypot(normal[0], normal[2]);
            if (std::fabs(normal[1]) < 1e-5f) {
                if (horizontal > 1e-5f) return std::numeric_limits<float>::infinity();
                continue;
            }
            steepest = std::max(steepest, horizontal / std::fabs(normal[1]));
        }
        return steepest;
    }

    bool passFilter(dtPolyRef ref, const dtMeshTile* tile, const dtPoly* poly) const override {
        // A steep polygon may still be traversable along its contour. Only
        // the direction actually travelled can prove an excessive climb.
        return dtQueryFilter::passFilter(ref, tile, poly);
    }

    float getCost(const float* a, const float* b,
                  dtPolyRef prev_ref, const dtMeshTile* prev_tile, const dtPoly* prev_poly,
                  dtPolyRef ref, const dtMeshTile* tile, const dtPoly* poly,
                  dtPolyRef next_ref, const dtMeshTile* next_tile, const dtPoly* next_poly) const override {
        const float base = dtQueryFilter::getCost(a, b, prev_ref, prev_tile, prev_poly,
                                                  ref, tile, poly, next_ref, next_tile, next_poly);
        const float rise = std::fabs(b[1] - a[1]);
        const float horizontal = dtVdist2D(a, b);
        const float slope = rise / std::max(.1f, horizontal);
        // >= 1 keeps the Euclidean A* heuristic admissible. A modest longer
        // gentle walk may beat a short scramble, without banning all hills.
        const float terrain_grade = std::min(2.f, grade(tile, poly));
        // User 2026-10-23: the route often struggled straight up a hillside
        // while a staircase went up right beside it; the stair paid the same
        // slope cost and, for its risers, the cliff penalty too.
        const bool structure = poly && (poly->flags & AIPC_NAV_STRUCTURE);
        const float slope_weight = structure ? .25f : 1.f;
        float penalty = 1.f + slope_weight * (6.f * slope * slope + 4.f * terrain_grade * terrain_grade);
        // Quantised mesh stairs have small near-vertical risers; do not
        // disconnect them by treating the whole polygon as a cliff.
        if (rise > .6f && slope > max_grade && !structure) penalty += 100.f;
        // Prefer clearance from known non-neighbour boundary edges. Polygon
        // size or a short internal portal is NOT evidence of a narrow road:
        // open ground can be tessellated into arbitrarily small triangles.
        float clearance = 3.f;
        if (tile && poly) {
            float middle[3];
            dtVlerp(middle, a, b, .5f);
            for (int i = 0; i < poly->vertCount; ++i) {
                if (poly->neis[i] != 0) continue;
                const float* left = &tile->verts[poly->verts[i] * 3];
                const float* right = &tile->verts[poly->verts[(i + 1) % poly->vertCount] * 3];
                float t;
                const float distance = std::sqrt(dtDistancePtSegSqr2D(middle, left, right, t));
                clearance = std::min(clearance, distance);
            }
        }
        penalty += .75f * (3.f - clearance) / 3.f;
        // User 2026-10-22: shallow liquid is a crossing, not a walkway.  Every
        // yard in it costs a multiple, so A* leaves it by the shortest way
        // and a dry detour wins unless it is many times longer.  Lava and
        // slime hurt; water does not, so it is cheaper.
        if (poly && (poly->flags & AIPC_NAV_MAGMA_SLIME)) penalty *= magma_slime_cost;
        else if (poly && (poly->flags & AIPC_NAV_WATER)) penalty *= water_cost;
        return base * penalty;
    }

private:
    float max_grade;
    float water_cost;
    float magma_slime_cost;
};
