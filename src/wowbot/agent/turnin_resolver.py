"""Evidence-ordered completion resolver; it never sends input or invents NPCs."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from wowbot.query_ports import TravelCostPort
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


def known_ender_entries(state: dict, quest_id) -> set[str]:
    """Creature entries that end this quest (TDB roles, learned, remembered)."""
    reference = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(quest_id)) or {}
    enders = {str(row.get("npc_id")) for row in reference.get("quest_roles") or ()
              if isinstance(row, dict) and row.get("role") == "QUEST_ENDER"}
    remembered = ((state.get("quest_turn_in_names") or {}).get(str(quest_id)) or {}).get("npc_id")
    if remembered is not None:
        enders.add(str(remembered))
    return enders


def located_entries(state: dict, entries: set[str], radius: float) -> list[tuple[float, dict, dict]]:
    """Server-located units (Ymir) of these entries, nearest first."""
    import math
    from .packet_entity_facts import best_position
    entities, player = state.get("packet_entities"), state.get("player_world_position") or {}
    px, py = number(player.get("x")), number(player.get("y"))
    if not isinstance(entities, dict) or px is None or py is None or not entries:
        return []
    result = []
    for value in entities.values():
        if (not isinstance(value, dict) or value.get("removed") or value.get("kind") not in {"CREATURE", "VEHICLE"}
                or str(value.get("entry_id")) not in entries):
            continue
        point = best_position(value)
        if point is None or str(point["instance_id"]) != str(player.get("instance_id")):
            continue
        distance = math.hypot(point["x"]-px, point["y"]-py)
        if distance <= radius:
            result.append((distance, value, point))
    return sorted(result, key=lambda row: row[0])


class TurnInResolver:
    """Resolve only proven completion surfaces in conservative order.

    A location is a bounded search region, never a claim that an NPC is there.
    In particular an arbitrary remembered quest waypoint must not move the
    player for a completed quest.  The resolver accepts only a declared
    turn-in role or a current Quest API completion waypoint.
    """

    def __init__(self, *, travel_cost: TravelCostPort | None = None):
        self.travel_cost = travel_cost

    def locate(self, record, state: dict, completion_mode: str = "UNKNOWN") -> TurnInResolution:
        mode = str(completion_mode or "UNKNOWN").upper()
        ui = state.get("quest_ui") or {}
        ui_action = str(ui.get("action") or state.get("quest_ui_action") or "").upper()
        if ui_action in {"COMPLETE", "TURN_IN", "REWARD_SELECT"}:
            return TurnInResolution(TurnInLocationKind.FIELD_UI, completion_mode="FIELD_TURN_IN",
                                    confidence=1., evidence=("quest_ui_completion_action",))

        target = state.get("target") or {}
        server = self.server_ender(record, state)
        if server is not None:
            from .server_npc_planning import server_npc_interaction_ready
            ready = server_npc_interaction_ready(state, server["server_entity_guid"], server)
            evidence = ("server_quest_ender_position",)
            if server.get("quest_ender_basis") == "UNIQUE_SERVER_REWARD_CANDIDATE":
                evidence += ("server_reward_candidate_requires_quest_ui",)
            if ready:
                evidence += ("soft_interact_guid_match",)
            return TurnInResolution(
                TurnInLocationKind.LOCAL_ENTITY if ready else TurnInLocationKind.TURN_IN_LOCATION,
                server, entity_guid=server["server_entity_guid"], completion_mode="NPC_TURN_IN",
                confidence=.98 if ready else .95,
                evidence=evidence)
        from .quest_poi_evidence import current_turnin_poi
        server_poi = current_turnin_poi(state, getattr(record, 'quest_id', None))
        target_role = str(target.get("quest_role") or target.get("role") or "").upper()
        if (target.get("guid") and target.get("attackable", target.get("is_attackable")) is False
                and target_role in {"TURN_IN", "QUEST_TURN_IN"}
                and (server_poi is None or str(target.get("quest_id")) == str(getattr(record, 'quest_id', None)))):
            return TurnInResolution(TurnInLocationKind.LOCAL_ENTITY,
                                    entity_guid=str(target["guid"]), completion_mode="NPC_TURN_IN",
                                    confidence=.98, evidence=("live_target_turn_in_role",))

        from .tdb_locations import role_region
        if server_poi is not None:
            packet = server_poi.get('knowledge_priority') == 'SERVER_POI'
            if not packet and server_poi.get('z_known') is not True:
                # Only an agreeing static ender may supply the missing floor.
                # The current API pin keeps its XY and location authority;
                # a cheaper historical spawn elsewhere cannot replace it.
                hint = role_region(state, getattr(record, 'quest_id', None), 'QUEST_ENDER',
                                   live_location=server_poi, travel_cost=self.travel_cost)
                if hint and hint.get('z_known') is True:
                    server_poi = {**server_poi, 'z': hint['z'], 'z_known': True,
                        'z_estimated': True, 'z_observed': False, 'z_source': hint.get('z_source'),
                        'z_confidence': hint.get('z_confidence', .8),
                        'z_knowledge_priority': 'PRIMARY_STATIC',
                        'height_reference_hint_id': hint.get('reference_hint_id')}
            return TurnInResolution(TurnInLocationKind.QUEST_API_REGION, server_poi,
                                    completion_mode='NPC_TURN_IN', confidence=.95,
                                    evidence=('current_server_turnin_poi' if packet
                                              else 'current_quest_api_turnin_poi',))
        locations = tuple(getattr(record, "known_locations", ()) or ())
        live_turnin = next((location for location in locations
                            if isinstance(location, dict)
                            and (str(location.get('role') or '').upper() in {'TURN_IN', 'QUEST_TURN_IN'}
                                 or str(location.get('source') or '').upper() == 'QUEST_API_WAYPOINT')
                            and world_point(location)), None)
        primary = role_region(state, getattr(record, 'quest_id', None), 'QUEST_ENDER',
                              live_location=live_turnin, travel_cost=self.travel_cost)
        if primary:
            return TurnInResolution(TurnInLocationKind.TURN_IN_LOCATION, primary,
                                    completion_mode='NPC_TURN_IN', confidence=.75,
                                    evidence=('tdb_primary_explicit_ender_spawn',))

        declared = next((self._point(location) for location in locations
                         if str(location.get("role") or "").upper() in {"TURN_IN", "QUEST_TURN_IN"}
                         and self._point(location)), None)
        if declared:
            return TurnInResolution(TurnInLocationKind.TURN_IN_LOCATION, declared,
                                    completion_mode="NPC_TURN_IN", confidence=.82,
                                    evidence=("declared_turn_in_location",))
        if mode == "NPC_TURN_IN":
            # Issue #89: NPC_TURN_IN is a completion mode, not location proof.
            # An objective/giver/memory point with a non-turn-in role is
            # never the hand-in destination.
            mode_location = next((self._point(location) for location in locations
                                  if str(location.get("role") or "").upper()
                                  in {"", "TURN_IN", "QUEST_TURN_IN"}
                                  and self._point(location)), None)
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

    SERVER_ENDER_YARDS = 150.

    @classmethod
    def server_ender(cls, record, state: dict) -> dict | None:
        """A unit the server shows with a yellow "?" (Ymir) that ends this quest.

        A current server reward marker outranks a historical ender entry.
        QuestGiverStatus names a GUID, not a quest id: a previously unknown
        ender is only a candidate when one finished quest and one reward
        marker make it unambiguous. Opening its UI must confirm the quest;
        this resolution neither rewrites the TDB nor proves completion.
        """
        from .packet_entity_facts import quest_givers
        quest_id = str(getattr(record, "quest_id", record) or "")
        enders = known_ender_entries(state, quest_id)
        givers = quest_givers(state, available=False, reward=True, radius=cls.SERVER_ENDER_YARDS)
        chosen = next((row for row in givers if str(row[1].get("entry_id")) in enders), None)
        basis = "KNOWN_ENTRY_SERVER_REWARD"
        finished = [quest for quest in state.get("active_quests") or ()
                    if isinstance(quest, dict) and quest.get("is_complete") is True]
        if (chosen is None and len(givers) == 1 and len(finished) == 1
                and str(finished[0].get("quest_id")) == quest_id):
            # A server-side change/phasing can replace the stored ender.
            # Do not pin navigation to a visible but obsolete TDB spawn.
            chosen = givers[0]
            basis = "UNIQUE_SERVER_REWARD_CANDIDATE"
        if chosen is None:
            # User 2026-10-20: once near the turn-in the server has sent the
            # ender's own create block -- use its exact point even when no
            # yellow "?" status arrived, unless the server says it is not ours.
            chosen = next((row for row in located_entries(state, enders, float("inf"))
                           if (row[1].get("quest_giver") or {}).get("reward_ready") is not False), None)
            basis = "KNOWN_ENTRY_SERVER_POSITION"
        if chosen is None:
            return None
        _distance, value, point = chosen
        from .packet_entity_facts import travel_position
        travel = travel_position(value) or {}
        point = {**point, **{axis: travel[axis] for axis in ("x", "y", "z") if axis in travel}}
        return {"x": point["x"], "y": point["y"], "z": point["z"], "z_known": True,
                "instance_id": point["instance_id"], "coordinate_space": "WORLD_YARDS",
                "map_id": state.get("map_id"), "source": "PACKET_QUEST_GIVER_STATUS",
                "knowledge_priority": "SERVER_LIVE", "server_entity_guid": value["guid"],
                "quest_ender_basis": basis,
                "npc_id": value.get("entry_id"), "stop_distance": 3.0, "face_on_arrival": True}

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
