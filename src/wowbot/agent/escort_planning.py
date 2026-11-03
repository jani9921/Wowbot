"""Classic escort from server facts (playbook E2): stay with what we escort.

Live 2026-10-28 12:05:11-13:04 (Black Wagon Flight 65793, "Escort the
wagon"): after "Let's get moving." the server summoned our own Inconspicuous
Wagon with Sabellian, Wrathion and two Expedition Shires, all created by us.
The agent flew to the quest's map POI -- the escort's destination, 535 yd
south -- the group fell out of range at 12:05:23 and the agent waited 59 min.

The subject is a unit the server shows as created/summoned by us whose entry
the objective names (``escort_creatures``, TDB).  Beyond FOLLOW_YARDS a MOVE
walks to it; close by, a WAIT_EVENT holds us there so no other quest or
search pulls us away.  When it leaves our view we go back to where we last
saw it.  Fighting stays with the combat policies (they run first).
"""
from __future__ import annotations

import math

from .models import Proposal, number
from .packet_entity_facts import best_position, travel_position, unit_dead, unit_facts

FOLLOW_YARDS = 12.        # farther than this: walk after it
STOP_YARDS = 6.
LEAD_YARDS = 25.          # walk to its spline end when that is this near
HOLD_SECONDS = 8.         # re-check the hold this often
REMEMBER_SECONDS = 1800.
LOST_YARDS = 15.          # back where we last saw it and still nothing: give up
PRIORITY = 101
DEFEND_YARDS = 40.        # attackers of the escorted unit this near it are ours to kill


def escort_objectives(state: dict) -> list[tuple[str, dict]]:
    """(quest id, TDB objective row) of open ESCORT objectives of open quests."""
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    result = []
    for quest in state.get("active_quests") or ():
        if (not isinstance(quest, dict) or quest.get("is_complete") is True
                or quest.get("is_failed") is True):
            continue
        texts = [str(row.get("description") or "").casefold() for row in quest.get("objectives") or ()
                 if isinstance(row, dict) and row.get("is_complete") is not True]
        quest_id = str(quest.get("quest_id"))
        for row in (reference.get(quest_id) or {}).get("objectives") or ():
            text = str(row.get("description") or "").strip().casefold() if isinstance(row, dict) else ""
            if row.get("mechanism") == "ESCORT" and row.get("escort_creatures") and text and any(
                    text in open_text for open_text in texts):
                result.append((quest_id, row))
    return result


def escort_subject(state: dict, row: dict) -> tuple[float, dict, dict] | None:
    """(flat yards, entity, point) of the nearest created-by-us subject in view."""
    entries = {str(item.get("entry")) for item in row.get("escort_creatures") or () if isinstance(item, dict)}
    player = state.get("player_world_position") or {}
    px, py = number(player.get("x")), number(player.get("y"))
    if px is None or py is None:
        return None
    best = None
    for value in (state.get("packet_entities") or {}).values():
        unit = unit_facts(value)
        if (not isinstance(value, dict) or value.get("kind") not in {"CREATURE", "VEHICLE"}
                or value.get("removed") or str(value.get("entry_id")) not in entries
                or not (unit.get("created_by_me") is True or unit.get("summoned_by_me") is True)
                or unit_dead(value)):
            continue
        point = best_position(value)
        if point is None or str(point.get("instance_id")) != str(player.get("instance_id")):
            continue
        flat = math.hypot(point["x"]-px, point["y"]-py)
        if best is None or flat < best[0]:
            best = (flat, value, point)
    return best


def escort_attackers(state: dict) -> list[dict]:
    """REV4 P8.4 (E2): live hostiles the server shows targeting an escorted
    unit, as kill-target rows (``kill_objective_units`` shape).

    "The mobs attack the NPC, not us" (QUEST_PLAYBOOKS E2): with only our own
    attackers known, the escort died while we held next to it.  The server's
    unit target field names its victim; the escort is ours (created/summoned
    by us).  Selection still goes by Tab with the exact GUID."""
    from .packet_entity_facts import unit_unattackable
    subjects = {}
    for quest_id, row in escort_objectives(state):
        seen = escort_subject(state, row)
        if seen is not None:
            subjects[str(seen[1]["guid"])] = (quest_id, row, seen[2])
    if not subjects:
        return []
    result = []
    for value in (state.get("packet_entities") or {}).values():
        unit = unit_facts(value)
        victim = str(unit.get("target_entity") or "")
        if (not isinstance(value, dict) or value.get("kind") not in {"CREATURE", "VEHICLE"}
                or value.get("removed") or victim not in subjects or unit_dead(value)
                or unit_unattackable(value) or unit.get("created_by_me") is True
                or unit.get("summoned_by_me") is True):
            continue
        point = best_position(value)
        quest_id, row, subject_point = subjects[victim]
        if (point is None or str(point.get("instance_id")) != str(subject_point.get("instance_id"))
                or math.hypot(point["x"]-subject_point["x"], point["y"]-subject_point["y"]) > DEFEND_YARDS):
            continue
        result.append({**point, "guid": value["guid"], "entry_id": value.get("entry_id"),
                       "quest_id": quest_id, "objective_id": f"{quest_id}:{row.get('order')}",
                       "targets_me": unit.get("targets_me") is True, "escort_attacker": True,
                       "escort_guid": victim})
    return result


def failed_escorts(state: dict) -> list[str]:
    """Quest ids of failed quests (addon 0.9.82 ``is_failed``) with an escort objective."""
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    return [str(quest.get("quest_id")) for quest in state.get("active_quests") or ()
            if isinstance(quest, dict) and quest.get("is_failed") is True
            and any(isinstance(row, dict) and row.get("mechanism") == "ESCORT"
                    for row in (reference.get(str(quest.get("quest_id"))) or {}).get("objectives") or ())]


