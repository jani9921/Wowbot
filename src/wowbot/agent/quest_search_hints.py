"""Bounded objective search geometry; never a live actor or input authority."""
from __future__ import annotations

import math

from .models import Proposal, number
from .ui_zones import same_zone


def objective_poi_points(state: dict, quest_id, objective_id, order=None):
    """Keep each matching POI point's own floor, including mixed-height groups.

    These are search hints, not NPC spawns or a polygon with a common Z.
    NavigationService must still validate each route and track coverage.
    """
    from .planning_types import world_point
    from .tdb_locations import _live_point_matches_poi
    player = state.get("player_world_position") or {}
    px, py = number(player.get("x")), number(player.get("y"))
    if (None in (px, py) or not all(math.isfinite(v) for v in (px, py))
            or player.get("instance_id") is None):
        return [], []
    reference = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(quest_id)) or {}
    live = [world_point(p) for p in state.get("quest_locations") or ()
            if isinstance(p, dict) and str(p.get("quest_id")) == str(quest_id)]
    live = [p for p in live if p and str(p.get("instance_id")) == str(player["instance_id"])
            and same_zone(p.get("map_id"), state.get("map_id"))]
    points, hints = [], []
    for poi in reference.get("pois") or ():
        if (not isinstance(poi, dict)
                or not (str(poi.get("objective_id")) == str(objective_id)
                        if poi.get("objective_id") not in (None, 0, "0")
                        else order is not None and str(poi.get("objective_index")) == str(order))
                or poi.get("geometry_ambiguous") or poi.get("geometry_mixed_build")
                or str(poi.get("world_map_id")) != str(player["instance_id"])
                or not same_zone(poi.get("ui_map_id"), state.get("map_id"))
                or any(v not in (None, 0) for v in (poi.get("conditions") or {}).values())
                or live and not any(_live_point_matches_poi(p, poi) for p in live)):
            continue
        raw = poi.get("points") or ()
        if not 1 <= len(raw) <= 64:
            continue
        for point in raw:
            x, y, z = (number(point.get(axis)) for axis in ("x", "y", "z"))
            if (None in (x, y) or not all(math.isfinite(v) for v in (x, y))
                    or math.hypot(x-px, y-py) > 2000.):
                continue
            hint = {"x": x, "y": y}
            if z is not None and math.isfinite(z) and z != 0.:
                hint["z"] = z
            if hint not in points:
                points.append(hint)
        hints.append(str(poi.get("poi_id")))
    return points[:64], sorted(hints)


def subject_search_proposal(state, quest_id, objective_id, entries, points, hints, *,
                            purpose, reason, excluded_points=()):
    if not points:
        return None
    points = sorted(points[:64], key=lambda p: (p["x"], p["y"], p.get("z", 0.)))
    centre = {axis: sum(p[axis] for p in points)/len(points) for axis in ("x", "y")}
    instance = (state.get("player_world_position") or {}).get("instance_id")
    area = {**centre, "coordinate_space": "WORLD_YARDS", "instance_id": instance,
            "map_id": state.get("map_id"), "coverage_points": points, "visit_radius": 6.,
            "radius": max(12., max(math.hypot(p["x"]-centre["x"], p["y"]-centre["y"])
                                   for p in points)), "source": "OBJECTIVE_SEARCH_HINTS"}
    return Proposal.make("MOVE", reason,
        {**centre, "coordinate_space": "WORLD_YARDS", "instance_id": instance,
         "map_id": state.get("map_id"), "quest_id": quest_id, "objective_id": objective_id,
         "purpose": purpose, "search_area": area, "expected_npc_ids": sorted(map(str, entries)),
         "search_hints": sorted(hints), "excluded_search_points": list(excluded_points),
         "require_navmesh": True, "stop_distance": 3., "knowledge_priority": "PRIMARY_STATIC"},
        confidence=.7, priority=90, evidence=("open_objective", "search_not_entity_identity"))
