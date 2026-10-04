"""Evidence-ordered completion resolver; it never sends input or invents NPCs."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import number
from .planning_types import world_point


class TurnInLocationKind(StrEnum):
    FIELD_UI = "FIELD_UI"
    LOCAL_ENTITY = "LOCAL_ENTITY"
    TURN_IN_LOCATION = "TURN_IN_LOCATION"
    QUEST_API_REGION = "QUEST_API_REGION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TurnInResolution:
    kind: TurnInLocationKind
    location: dict | None = None
    entity_guid: str | None = None
    completion_mode: str = "UNKNOWN"
    confidence: float = 0.
    evidence: tuple[str, ...] = ()


class TurnInResolver:
    """Resolve only proven completion surfaces in conservative order.

    A location is a bounded search region, never a claim that an NPC is there.
    In particular an arbitrary remembered quest waypoint must not move the
    player for a completed quest.  The resolver accepts only a declared
    turn-in role or a current Quest API completion waypoint.
    """

    def locate(self, record, state: dict, completion_mode: str = "UNKNOWN") -> TurnInResolution:
        mode = str(completion_mode or "UNKNOWN").upper()
        ui = state.get("quest_ui") or {}
        ui_action = str(ui.get("action") or state.get("quest_ui_action") or "").upper()
        if ui_action in {"COMPLETE", "TURN_IN", "REWARD_SELECT"}:
            return TurnInResolution(TurnInLocationKind.FIELD_UI, completion_mode="FIELD_TURN_IN",
                                    confidence=1., evidence=("quest_ui_completion_action",))

        target = state.get("target") or {}
        target_role = str(target.get("quest_role") or target.get("role") or "").upper()
        if (target.get("guid") and target.get("attackable", target.get("is_attackable")) is False
                and target_role in {"TURN_IN", "QUEST_TURN_IN"}):
            return TurnInResolution(TurnInLocationKind.LOCAL_ENTITY,
                                    entity_guid=str(target["guid"]), completion_mode="NPC_TURN_IN",
                                    confidence=.98, evidence=("live_target_turn_in_role",))

        locations = tuple(getattr(record, "known_locations", ()) or ())
        declared = next((self._point(location) for location in locations
                         if str(location.get("role") or "").upper() in {"TURN_IN", "QUEST_TURN_IN"}
                         and self._point(location)), None)
        if declared:
            return TurnInResolution(TurnInLocationKind.TURN_IN_LOCATION, declared,
                                    completion_mode="NPC_TURN_IN", confidence=.82,
                                    evidence=("declared_turn_in_location",))
        if mode == "NPC_TURN_IN":
            mode_location = next((self._point(location) for location in locations
                                  if self._point(location)), None)
            if mode_location:
                return TurnInResolution(TurnInLocationKind.TURN_IN_LOCATION, mode_location,
                                        completion_mode=mode, confidence=.65,
                                        evidence=("declared_npc_turn_in_mode",))
        waypoint = next((self._point(location) for location in locations
                         if str(location.get("source") or "").upper() == "QUEST_API_WAYPOINT"
                         and self._point(location)), None)
        if waypoint:
            return TurnInResolution(TurnInLocationKind.QUEST_API_REGION, waypoint,
                                    completion_mode=mode, confidence=.6,
                                    evidence=("current_quest_api_waypoint",))
        return TurnInResolution(TurnInLocationKind.UNKNOWN, completion_mode=mode)

    @staticmethod
    def _point(value) -> dict | None:
        if not isinstance(value, dict):
            return None
        converted = world_point(value)
        if converted:
            return converted
        x, y = number(value.get("x")), number(value.get("y"))
        map_id = value.get("map_id", value.get("world_map_id"))
        if x is None or y is None or map_id is None:
            return None
        return {**value, "x": x, "y": y, "map_id": map_id}
