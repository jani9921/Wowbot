"""Loot own kills found by their server position (user 2026-10-20).

The server sets a unit's lootable dynamic flag (0x4) per player: live
2026-10-20 09:08:06 a Harpy Snatcher the agent killed went 0 -> 0x4 and back
to 0 after its loot (09:08:09), and the corpse stayed until 09:08:40.  The
loot steps so far needed the corpse selected, hovered (tooltip anchor) or the
client's soft-interact unit -- otherwise LOOT failed ``corpse_not_found``
(live 10:16:30, 10:21:09, 10:24:55, 12:58:16).

Out of combat the agent walks to the nearest corpse the server marks
lootable for us, faces it, and presses Interact through the existing LOOT
skill only when the client's soft-interact unit is exactly that corpse.
"""
from __future__ import annotations

import math

from .models import Proposal, number
from .packet_entity_facts import UNIT_LOOTABLE, best_position

SEARCH_YARDS = 40.
# A corpse explicitly confirmed as ours may be behind the normal search
# circle after a combat knockback or a short quest MOVE. Never apply this
# extension to arbitrary nearby dead units.
CONFIRMED_CORPSE_YARDS = 100.
FLOOR_YARDS = 5.
LOOT_RANGE_YARDS = 3.
# Live 2026-10-21 10:57:49: three Primal Proto-Whelps died on one spot; the
# soft-interact unit was one of them, the nearest-first walk aimed at another,
# and nothing was pressed (the screen corpse search took over and failed
# corpse_not_found).  The Interact key loots whichever of our lootable
# corpses it acts on within this range.
RECIPIENT_YARDS = 5.
FACING_RADIANS = .6
MAX_PRESSES = 2
REST_SECONDS = 30.
# Live 2026-10-25 10:33-10:37 (Cooking Meat, "Raw Meat collected from
# wildlife"): five or six goats and porcupines died before one was looted.
# The next kill walk was 116 (100 + agenda 12 + campaign 4), the corpse walk
# 112 and the press 108, so every new mob won.  Our own lootable corpse
# within reach comes before the next quest step.
LOOT_PRIORITY = 122.
APPROACH_PRIORITY = 120.


