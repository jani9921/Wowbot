"""Addon map-POI knowledge: API quest givers and dungeon/raid entrances.

User 2026-10-01: find "!" quest givers and dungeon/raid entrances from the
Retail map APIs (``C_QuestLine``, ``C_EncounterJournal``, ``C_TaxiMap``,
``C_AreaPoiInfo``; addon 0.9.37 ``map_pois``) instead of a blind visual
search.  Every record is a location hypothesis: arriving proves only the
area.  The giver itself is still confirmed live (World3D cue, hover, addon
target), and the entrance by the instance transition.

Only Blizzard's explicit same-instance WORLD_YARDS conversion becomes a
navmesh destination; normalized map X/Y never drives movement.
"""
from __future__ import annotations

import math

from .models import Goal, Proposal, number, words
from .planning_types import world_point

API_QUEST_GIVER_PURPOSE = "LOCATE_API_QUEST_GIVER"
INSTANCE_ENTRANCE_PURPOSE = "LOCATE_INSTANCE_ENTRANCE"
POI_KINDS = ("available_quests", "dungeon_entrances", "taxi_nodes", "area_pois")


def map_poi_records(state: dict, kind: str) -> list[dict]:
    pois = state.get("map_pois")
    records = pois.get(kind) if isinstance(pois, dict) else None
    return [record for record in records or () if isinstance(record, dict)]


def soft_interact_giver_waiting(state: dict, selected_guid: str) -> bool:
    """At an API "!" pin (≤ SOFT_INTERACT_YARDS) another friendly NPC is the
    client's soft-interact unit: it, not the selected unit, is the giver."""
    point = _player_point(state)
    if point is None:
        return False
    px, py, _instance = point
    near = any(math.hypot(destination["x"]-px, destination["y"]-py)
               <= MapPoiPlanningPolicy.SOFT_INTERACT_YARDS
               for _distance, _record, destination in reachable_records(state, "available_quests"))
    return near and any(
        isinstance(row, dict) and str(row.get("source_unit") or "").casefold() == "softinteract"
        and str(row.get("unit_type") or "").upper() in {"NPC", "CREATURE"}
        and row.get("is_attackable") is not True and row.get("guid")
        and str(row.get("guid")) != str(selected_guid or "")
        for row in state.get("soft_targets") or ())


def entrance_kind(record: dict) -> str:
    """RAID / DUNGEON from the Encounter Journal pin atlas, else UNKNOWN."""
    atlas = str(record.get("atlas_name") or "").lower()
    if "raid" in atlas:
        return "RAID"
    if "dungeon" in atlas:
        return "DUNGEON"
    return "UNKNOWN"


def _player_point(state: dict) -> tuple[float, float, object] | None:
    position = state.get("player_world_position")
    if not isinstance(position, dict):
        return None
    x, y = number(position.get("x")), number(position.get("y"))
    if x is None or y is None or position.get("instance_id") is None:
        return None
    return x, y, position.get("instance_id")


def reachable_records(state: dict, kind: str) -> list[tuple[float, dict, dict]]:
    """(distance yards, record, WORLD_YARDS point) on the player's instance, nearest first."""
    player = _player_point(state)
    if player is None:
        return []
    px, py, instance = player
    result = []
    for record in map_poi_records(state, kind):
        destination = world_point(record)
        if destination is None or str(destination["instance_id"]) != str(instance):
            continue
        result.append((math.hypot(destination["x"]-px, destination["y"]-py), record, destination))
    result.sort(key=lambda item: item[0])
    return result


