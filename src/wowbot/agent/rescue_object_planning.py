"""Rescue an objective NPC by using the object that holds it (server data).

Live 2026-10-20 12:57-12:59 (Explorers in Peril, The Waking Shores): the
objective "Professor Cogcatcher rescued" came normalized as KILL, so the agent
searched for hostiles around him.  The server showed him 0.76 yd inside a
"Protodragon Rib Cage" (GOOBER 379137); the cursor passed over the cage at
12:58:38-12:59:03 from 3.2 yd and Interact was never pressed.

The objective names the NPC (TDB named creature); the server gives the exact
position of the NPC and of the door/button/chest/goober holding it.  The agent
walks to that object, faces it and presses Interact once per attempt -- the
same INTERACT_KEY_PACKET use as the totems and cocoons, out of combat and only
while no unit is the soft-interact recipient.  Without Ymir it proposes
nothing and the existing flow applies.
"""
from __future__ import annotations

import math

from .models import Proposal, number
from .object_interaction_flow import ObjectInteractionFlow
from .packet_entity_facts import (INTERACTIVE_GO_TYPES, RESCUE_BASIS, UNIT_LOOTABLE,
                                  _unit_flags, best_position, interaction_position, rescue_objects)

PRESS_SECONDS = 4.             # one press per attempt
MAX_PRESSES = 2                # per object before giving it a rest
REST_SECONDS = 60.


class RescueObjectPolicy:
    def __init__(self) -> None:
        self.presses: dict[str, list[float]] = {}

    def propose(self, state: dict, player_z: float | None = None) -> list[Proposal]:
        now = number(state.get("monotonic_time"))
        ui_open = ((state.get("quest_ui") or {}).get("open") is True or state.get("quest_ui_open") is True
                   or (state.get("gossip_ui") or {}).get("open") is True)
        if now is None or ui_open or state.get("is_in_combat") or state.get("in_vehicle") is True:
            return []
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if px is None or py is None:
            return []
        if player_z is None and position.get("z_observed") is True:
            player_z = number(position.get("z"))
        flow = ObjectInteractionFlow
        ranked = []
        for item in rescue_objects(state):
            if str(item.get("instance_id")) != str(position.get("instance_id")):
                continue
            recent = [at for at in self.presses.get(item["guid"], ()) if 0 <= now-at <= REST_SECONDS]
            self.presses[item["guid"]] = recent
            if len(recent) >= MAX_PRESSES:
                continue                       # pressed without credit: something else frees it
            flat = math.hypot(item["x"]-px, item["y"]-py)
            dz = abs(item["z"]-player_z) if player_z is not None else 0.
            ranked.append((flat + flow.PACKET_VERTICAL_WALK_FACTOR*dz, flat, dz, item))
        if not ranked:
            return []
        _, flat, dz, item = min(ranked, key=lambda row: row[0])
        guid = item["guid"]
        facing = number(state.get("orientation"))
        bearing = math.atan2(item["y"]-py, item["x"]-px)
        facing_ok = (flat < 1. or (facing is not None and abs((bearing-facing+math.pi) % math.tau - math.pi)
                                   <= flow.INTERACT_KEY_FACING_RADIANS))
        if flat > flow.PACKET_USE_RANGE_YARDS or dz > flow.PACKET_FLOOR_YARDS or not facing_ok:
            return [Proposal.make(
                "MOVE", "Megmentendő NPC-t tartó tárgy (szerver): odalépek és felé fordulok",
                {"x": item["x"], "y": item["y"], "z": item["z"], "z_known": True,
                 "z_source": "PACKET_GAMEOBJECT", "coordinate_space": "WORLD_YARDS",
                 "instance_id": position.get("instance_id"), "map_id": state.get("map_id"),
                 "purpose": "APPROACH_RESCUE_OBJECT", "require_navmesh": True,
                 "stop_distance": 2.0, "face_on_arrival": True, "server_entity_guid": guid,
                 "quest_id": item["quest_id"], "objective_id": item["objective_id"]},
                confidence=.85, priority=98, evidence=("server_rescue_npc_held_by_object",))]
        if any(isinstance(target, dict) and str(target.get("source_unit") or "").casefold() == "softinteract"
               and target.get("unit_type") not in (None, "GAMEOBJECT")
               for target in state.get("soft_targets") or ()):
            return []                          # F7 would talk to that unit instead
        for value in (state.get("packet_entities") or {}).values():
            if (not isinstance(value, dict) or value.get("kind") != "GAMEOBJECT" or value.get("removed")
                    or value.get("guid") == guid
                    or (value.get("info") or {}).get("go_type") not in INTERACTIVE_GO_TYPES | {None}):
                continue
            point = best_position(value)
            if point is not None and math.hypot(point["x"]-px, point["y"]-py) <= flat+.5:
                return []                      # another usable object is as near: F7 is ambiguous
        recent = self.presses.setdefault(guid, [])
        if recent and now-recent[-1] < PRESS_SECONDS:
            return []
        recent.append(now)
        return [Proposal.make(
            "OBJECT_USE", "Megmentendő NPC-t tartó tárgy előttem (szerver): Interact (F7)",
            {"activation_source": "INTERACT_KEY_PACKET", "binding": "INTERACTTARGET",
             "server_use_basis": RESCUE_BASIS, "object_guid": guid, "object_id": item.get("entry_id"),
             "rescue_npc_guid": item["rescue_npc_guid"],
             "objective_id": item["objective_id"], "quest_ids": [item["quest_id"]]},
            confidence=.85, priority=99,
            evidence=("server_rescue_npc_held_by_object", "facing_in_range_no_unit_soft_target"))]


