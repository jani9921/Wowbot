"""Order completed quests' turn-ins: the current zone first, then the nearest.

User 2026-10-31 (live 08:00, after Fargodeep Mine): two quests were ready to
hand in, The Fargodeep Mine (62, Goldshire, Elwynn Forest) and the
breadcrumb Hero's Call: Westfall! (26378, Westfall).  Both turn-in MOVEs had
priority 110 and the same capped distance penalty, so the choice flipped
between Goldshire and Westfall.  "Always hand in first what is on the same
map; do not go to another map and come back for the other one."

A turn-in's zone comes only from an authoritative source, in this order: the
server POI's turn-in blob (even when another source supplied the
destination), a nearby server ender, the client DB2 QuestPOIBlob turn-in
blob (ObjectiveIndex -1).  Neither a TDB region's ``map_id`` (a copy of the
current UI map) nor a client quest API pin is zone evidence: live 08:23 the
breadcrumb's API waypoint sat on the Elwynn map at the Westfall border, so
the Westfall turn-in looked local and won over Goldshire.  Zones compare by the DB2
UiMap parent chain: a micro/dungeon map belongs to its zone (Fargodeep Mine
39 -> Elwynn Forest 37).  Unknown zones rank between same and other.
"""
from __future__ import annotations

from dataclasses import replace
import math

from .models import number
from .ui_zones import ZoneResolver

TRUSTED_ZONE_PRIORITIES = frozenset({"SERVER_POI", "SERVER_LIVE"})
TURN_IN_PURPOSE = "LOCATE_TURN_IN_REGION"


def _server_poi_ui_map(state: dict, quest_id) -> int | None:
    record = (state.get("packet_quest_pois") or {}).get(str(quest_id)) or {}
    maps = {blob.get("ui_map_id") for blob in record.get("blobs") or ()
            if blob.get("objective_index") == -1 and blob.get("objective_id") == 0}
    maps.discard(None)
    return next(iter(maps)) if len(maps) == 1 else None


def _client_turnin_ui_map(quest_id, zones: ZoneResolver) -> int | None:
    """The client DB2 turn-in blob's UI map (static, always present)."""
    cache = zones.__dict__.setdefault("turnin_maps", {})
    key = str(quest_id)
    if key not in cache:
        maps = set()
        try:
            identifier = int(quest_id)
            details = zones._client().quest(identifier, details=True) or {}
            maps = {row["data"].get("UiMapID") for row in details.get("records") or ()
                    if row.get("table") == "QuestPOIBlob" and row["data"].get("ObjectiveIndex") == -1
                    and not row["data"].get("PlayerConditionID")}
        except Exception:
            maps = set()
        maps.discard(None)
        cache[key] = next(iter(maps)) if len(maps) == 1 else None
    return cache[key]


def turn_in_ui_map(state: dict, quest_id, location: dict, zones: ZoneResolver | None = None) -> int | None:
    value = _server_poi_ui_map(state, quest_id)
    if value is not None:
        return value
    if location.get("knowledge_priority") in TRUSTED_ZONE_PRIORITIES:
        value = location.get("ui_map_id", location.get("map_id"))
        if value is not None:
            return value
    return _client_turnin_ui_map(quest_id, zones) if zones is not None else None


def _distance(state: dict, location: dict) -> float:
    player = state.get("player_world_position") or {}
    px, py = number(player.get("x")), number(player.get("y"))
    x, y = number(location.get("x")), number(location.get("y"))
    if None in (px, py, x, y) or str(location.get("instance_id", player.get("instance_id"))) != str(
            player.get("instance_id")):
        return math.inf
    return math.hypot(x-px, y-py)


def zone_place(state: dict, ui_map, zones: ZoneResolver) -> int:
    """0: the player's zone, 1: unknown, 2: another zone (shared with QuestAgenda)."""
    here, zone = zones.zone(state.get("map_id")), zones.zone(ui_map)
    return 0 if zone is not None and zone == here else 1 if zone is None or here is None else 2


def order_turnins(proposals: list, state: dict, zones: ZoneResolver) -> list:
    """Keep one turn-in MOVE at its priority; the others yield by one point."""
    moves = [(index, proposal) for index, proposal in enumerate(proposals)
             if proposal.skill == "MOVE" and proposal.parameters.get("purpose") == TURN_IN_PURPOSE]
    if len(moves) < 2:
        return proposals
    def rank(item):
        _index, proposal = item
        parameters = proposal.parameters
        place = zone_place(state, turn_in_ui_map(state, parameters.get("quest_id"), parameters, zones), zones)
        return place, _distance(state, parameters), str(parameters.get("quest_id"))

    ordered = sorted(moves, key=rank)
    result = list(proposals)
    for position, (index, proposal) in enumerate(ordered):
        if position:
            result[index] = replace(proposal, priority=proposal.priority - 1.)
    return result
