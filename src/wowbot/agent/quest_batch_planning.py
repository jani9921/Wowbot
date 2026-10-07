"""Batch nearby quests before walking back to turn them in (user 2026-10-03).

"When several quests point to one place, or very close to each other, do them
first and turn them in together -- not one, walk back to turn it in, then
return to the same place."  A completed quest's turn-in trip is therefore
deferred while another quest in the log still has an objective area close to
the player.  Locations come only from the Quest API map POIs
(``quest_locations`` with an explicit WORLD_YARDS conversion).
"""
from __future__ import annotations

import math

from .models import number
from .planning_types import world_point


class QuestBatchPolicy:
    # An unfinished objective area this close is worked on before a turn-in.
    BATCH_RADIUS_YARDS = 120.
    # A turn-in point this close is handed in right away (it is "on the way").
    TURN_IN_HERE_YARDS = 40.
    # Never keep a finished quest waiting longer than this.
    MAX_DEFER_SECONDS = 600.
    # Issue #90: an objective this far above/below (known Z on both sides) is
    # on another floor -- a cave route, not "nearby work".
    MAX_FLOOR_DZ_YARDS = 15.

    def __init__(self) -> None:
        self.completed_since: dict[str, float] = {}

    @staticmethod
    def _known_z(point: dict) -> float | None:
        if point.get("z_known") is False or point.get("z_estimated") is True:
            return None
        return number(point.get("z"))

    @classmethod
    def _player(cls, state: dict) -> tuple[float, float, object, float | None] | None:
        position = state.get("player_world_position") or {}
        x, y = number(position.get("x")), number(position.get("y"))
        if x is None or y is None:
            return None
        return x, y, position.get("instance_id"), cls._known_z(position)

    @staticmethod
    def locations(state: dict) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for location in state.get("quest_locations") or ():
            point = world_point(location) if isinstance(location, dict) else None
            if point is not None and location.get("quest_id") is not None:
                result.setdefault(str(location["quest_id"]), []).append(point)
        return result

    @classmethod
    def _distance(cls, player, point: dict) -> float | None:
        if player is None:
            return None
        if (player[2] is not None and point.get("instance_id") is not None
                and str(player[2]) != str(point["instance_id"])):
            return None
        point_z = cls._known_z(point)
        if (player[3] is not None and point_z is not None
                and abs(point_z - player[3]) > cls.MAX_FLOOR_DZ_YARDS):
            return None      # another floor: neither nearby work nor "here"
        return math.hypot(float(point["x"]) - player[0], float(point["y"]) - player[1])

    def deferred_turnins(self, state: dict, now: float | None) -> frozenset[str]:
        """Completed quest IDs whose turn-in trip should wait for now."""
        quests = [quest for quest in state.get("active_quests") or ()
                  if isinstance(quest, dict) and quest.get("quest_id") is not None]
        complete = {str(quest["quest_id"]) for quest in quests if quest.get("is_complete") is True}
        incomplete = {str(quest["quest_id"]) for quest in quests if quest.get("is_complete") is not True}
        for quest_id in list(self.completed_since):
            if quest_id not in complete:
                del self.completed_since[quest_id]
        if now is not None:
            for quest_id in complete:
                self.completed_since.setdefault(quest_id, now)
        if not complete or not incomplete:
            return frozenset()
        player = self._player(state)
        places = self.locations(state)
        nearby_work = any(
            (distance := self._distance(player, point)) is not None
            and distance <= self.BATCH_RADIUS_YARDS
            for quest_id in incomplete for point in places.get(quest_id, ()))
        if not nearby_work:
            return frozenset()
        deferred = set()
        for quest_id in complete:
            since = self.completed_since.get(quest_id)
            if now is not None and since is not None and now - since > self.MAX_DEFER_SECONDS:
                continue
            here = any((distance := self._distance(player, point)) is not None
                       and distance <= self.TURN_IN_HERE_YARDS
                       for point in places.get(quest_id, ()))
            if not here:
                deferred.add(quest_id)
        return frozenset(deferred)
