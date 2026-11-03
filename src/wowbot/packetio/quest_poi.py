"""Bounded numeric quest-POI snapshots; no NPC identity or action authority.

WPP V9_0_1 QuestHandler is the latest POI payload handler in the pinned
12.1.5 tree: 12 int32 blob fields, int16 XYZ points and one merge-bit byte.
Checked to exact record end on all 9 responses in the user-run 70575
capture of 2026-10-28 15:56 (65793 turn-in: 1792,31,313).
"""
from __future__ import annotations

import struct

MAX_QUESTS, MAX_BLOBS, MAX_POINTS = 64, 64, 512
BLOB_FIELDS = ("blob_index", "objective_index", "objective_id", "quest_object_id",
               "world_map_id", "ui_map_id", "priority", "flags", "world_effect_id",
               "player_condition_id", "navigation_condition_id", "spawn_tracking_id")


def normalize_poi_blobs(blobs):
    """Rebuild the exact allowlisted numeric shape, rejecting unreviewed data."""
    if not isinstance(blobs, list) or len(blobs) > MAX_BLOBS:
        raise ValueError("quest POI blob count")
    result, total = [], 0
    for blob in blobs:
        if not isinstance(blob, dict):
            raise ValueError("quest POI blob")
        row = {}
        for field in ("group_index", *BLOB_FIELDS):
            value = blob.get(field)
            if type(value) is not int or not -(2**31) <= value < 2**31:
                raise ValueError("quest POI numeric metadata")
            row[field] = value
        if (not 0 <= row["group_index"] < MAX_BLOBS or not -1 <= row["objective_index"] <= 255
                or not 0 <= row["world_map_id"] < 65536 or not 0 <= row["ui_map_id"] < 2**20):
            raise ValueError("quest POI map/objective")
        points = blob.get("points")
        if not isinstance(points, list):
            raise ValueError("quest POI points")
        total += len(points)
        if total > MAX_POINTS:
            raise ValueError("quest POI point count")
        row["points"] = []
        for point in points:
            if (not isinstance(point, dict) or any(type(point.get(axis)) is not int
                    or not -32768 <= point[axis] <= 32767 for axis in ("x", "y", "z"))):
                raise ValueError("quest POI coordinate")
            row["points"].append({axis: point[axis] for axis in ("x", "y", "z")})
        if type(blob.get("always_merge")) is not bool:
            raise ValueError("quest POI merge flag")
        row["always_merge"] = blob["always_merge"]
        result.append(row)
    if len({row["group_index"] for row in result}) != len(result):
        raise ValueError("duplicate quest POI group")
    return result


def decode_quest_pois(data: bytes):
    offset = 0

    def read(fmt):
        nonlocal offset
        size = struct.calcsize(fmt)
        values = struct.unpack_from(fmt, data, offset)
        offset += size
        return values

    _num_pois, count = read("<II")
    if count > MAX_QUESTS:
        raise ValueError("quest POI quest count")
    decoded, quest_ids = [], set()
    for _ in range(count):
        quest, blob_count = read("<iI")
        if not 0 < quest < 2**31 or quest in quest_ids or blob_count > MAX_BLOBS:
            raise ValueError("quest POI quest/blob identity")
        quest_ids.add(quest)
        blobs, total = [], 0
        for group in range(blob_count):
            blob = dict(zip(BLOB_FIELDS, read("<12i")))
            point_count, = read("<I")
            total += point_count
            if total > MAX_POINTS:
                raise ValueError("quest POI point count")
            points = [dict(zip(("x", "y", "z"), read("<hhh"))) for _ in range(point_count)]
            flag, = read("<B")
            if flag & 0x7F:
                raise ValueError("unreviewed quest POI merge padding")
            blobs.append({**blob, "group_index": group, "points": points, "always_merge": bool(flag & 0x80)})
        decoded.append(("QUEST_POI_UPDATE", {"quest_id": quest, "blobs": normalize_poi_blobs(blobs)}))
    if offset != len(data):
        raise ValueError("unreviewed quest POI trailing data")
    return decoded