class EscortPolicy:
    def __init__(self) -> None:
        self.last_seen: dict[str, dict] = {}       # quest id -> {point, guid, at}

    def filter_travel(self, proposals: list[Proposal], state: dict) -> list[Proposal]:
        """An engaged escort's destination POI is not its next follow point.

        Apply before failure/ranking suppression: a temporary hold recheck
        cannot make a higher-priority destination MOVE outrun the escort.
        Combat and loot retain their independent proposals.
        """
        now = number(state.get("monotonic_time"))
        if now is None:
            return proposals
        engaged = {qid for qid, row in escort_objectives(state)
                   if escort_subject(state, row) is not None or
                   (qid in self.last_seen and 0 <= now-self.last_seen[qid]["at"] <= REMEMBER_SECONDS)}
        if not engaged:
            return proposals
        result = []
        for proposal in proposals:
            params = proposal.parameters
            purpose = str(params.get("purpose") or "")
            if (proposal.skill == "MOVE"
                    and purpose not in {"ESCORT_FOLLOW", "ESCORT_RETURN", "APPROACH_SERVER_KILL_TARGET"}
                    and not purpose.startswith(("COMBAT", "LOOT", "APPROACH_SERVER_LOOT"))
                    and params.get("allow_combat") is not True):
                continue
            result.append(proposal)
        return result

    def propose(self, state: dict) -> list[Proposal]:
        now = number(state.get("monotonic_time"))
        if now is None or state.get("is_in_combat") or state.get("in_vehicle") is True:
            return []
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        if escort_attackers(state):
            # The server-GUID kill flow selects and fights them; holding the
            # escort here would let it die (P8.4 E2).
            return []
        open_quests = set()
        for quest_id, row in escort_objectives(state):
            open_quests.add(quest_id)
            seen = escort_subject(state, row)
            if seen is not None:
                flat, value, point = seen
                guid = str(value["guid"])
                self.last_seen[quest_id] = {"point": dict(point), "guid": guid, "at": now}
                if flat <= FOLLOW_YARDS:
                    return [Proposal.make(
                        "WAIT_EVENT", "Kísérés: a kísért egység mellett maradok, amíg halad",
                        {"quest_ids": [quest_id], "objective_kind": "ESCORT",
                         "objective_text": row.get("description"), "server_entity_guid": guid,
                         "escort_follow_yards": FOLLOW_YARDS, "wait_seconds": HOLD_SECONDS},
                        confidence=.85, priority=PRIORITY, evidence=("server_escort_subject", "objective_escort"))]
                ahead = travel_position(value) or point
                if px is not None and math.hypot(ahead["x"]-point["x"], ahead["y"]-point["y"]) > LEAD_YARDS:
                    ahead = point
                return [self._move(state, quest_id, row, ahead, guid, "ESCORT_FOLLOW",
                                   "Kísérés: a kísért egység után megyek")]
            memory = self.last_seen.get(quest_id)
            if memory is None or not 0 <= now-memory["at"] <= REMEMBER_SECONDS or px is None:
                continue
            spot = memory["point"]
            if math.hypot(spot["x"]-px, spot["y"]-py) <= LOST_YARDS:
                self.last_seen.pop(quest_id, None)   # it is not where we left it
                continue
            return [self._move(state, quest_id, row, spot, memory["guid"], "ESCORT_RETURN",
                               "Kísérés: vissza oda, ahol a kísért egységet utoljára láttam")]
        for quest_id in set(self.last_seen) - open_quests:
            self.last_seen.pop(quest_id, None)
        failed = failed_escorts(state)
        if failed:
            # Restarting needs abandon + re-accept (no adapter yet): report
            # it typed, at a low priority, instead of holding a dead escort.
            return [Proposal.make(
                "WAIT", "Kísérés elbukott (quest failed): újrafelvétel kell, ezt még nem tudom, szólok",
                {"reason": "escort_quest_failed", "quest_ids": failed,
                 "needs": "ABANDON_AND_REACCEPT", "waiting_for": ["USER_OR_QUEST_STATE_CHANGE"]},
                confidence=.9, priority=30, evidence=("quest_log_failed", "objective_escort"))]
        return []

    @staticmethod
    def _move(state: dict, quest_id: str, row: dict, point: dict, guid: str, purpose: str,
              reason: str) -> Proposal:
        return Proposal.make(
            "MOVE", reason,
            {"x": point["x"], "y": point["y"], "z": point["z"], "z_known": True,
             "z_source": "PACKET_ENTITY", "coordinate_space": "WORLD_YARDS",
             "instance_id": point["instance_id"], "map_id": state.get("map_id"),
             "purpose": purpose, "require_navmesh": True, "stop_distance": STOP_YARDS,
             "server_entity_guid": guid, "quest_id": quest_id,
             "objective_id": f"{quest_id}:{row.get('order')}"},
            confidence=.85, priority=PRIORITY, evidence=("server_escort_subject", "objective_escort"))


def escort_subject_left(state: dict, guid: str, follow_yards: float) -> bool:
    """The held escort subject moved beyond ``follow_yards`` or left our view."""
    value = (state.get("packet_entities") or {}).get(str(guid))
    player = state.get("player_world_position") or {}
    px, py = number(player.get("x")), number(player.get("y"))
    point = best_position(value) if isinstance(value, dict) and not value.get("removed") else None
    if point is None or px is None or py is None:
        return True
    return math.hypot(point["x"]-px, point["y"]-py) > follow_yards