# Live 2026-10-21 10:34:42 (Explorers in Peril): Archivist Rellid (189055,
# npc flag SPELLCLICK) rides a circling Primal Proto-Drake; the server sent
# him once from 100 yd and removed him OUT_OF_RANGE 1.3 s later, so no
# server walk-up existed.  When the drake passed, the client's soft-interact
# unit WAS Rellid -- and the agent kept searching the screen.  User: "rá
# kell kattintani".  Whenever the soft-interact unit is the NPC an open
# rescue objective names, Interact is pressed at once.
SOFT_PRESS_SECONDS = 1.5


def rescue_interaction_in_range(state: dict, guid) -> bool | None:
    """Known horizontal distance, not the mere presence of a soft hint.

    Do not turn vertical separation into a failed range check: an airborne
    spellclick passenger may be usable from the ground. The client remains
    the final authority for actual range/LOS and the interaction result.
    """
    point = interaction_position(state, guid)
    player = state.get("player_world_position") or {}
    x, y = number(player.get("x")), number(player.get("y"))
    if point is None or x is None or y is None:
        return None
    return math.hypot(point["x"]-x, point["y"]-y) <= 4.


def rescue_soft_target(state: dict) -> dict | None:
    """The soft-interact unit, when an open rescue objective names it."""
    from .packet_entity_facts import _RESCUE_TEXT
    from .quest_creature_memory import npc_id_from_guid
    soft = next((row for row in state.get("soft_targets") or ()
                 if isinstance(row, dict) and str(row.get("source_unit") or "").casefold() == "softinteract"),
                None)
    if (soft is None or not soft.get("guid") or soft.get("unit_type") == "GAMEOBJECT"
            or soft.get("is_attackable", soft.get("attackable")) is True
            or soft.get("is_dead", soft.get("dead")) is True):
        return None
    npc = soft.get("npc_id") if soft.get("npc_id") is not None else npc_id_from_guid(soft["guid"])
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        open_texts = [str(objective.get("description") or "").casefold()
                      for objective in quest.get("objectives") or ()
                      if isinstance(objective, dict) and objective.get("is_complete") is not True]
        for row in (reference.get(str(quest.get("quest_id"))) or {}).get("objectives") or ():
            text = str((row or {}).get("description") or "") if isinstance(row, dict) else ""
            if (not text or not _RESCUE_TEXT.search(text)
                    or not any(text.casefold() in live for live in open_texts)):
                continue
            from .packet_entity_facts import rescue_actor_entries
            entries = rescue_actor_entries(row)
            if str(npc) in entries and rescue_interaction_in_range(state, soft["guid"]) is not False:
                return {**soft, "npc_id": npc, "quest_id": str(quest.get("quest_id")), "objective": text}
    return None


