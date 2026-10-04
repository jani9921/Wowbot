"""Evidence-ordered M1 objective location resolver.

It resolves a location hypothesis only. The shared Planner remains responsible
for selecting an M0 skill; this module never emits input or a route.
"""
from __future__ import annotations

from dataclasses import dataclass

from wowbot.runtime import ObjectiveLocationStatus
from .models import number, words


@dataclass(frozen=True)
class ObjectiveLocation:
    status: ObjectiveLocationStatus
    coordinates: dict | None = None
    confidence: float = 0.
    evidence: tuple[str, ...] = ()


class ObjectiveLocator:
    def locate(self, objective, record, state: dict) -> ObjectiveLocation:
        target = state.get("target") or {}
        entity = objective.target_entity or {}
        if self._matches(target, entity):
            return ObjectiveLocation(ObjectiveLocationStatus.LOCAL_ENTITY, confidence=.98,
                                     evidence=("selected_target_matches_objective",))
        location = self._valid_location(objective.target_location)
        if location:
            status = (ObjectiveLocationStatus.LOCAL_MARKER
                      if location.get("map_id") == state.get("map_id")
                      else ObjectiveLocationStatus.WORLD_MAP_LOCATION)
            return ObjectiveLocation(status, location, objective.confidence,
                                     ("objective_api_location",))
        for location in getattr(record, "known_locations", ()):
            valid = self._valid_location(location)
            if valid:
                status = (ObjectiveLocationStatus.LOCAL_MARKER
                          if valid.get("map_id") == state.get("map_id")
                          else ObjectiveLocationStatus.WORLD_MAP_LOCATION)
                return ObjectiveLocation(status, valid, .75, ("quest_known_location",))
        candidates = tuple(getattr(objective, "location_candidates", ()) or ())
        if candidates:
            candidate = max(candidates, key=lambda item: number(item.get("confidence")) or 0.)
            valid = self._valid_location(candidate)
            if valid:
                return ObjectiveLocation(ObjectiveLocationStatus.KNOWN_LOCATION, valid,
                                         number(candidate.get("confidence")) or .0,
                                         (str(candidate.get("source") or "location_memory"),))
        search_area = self._valid_location((getattr(objective, "raw", {}) or {}).get("search_area"))
        if search_area:
            return ObjectiveLocation(ObjectiveLocationStatus.SEARCH_AREA, search_area, .5,
                                     ("objective_search_area",))
        if (getattr(objective, "raw", {}) or {}).get("transition_required") is True:
            return ObjectiveLocation(ObjectiveLocationStatus.TRANSITION_REQUIRED, confidence=.8,
                                     evidence=("objective_transition_required",))
        return ObjectiveLocation(ObjectiveLocationStatus.UNKNOWN)

    @staticmethod
    def _valid_location(value) -> dict | None:
        if not isinstance(value, dict):
            return None
        x, y = number(value.get("x")), number(value.get("y"))
        if x is None or y is None or value.get("map_id") is None:
            return None
        return {**value, "x": x, "y": y}

    @staticmethod
    def _matches(target: dict, entity: dict) -> bool:
        if not target or not entity:
            return False
        if entity.get("npc_id") is not None and target.get("npc_id") is not None:
            return str(entity["npc_id"]) == str(target["npc_id"])
        expected, actual = words(str(entity.get("name") or "")), words(str(target.get("name") or ""))
        return bool(expected and actual and expected == actual)