class ServerLootPolicy:
    def __init__(self) -> None:
        self.presses: dict[str, list[float]] = {}

    @staticmethod
    def corpses(state: dict, player_z: float | None = None) -> list[tuple[float, dict, dict]]:
        """(distance, entity, point) of corpses the server marks lootable for us."""
        entities = state.get("packet_entities")
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if not isinstance(entities, dict) or px is None or py is None:
            return []
        result = []
        owned = {str(guid) for guid in state.get("owned_corpse_guids") or ()}
        owned.update(str(row["guid"]) for row in state.get("confirmed_corpse_anchors") or ()
                     if isinstance(row, dict) and row.get("guid") and row.get("ownership_confirmed") is True)
        for value in entities.values():
            flags = (value.get("dynamic_flags") or {}).get("value") if isinstance(value, dict) else None
            if (not isinstance(value, dict) or value.get("kind") not in {"CREATURE", "VEHICLE"}
                    or value.get("removed") or type(flags) is not int or not flags & UNIT_LOOTABLE):
                continue
            point = best_position(value)
            if point is None or str(point["instance_id"]) != str(position.get("instance_id")):
                continue
            if player_z is not None and abs(point["z"]-player_z) > FLOOR_YARDS:
                continue
            distance = math.hypot(point["x"]-px, point["y"]-py)
            radius = CONFIRMED_CORPSE_YARDS if str(value.get("guid")) in owned else SEARCH_YARDS
            if distance <= radius:
                result.append((distance, value, point))
        return sorted(result, key=lambda row: row[0])

    @staticmethod
    def key_recipient(state: dict) -> tuple[str | None, bool]:
        """(GUID, via soft-interact) of the unit the Interact key acts on:
        the selected unit, else the client's soft-interact unit."""
        target = str((state.get("target") or {}).get("guid") or "")
        if target:
            return target, False
        soft = next((str(row["guid"]) for row in state.get("soft_targets") or ()
                     if isinstance(row, dict) and row.get("guid")
                     and str(row.get("source_unit") or "").casefold() == "softinteract"), None)
        return soft, soft is not None

    def propose(self, state: dict, player_z: float | None = None) -> list[Proposal]:
        from wowbot.skills.loot import soft_interact_corpse
        now = number(state.get("monotonic_time"))
        ui_open = ((state.get("quest_ui") or {}).get("open") is True or state.get("quest_ui_open") is True
                   or (state.get("gossip_ui") or {}).get("open") is True
                   or (state.get("vendor_ui") or {}).get("open") is True
                   or state.get("loot_open") is True or (state.get("loot") or {}).get("open") is True)
        if (now is None or ui_open or state.get("is_in_combat") or state.get("in_vehicle") is True
                or state.get("is_dead") or state.get("is_ghost")):
            return []
        position = state.get("player_world_position") or {}
        if player_z is None and position.get("z_observed") is True:
            player_z = number(position.get("z"))
        px, py = number(position.get("x")), number(position.get("y"))
        facing = number(state.get("orientation"))
        quest_ids = [str(quest.get("quest_id")) for quest in state.get("active_quests") or ()
                     if isinstance(quest, dict) and quest.get("is_complete") is not True]
        rows = []
        for distance, value, point in self.corpses(state, player_z):
            guid = str(value["guid"])
            recent = [at for at in self.presses.get(guid, ()) if 0 <= now-at <= REST_SECONDS]
            self.presses[guid] = recent
            if len(recent) < MAX_PRESSES:      # pressed, still flagged: rest
                rows.append((distance, value, point))
        recipient, via_soft = self.key_recipient(state)
        for distance, value, point in rows:
            guid = str(value["guid"])
            if guid == recipient and distance <= RECIPIENT_YARDS:
                self.presses[guid].append(now)
                return [Proposal.make(
                    "LOOT", "Lootolható saját hulla az interact billentyű alatt (szerver): F7",
                    {"guid": guid, "soft_interact": via_soft, "server_lootable": True,
                     "quest_ids": quest_ids},
                    confidence=.95, priority=LOOT_PRIORITY,
                    evidence=("server_lootable_flag", "soft_interact_corpse" if via_soft
                              else "selected_corpse"))]
        for distance, value, point in rows:
            guid = str(value["guid"])
            recent = self.presses[guid]
            bearing = math.atan2(point["y"]-py, point["x"]-px)
            facing_ok = (distance < 1. or (facing is not None and abs((bearing-facing+math.pi) % math.tau - math.pi)
                                            <= FACING_RADIANS))
            if distance > LOOT_RANGE_YARDS or not facing_ok:
                return [Proposal.make(
                    "MOVE", "Lootolható saját hulla (szerver-pozíció): odamegyek és felé fordulok",
                    {"x": point["x"], "y": point["y"], "z": point["z"], "z_known": True,
                     "z_source": "PACKET_ENTITY", "coordinate_space": "WORLD_YARDS",
                     "instance_id": position.get("instance_id"), "map_id": state.get("map_id"),
                     "purpose": "APPROACH_SERVER_CORPSE", "require_navmesh": True,
                     "stop_distance": 2.0, "face_on_arrival": True, "server_entity_guid": guid},
                    confidence=.85, priority=APPROACH_PRIORITY, evidence=("server_lootable_flag", "server_unit_position"))]
            if not soft_interact_corpse(state, guid, server_lootable=True):
                return []                      # another unit would take the key; the other loot steps decide
            recent.append(now)
            return [Proposal.make(
                "LOOT", "Lootolható saját hulla előttem (szerver + soft-interact): interact billentyű",
                {"guid": guid, "soft_interact": True, "server_lootable": True, "quest_ids": quest_ids},
                confidence=.95, priority=LOOT_PRIORITY, evidence=("server_lootable_flag", "soft_interact_corpse"))]
        return []