class SoftInteractRescuePolicy:
    def __init__(self) -> None:
        self.pressed_at: dict[str, float] = {}

    def propose(self, state: dict) -> list[Proposal]:
        from wowbot.runtime.skill_identity import check_interaction_recipient
        now = number(state.get("monotonic_time"))
        ui_open = ((state.get("quest_ui") or {}).get("open") is True or state.get("quest_ui_open") is True
                   or (state.get("gossip_ui") or {}).get("open") is True)
        if now is None or ui_open or state.get("is_in_combat") or state.get("in_vehicle") is True:
            return []
        target = rescue_soft_target(state)
        if target is None:
            return []
        guid = str(target["guid"])
        last = self.pressed_at.get(guid)
        if (last is not None and 0 <= now-last < SOFT_PRESS_SECONDS
                or not check_interaction_recipient({"guid": guid}, state, now)):
            return []
        self.pressed_at[guid] = now
        return [Proposal.make(
            "INTERACT", f"Megmentendő quest-NPC a soft-interact célpont ({target.get('name')}): F7",
            {"activation_source": "SOFT_INTERACT", "soft_guid": guid, "npc_id": target["npc_id"],
             "purpose": "RESCUE_SOFT_INTERACT_NPC", "quest_id": target["quest_id"]},
            confidence=.9, priority=126,
            evidence=("rescue_objective_names_npc", "soft_interact_guid_match"))]


# User 2026-10-21 10:47-10:52 (same quest): "van olyan bind, hogy
# TARGETNEARESTFRIEND, Ctrl+Tab, azzal kijelöli Rellidet".  Live, Rellid
# stayed the selected target for minutes while his drake circled; the soft
# interact unit was him only in four ~1 s windows.  Around a rescue NPC seen
# lately, Ctrl+Tab selects him (TARGET.verify wants his GUID); while he is
# the selected unit, Interact is pressed when the addon (0.9.71,
# CheckInteractDistance) says he is near, or every UNKNOWN_PRESS_SECONDS on
# an older addon.  Never while another unit is the soft-interact recipient.
SEEN_FOR_SECONDS = 180.
AROUND_YARDS = 70.
FRIEND_TAB_SECONDS = 4.
NEAR_PRESS_SECONDS = 1.5
UNKNOWN_PRESS_SECONDS = 3.


def open_rescue_entries(state: dict) -> dict[str, str]:
    """{creature entry: quest id} named by open rescue objectives."""
    from .packet_entity_facts import _RESCUE_TEXT
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    result: dict[str, str] = {}
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        open_texts = [str(objective.get("description") or "").casefold()
                      for objective in quest.get("objectives") or ()
                      if isinstance(objective, dict) and objective.get("is_complete") is not True]
        for row in (reference.get(str(quest.get("quest_id"))) or {}).get("objectives") or ():
            text = str((row or {}).get("description") or "") if isinstance(row, dict) else ""
            if text and _RESCUE_TEXT.search(text) and any(text.casefold() in live for live in open_texts):
                from .packet_entity_facts import rescue_actor_entries
                for entry in rescue_actor_entries(row):
                    result.setdefault(entry, str(quest.get("quest_id")))
    return result


def rescue_search_proposal(state: dict, entries: dict[str, str]) -> Proposal | None:
    """Bounded search hints, never NPC locations/identity or a rescued count.

    Mixed-height POI vertices may be searched individually through MMAP;
    they are not claimed to be spawns, a safe polygon or one common floor.
    The existing NavigationService coverage owns visited cells.
    """
    from .packet_entity_facts import rescue_credit_entry, _RESCUE_TEXT
    from .quest_search_hints import objective_poi_points, subject_search_proposal
    player = state.get("player_world_position") or {}
    px, py = number(player.get("x")), number(player.get("y"))
    if (None in (px, py) or not all(math.isfinite(v) for v in (px, py))
            or player.get("instance_id") is None):
        return None
    references = (state.get("reference_knowledge") or {}).get("quests") or {}
    for qid in dict.fromkeys(entries.values()):
        reference = references.get(qid) or {}
        for row in reference.get("objectives") or ():
            if (not isinstance(row, dict) or entries.get(rescue_credit_entry(row)) != qid
                    or not _RESCUE_TEXT.search(str(row.get("description") or ""))
                    or not any(str(row.get("description") or "").casefold()
                               in str(obj.get("description") or "").casefold()
                               for quest in state.get("active_quests") or ()
                               if str(quest.get("quest_id")) == qid and quest.get("is_complete") is not True
                               for obj in quest.get("objectives") or ()
                               if obj.get("is_complete") is not True)):
                continue
            oid = row.get("objective_id")
            points, hints = objective_poi_points(state, qid, oid, row.get("order"))
            if not points:
                continue
            return subject_search_proposal(state, qid, oid,
                [entry for entry, quest in entries.items() if quest == qid], points, hints,
                purpose="SEARCH_RESCUE_OBJECTIVE",
                reason="Mentési quest: következő még nem vizsgált TDB keresési pont")
    return None