class MapPoiPlanningPolicy:
    """Turn API map POIs into navmesh MOVE proposals; owns no input."""

    # Live 2026-10-06 22:12: 7-9 yd from Private Cole's "!" the client's
    # soft-interact unit was Quartermaster Richter next to him; at 4-5 yd it
    # was Private Cole.  Walk right up to the giver.
    ARRIVAL_YARDS = 4.
    # After reaching a giver, stay with it (soft-interact pickup, local
    # search) instead of walking to the next giver at once (live 22:12: the
    # agent reached Henry Garrick's "!", turned round and walked 80 yd back).
    GIVER_LOCAL_SECONDS = 10.
    GIVER_AREA_YARDS = 15.
    SOFT_INTERACT_YARDS = 6.
    SOFT_RETRY_SECONDS = 30.
    # Reached without accepting a quest: the local search (World3D cue,
    # sweep, roam) owns the area; come back to this giver only later.
    REVISIT_SECONDS = 300.
    MAX_ROUTES = 3
    QUEST_GIVER_PRIORITY = 80.
    ENTRANCE_PRIORITY = 66.

    def __init__(self) -> None:
        self.reached_at: dict[tuple, float] = {}

    @staticmethod
    def key(params: dict) -> tuple:
        return (str(params.get("purpose") or ""),
                str(params.get("quest_id") or params.get("journal_instance_id")
                    or params.get("poi_name") or ""),
                round(number(params.get("location_map_x")) or -1., 4),
                round(number(params.get("location_map_y")) or -1., 4))

    def mark_reached(self, params: dict, now: float) -> None:
        if params.get("purpose") in {API_QUEST_GIVER_PURPOSE, INSTANCE_ENTRANCE_PURPOSE}:
            self.reached_at[self.key(params)] = now

    def _recently_reached(self, params: dict, now: float) -> bool:
        reached = self.reached_at.get(self.key(params))
        return reached is not None and 0 <= now-reached < self.REVISIT_SECONDS

    # Campaign first (user 2026-10-03, option B + C): a campaign "!" is always
    # the next pickup; a side quest only when it is on the way (this close)
    # or when no campaign quest is available or in progress.
    SIDE_QUEST_ON_THE_WAY_YARDS = 60.
    QUEST_LOG_SOFT_LIMIT = 30

    @staticmethod
    def campaign_in_progress(state: dict) -> bool:
        return any(isinstance(quest, dict) and quest.get("is_campaign") is True
                   for quest in state.get("active_quests") or ())

    def _giver_candidates(self, state: dict) -> list[tuple[float, dict, dict]]:
        records = reachable_records(state, "available_quests")
        active = [quest for quest in state.get("active_quests") or () if isinstance(quest, dict)]
        if len(active) >= self.QUEST_LOG_SOFT_LIMIT:
            return []
        campaign = [row for row in records if row[1].get("is_campaign") is True]
        side = [row for row in records if row[1].get("is_campaign") is not True]
        campaign_active = self.campaign_in_progress(state)
        chosen = [] if campaign_active else list(campaign)
        if not active and not chosen:
            # No quest in the log and no campaign pickup here (level or chain
            # gate): side quests carry on (option C).
            chosen = list(side)
        else:
            # Option B: side quests that are on the way.
            chosen += [row for row in side if row[0] <= self.SIDE_QUEST_ON_THE_WAY_YARDS]
        return sorted(chosen, key=lambda row: (row[1].get("is_campaign") is not True, row[0]))

    # Live 2026-10-05 (05:39 and 12:24): the follow-up "!" pins of a turn-in
    # arrive 7-14 s after it.  At 12:24 the agent left for Private Cole's pin
    # (85 yd) 2 s after turning in to Bjorn; Alaria's new pin then appeared
    # 2 yd from where it had stood, and it walked back (user).  Hold the pin
    # routes until the pin list changes or this much time has passed.
    POST_TURN_IN_SETTLE_SECONDS = 10.

    def _settling_after_turn_in(self, state: dict, now: float) -> bool:
        active = frozenset(str(quest.get("quest_id")) for quest in state.get("active_quests") or ()
                           if isinstance(quest, dict))
        pins = frozenset(str(record.get("quest_id")) for record in map_poi_records(state, "available_quests"))
        previous = self.__dict__.get("_last_active_quests")
        self.__dict__["_last_active_quests"] = active
        if previous is not None and previous - active:
            self.__dict__["_turn_in_settle"] = (now, pins)    # a quest left the log
        settle = self.__dict__.get("_turn_in_settle")
        if settle is None:
            return False
        if not 0 <= now-settle[0] < self.POST_TURN_IN_SETTLE_SECONDS or pins != settle[1]:
            self.__dict__.pop("_turn_in_settle", None)
            return False
        return True

    def quest_giver_moves(self, world, now: float | None = None) -> list[Proposal]:
        """Walk to API "!" givers: campaign first, side quests only on the way."""
        state = world.state
        if state.get("is_in_combat"):
            return []
        now = number(state.get("monotonic_time")) if now is None else now
        now = 0. if now is None else now
        if self._settling_after_turn_in(state, now):
            return []
        result = []
        candidates = self._giver_candidates(state)
        for row in candidates:
            arrived = self._giver_params(row)
            if row[0] <= self.ARRIVAL_YARDS and not self._recently_reached(arrived, now):
                self.mark_reached(arrived, now)
        focused = [row for row in candidates if row[0] <= self.GIVER_AREA_YARDS
                   and self._reached_within(self._giver_params(row), now, self.GIVER_LOCAL_SECONDS)]
        for distance, record, destination in candidates:
            if focused and record is not focused[0][1]:
                continue                       # stay with the giver just reached
            params = {
                **destination,
                "quest_id": record.get("quest_id"),
                "quest_name": record.get("quest_name"),
                "location_map_x": record.get("x"),
                "location_map_y": record.get("y"),
                "location_source": record.get("source"),
                "purpose": API_QUEST_GIVER_PURPOSE,
                "stop_distance": self.ARRIVAL_YARDS,
                "require_navmesh": True,
            }
            if distance <= self.ARRIVAL_YARDS and not self._recently_reached(params, now):
                # Already at the giver: the soft-interact pickup and the local
                # perception take over.
                self.mark_reached(params, now)
            if distance <= self.SOFT_INTERACT_YARDS:
                pickup = self._soft_interact_pickup(state, params, record, now)
                if pickup is not None:
                    result.append(pickup)
                    continue
            if distance <= self.ARRIVAL_YARDS:
                continue
            if self._recently_reached(params, now) and not focused:
                continue
            campaign = record.get("is_campaign") is True
            params["is_campaign"] = campaign
            result.append(Proposal.make(
                "MOVE", ("Quest API: kampány quest giver ('!') helye; ott helyi vizuális azonosítás"
                         if campaign else
                         "Quest API: elérhető quest giver ('!') helye; ott helyi vizuális azonosítás"),
                params, confidence=.75,
                priority=self.QUEST_GIVER_PRIORITY + (4. if campaign else 0.) - .5*len(result)))
            if len(result) >= self.MAX_ROUTES:
                break
        return result

    @staticmethod
    def _giver_params(row) -> dict:
        _distance, record, destination = row
        return {**destination, "quest_id": record.get("quest_id"),
                "location_map_x": record.get("x"), "location_map_y": record.get("y"),
                "purpose": API_QUEST_GIVER_PURPOSE}

    def _reached_within(self, params: dict, now: float, seconds: float) -> bool:
        reached = self.reached_at.get(self.key(params))
        return reached is not None and 0 <= now-reached < seconds

    def _soft_interact_pickup(self, state: dict, params: dict, record: dict, now: float) -> Proposal | None:
        """At the giver's "!": the client's soft-interact friendly NPC is the
        one in front of us; the Interact key opens its quest/gossip window.
        Each NPC is tried once per giver (a vendor next to it is not retried)."""
        tried = self.__dict__.setdefault("_soft_tried", {})
        for row in state.get("soft_targets") or ():
            if (not isinstance(row, dict)
                    or str(row.get("source_unit") or "").casefold() != "softinteract"
                    or str(row.get("unit_type") or "").upper() not in {"NPC", "CREATURE"}
                    or row.get("is_attackable") is True or row.get("is_dead") is True
                    or not row.get("guid")):
                continue
            key = (self.key(params), str(row["guid"]))
            if 0 <= now - tried.get(key, -1e9) < self.SOFT_RETRY_SECONDS:
                continue
            tried[key] = now
            return Proposal.make(
                "INTERACT", "Quest-adó \"!\" helyén a kliens soft-interact NPC-je: interact billentyű",
                {"activation_source": "SOFT_INTERACT", "soft_guid": row["guid"],
                 "npc_id": row.get("npc_id"), "npc_name": row.get("name"),
                 "purpose": "PICKUP_API_QUEST", "quest_id": record.get("quest_id"),
                 "is_campaign": record.get("is_campaign") is True},
                # One key press per NPC and giver: above a stale selected-
                # friendly approach (102), cannot loop.
                confidence=.8, priority=104, evidence=("api_giver_reached", "soft_interact_npc"))
        return None

    def entrance_moves(self, world, goal: Goal, now: float | None = None) -> list[Proposal]:
        """DUNGEON/raid goal outside the instance: walk to the API entrance."""
        state = world.state
        if state.get("is_in_combat"):
            return []
        now = number(state.get("monotonic_time")) if now is None else now
        now = 0. if now is None else now
        text = words(goal.text)
        wanted = "RAID" if "raid" in text else "DUNGEON" if "dungeon" in text else None
        candidates = reachable_records(state, "dungeon_entrances")
        named = [item for item in candidates
                 if (name := words(str(item[1].get("name") or ""))) and name in text]
        if named:
            candidates = named
        elif wanted:
            candidates = [item for item in candidates
                          if entrance_kind(item[1]) in {wanted, "UNKNOWN"}]
        result = []
        for distance, record, destination in candidates:
            params = {
                **destination,
                "poi_name": record.get("name"),
                "journal_instance_id": record.get("journal_instance_id"),
                "entrance_kind": entrance_kind(record),
                "location_map_x": record.get("x"),
                "location_map_y": record.get("y"),
                "location_source": record.get("source"),
                "purpose": INSTANCE_ENTRANCE_PURPOSE,
                "stop_distance": 4.,
                "require_navmesh": True,
            }
            if distance <= 4. or self._recently_reached(params, now):
                continue
            result.append(Proposal.make(
                "MOVE", "Encounter Journal API: dungeon/raid bejárat helye",
                params, confidence=.8, priority=self.ENTRANCE_PRIORITY - .5*len(result)))
            if len(result) >= self.MAX_ROUTES:
                break
        return result

    @staticmethod
    def status(state: dict) -> dict[str, object]:
        """Compact knowledge summary for diagnostics."""
        summary: dict[str, object] = {
            kind: len(map_poi_records(state, kind)) for kind in POI_KINDS}
        summary["instance_entrances"] = [
            {"name": record.get("name"), "kind": entrance_kind(record),
             "journal_instance_id": record.get("journal_instance_id")}
            for record in map_poi_records(state, "dungeon_entrances")]
        return summary
