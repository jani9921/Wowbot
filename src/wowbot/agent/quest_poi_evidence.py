"""Current server quest geometry is a search destination, never NPC identity."""
from __future__ import annotations

from .models import number


def objective_destinations(state, blobs):
    """Bounded interior/point candidates; never polygon corners as objects."""
    from .tdb_locations import geometry_points
    player = state.get('player_world_position') or {}
    if (player.get('coordinate_space') != 'WORLD_YARDS'
            or any(number(player.get(k)) is None for k in ('x', 'y'))):
        return []
    result = []
    for blob in blobs:
        if (blob.get('world_map_id') != player.get('instance_id')
                or blob.get('player_condition_id') or blob.get('navigation_condition_id')
                or blob.get('objective_index', -1) < 0):
            continue
        points = blob.get('points') or ()
        samples = geometry_points(points)
        heights = {number(p.get('z')) for p in points}
        # POI Z=0 is frequently a sentinel, not an observed terrain floor.
        known_height = len(heights) == 1 and next(iter(heights), None) not in (None, 0)
        for sample in samples:
            result.append({**sample, **({'z': next(iter(heights))} if known_height else {}),
                'z_known': known_height, 'z_observed': False, 'z_estimated': False,
                'coordinate_space': 'WORLD_YARDS', 'instance_id': blob['world_map_id'],
                'map_id': blob['ui_map_id'], 'source': 'PACKET_QUEST_POI',
                'sample_time': blob['sample_time'], 'knowledge_priority': 'SERVER_POI',
                'require_navmesh': True, 'confirmed': False, 'navigation_trusted': False,
                'poi_blob_index': blob['blob_index'], 'poi_group_index': blob['group_index']})
    return result


def current_turnin_poi(state: dict, quest_id) -> dict | None:
    """Packet POI first, then the current completed quest's client API pin.

    API pins are search destinations, not NPC/GUID or arrival evidence.
    Historical record.known_locations and unaccepted task pins do not enter
    this path. The supplied world conversion retains its real provenance.
    """
    packet = server_turnin_poi(state, quest_id)
    if packet is not None:
        return packet
    if not any(str(q.get('quest_id')) == str(quest_id) and q.get('is_complete') is True
               and q.get('is_accepted') is not False
               for q in state.get('active_quests') or () if isinstance(q, dict)):
        return None
    from .planning_types import world_point
    player = world_point(state.get('player_world_position'))
    if player is None:
        return None
    candidates = []
    for row in state.get('quest_locations') or ():
        if (not isinstance(row, dict) or str(row.get('quest_id')) != str(quest_id)
                or row.get('source') not in {'QUEST_POI', 'QUEST_API_WAYPOINT'}
                or row.get('in_progress') is False
                or str(row.get('role') or '').upper() not in {'', 'TURN_IN', 'QUEST_TURN_IN'}):
            continue
        point = world_point(row)
        if point is None or str(point['instance_id']) != str(player['instance_id']):
            continue
        candidates.append({**point, 'quest_id': int(quest_id),
            'source': 'QUEST_API_COMPLETION_POI', 'knowledge_priority': 'QUEST_API_CURRENT',
            'z_known': point.get('z_known') is True and number(point.get('z')) is not None,
            'confirmed': False, 'navigation_trusted': False, 'require_navmesh': True})
    distinct = {(p['x'], p['y'], p.get('z') if p['z_known'] else None) for p in candidates}
    return candidates[0] if len(distinct) == 1 else None


def server_turnin_poi(state: dict, quest_id) -> dict | None:
    if not any(str(quest.get("quest_id")) == str(quest_id) and quest.get("is_complete") is True
               for quest in state.get("active_quests") or () if isinstance(quest, dict)):
        return None
    record = (state.get("packet_quest_pois") or {}).get(str(quest_id)) or {}
    if record.get("verified") is not True or record.get("source") != "SMSG_QUEST_POI_QUERY_RESPONSE":
        return None
    now, sampled = number(state.get("monotonic_time")), number(record.get("sampled_at"))
    if now is None or sampled is None or not 0 <= now-sampled <= 1800.:
        return None
    player = state.get("player_world_position") or {}
    candidates = []
    for blob in record.get("blobs") or ():
        if (blob.get("objective_index") != -1 or blob.get("objective_id") != 0
                or str(blob.get("world_map_id")) != str(player.get("instance_id"))
                or blob.get("player_condition_id") or blob.get("navigation_condition_id")
                or len(blob.get("points") or ()) != 1):
            continue
        point = blob["points"][0]
        x, y, z = (number(point.get(axis)) for axis in ("x", "y", "z"))
        if x is None or y is None:
            continue
        candidates.append({"x": x, "y": y, **({"z": z} if z else {}),
            "z_known": bool(z), "z_estimated": False, "z_observed": False,
            "z_source": "SERVER_QUEST_POI", "coordinate_space": "WORLD_YARDS",
            # Adjacent UI zones share server world coordinates (2444:
            # Waking Shores -> Ohn'ahran Plains). The instance, not today's
            # UI zone, decides whether this XYZ is directly navigable.
            "instance_id": blob["world_map_id"], "map_id": blob["ui_map_id"],
            "ui_map_id": blob["ui_map_id"],
            "source": "PACKET_QUEST_POI", "knowledge_priority": "SERVER_POI",
            "quest_id": int(quest_id), "poi_blob_index": blob["blob_index"],
            "poi_group_index": blob["group_index"], "sample_time": sampled,
            "confirmed": False, "navigation_trusted": False})
    distinct = {(row["x"], row["y"], row.get("z")) for row in candidates}
    return candidates[0] if len(distinct) == 1 else None