class RescueTargetPolicy:
    def __init__(self) -> None:
        self.sightings: dict[str, tuple[float, str, tuple[float, float] | None]] = {}
        self.tabbed_at: float | None = None
        self.pressed_at: float | None = None

    def _note_sightings(self, state: dict, entries: dict[str, str], now: float) -> None:
        from .quest_creature_memory import npc_id_from_guid
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        here = (px, py) if px is not None and py is not None else None
        units = [state.get("target") or {}, state.get("mouseover") or {},
                 *(row for row in state.get("soft_targets") or () if isinstance(row, dict))]
        units += [value for value in (state.get("packet_entities") or {}).values() if isinstance(value, dict)]
        for unit in units:
            guid = str(unit.get("guid") or "")
            npc = unit.get("npc_id", unit.get("entry_id"))
            if npc is None and guid:
                npc = npc_id_from_guid(guid)
            if unit.get("kind") in {"CREATURE", "VEHICLE"}:
                point = best_position(unit)
                flags = (unit.get("info") or {}).get("npc_flags")
                if (unit.get("removed") or point is None
                        or str(point.get("instance_id")) != str(player.get("instance_id"))
                        or _unit_flags(unit) & UNIT_LOOTABLE
                        or type(flags) is not int or not flags & (0x1000000 | 0x1 | 0x2)
                        or (here is not None and math.hypot(point["x"]-px, point["y"]-py) > 20.)
                        or (player.get("z_observed") is True and number(player.get("z")) is not None
                            and abs(point["z"]-player["z"]) > 5.)):
                    continue                  # a distant/other-floor packet is not a near friend-tab sighting
            if guid and str(npc) in entries and unit.get("is_dead", unit.get("dead")) is not True:
                self.sightings[str(npc)] = (now, guid, here)

    @staticmethod
    def _direct_credit_approach(state: dict, entries: dict[str, str]) -> Proposal | None:
        """A live spellclick actor may be its own concrete rescue credit.

        Whimpering Whelpling is such a case: the separate named list is
        empty, but exact TDB entry + server spellclick/XYZ are available.
        Route to its real floor before any near-unit Ctrl+Tab/Interact.
        Named passengers retain their existing passing-soft-target flow.
        """
        from .packet_entity_facts import rescue_credit_entry
        direct = set()
        reference = (state.get("reference_knowledge") or {}).get("quests") or {}
        for quest in reference.values():
            for row in (quest or {}).get("objectives") or ():
                if isinstance(row, dict) and not row.get("named_creatures"):
                    entry = rescue_credit_entry(row)
                    if entry in entries:
                        direct.add(entry)
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        if None in (px, py):
            return None
        choices = []
        for unit in (state.get("packet_entities") or {}).values():
            if not isinstance(unit, dict) or str(unit.get("entry_id")) not in direct:
                continue
            flags = (unit.get("info") or {}).get("npc_flags")
            point = interaction_position(state, unit.get("guid"))
            if (unit.get("kind") not in {"CREATURE", "VEHICLE"} or not unit.get("guid")
                    or unit.get("removed") or unit.get("dead", unit.get("is_dead")) is True
                    or type(flags) is not int or not flags & 0x1000000 or point is None
                    or str(point["instance_id"]) != str(player.get("instance_id"))
                    or _unit_flags(unit) & UNIT_LOOTABLE):
                continue
            distance = math.hypot(point["x"]-px, point["y"]-py)
            dz = (abs(point["z"]-player["z"])
                  if player.get("z_observed") is True and number(player.get("z")) is not None else 0.)
            target = state.get("target") or {}
            selected_ready = (str(target.get("guid")) == str(unit["guid"])
                              and target.get("interact_near") is True and distance <= 4.)
            if math.isfinite(distance) and not selected_ready and (distance > 3. or dz > 5.):
                choices.append((distance, unit, point))
        if not choices:
            return None
        _, unit, point = min(choices, key=lambda choice: choice[0])
        return Proposal.make("MOVE", "Megmentendő NPC pontos szerverhelye: odamegyek a megfelelő szintre",
            {**{key: point[key] for key in ("x", "y", "z", "instance_id", "coordinate_space")},
             "z_known":True, "z_source":"PACKET_ENTITY",
             "map_id":state.get("map_id"), "server_entity_guid":unit["guid"],
             "quest_id":entries[str(unit["entry_id"])], "purpose":"APPROACH_RESCUE_NPC",
             "require_navmesh":True, "face_on_arrival":True, "stop_distance":2.5,
             "knowledge_priority":"SERVER_LIVE"},
            confidence=.85, priority=123,
            evidence=("concrete_rescue_credit_entry", "server_spellclick_identity_and_position"))

    def propose(self, state: dict) -> list[Proposal]:
        now = number(state.get("monotonic_time"))
        ui_open = ((state.get("quest_ui") or {}).get("open") is True or state.get("quest_ui_open") is True
                   or (state.get("gossip_ui") or {}).get("open") is True)
        if now is None or ui_open or state.get("is_in_combat") or state.get("in_vehicle") is True:
            return []
        entries = open_rescue_entries(state)
        if not entries:
            return []
        self._note_sightings(state, entries, now)
        if rescue_soft_target(state) is not None:
            return []                          # SoftInteractRescuePolicy presses
        approach = self._direct_credit_approach(state, entries)
        if approach is not None:
            return [approach]
        soft = next((row for row in state.get("soft_targets") or ()
                     if isinstance(row, dict) and str(row.get("source_unit") or "").casefold() == "softinteract"),
                    None)
        target = state.get("target") or {}
        npc = target.get("npc_id")
        if (target.get("guid") and str(npc) in entries
                and target.get("dead", target.get("is_dead")) is not True
                and target.get("attackable", target.get("is_attackable")) is not True):
            if soft is not None:
                return []                      # F7 would go to that unit instead
            near = target.get("interact_near")
            wait = NEAR_PRESS_SECONDS if near is True else UNKNOWN_PRESS_SECONDS
            if near is False or (self.pressed_at is not None and 0 <= now-self.pressed_at < wait):
                return []
            self.pressed_at = now
            name = target.get("name")
            return [Proposal.make(
                "INTERACT", f"Megmentendő quest-NPC kijelölve ({name}): F7",
                {"guid": target["guid"], "npc_id": npc, "no_hover": True,
                 "purpose": "RESCUE_TARGET_INTERACT", "quest_id": entries[str(npc)],
                 "interact_near": near},
                confidence=.85, priority=125,
                evidence=("rescue_objective_names_npc", "selected_target_identity"))]
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        recent = [(entry, seen) for entry, seen in self.sightings.items()
                  if entry in entries and 0 <= now-seen[0] <= SEEN_FOR_SECONDS
                  and (seen[2] is None or px is None
                       or math.hypot(seen[2][0]-px, seen[2][1]-py) <= AROUND_YARDS)]
        if not recent or (self.tabbed_at is not None and 0 <= now-self.tabbed_at < FRIEND_TAB_SECONDS):
            # No arbitrary distance cap on already known server actors.
            # With no actor, bring new entities into range by bounded MMAP
            # coverage, not by waiting forever at the completed POI centre.
            if any(isinstance(unit, dict) and str(unit.get("entry_id")) in entries
                   and interaction_position(state, unit.get("guid")) is not None
                   for unit in (state.get("packet_entities") or {}).values()):
                return []
            search = rescue_search_proposal(state, entries)
            return [search] if search is not None else []
        entry, (_, guid, _) = max(recent, key=lambda item: item[1][0])
        self.tabbed_at = now
        return [Proposal.make(
            "TARGET", "Megmentendő quest-NPC a közelben: Ctrl+Tab (legközelebbi barátságos egység)",
            {"activation_source": "TAB_FRIEND_RESCUE", "guid": guid, "npc_id": int(entry),
             "acceptable_guids": [guid], "purpose": "RESCUE_FRIEND_TAB", "quest_id": entries[entry]},
            confidence=.8, priority=124, evidence=("rescue_objective_names_npc", "rescue_npc_seen_nearby"))]
