"""Find KILL-objective mobs by their server position and select them by GUID.

User 2026-10-20: "the server sends the positions of the nearby quest mobs
too" -- live 09:04-09:13 every harpy, worg and Bloodbeak came with exact
x,y,z and movement splines, while the agent searched for them on screen
(SEEK/INSPECT/hover) and often wandered.

Out of combat the agent walks toward the nearest live objective mob,
faces it and presses Tab (TARGETNEARESTENEMY) only when the server shows
that unit as the nearest one straight ahead.  The new target must carry
exactly the server GUID (TARGET.verify), so a wrong pick is never attacked:
combat planning attacks only quest-relevant targets out of combat.  Once the
mob is selected, the agent closes in until a harmful action is in range and
the existing COMBAT step takes over.  Without Ymir it proposes nothing.
"""
from __future__ import annotations

import math

from .models import Proposal, number
from .object_interaction_flow import ObjectInteractionFlow
from .packet_entity_facts import (TAB_FACING_RADIANS, TAB_SERVER_GUID, TAB_TARGET_YARDS,
                                  kill_objective_units, tab_target_check)

PRESS_SECONDS = 2.             # one Tab per attempt
MAX_PRESSES = 2                # per unit before giving it a rest
REST_SECONDS = 45.
APPROACH_STOP_YARDS = 12.      # well inside Tab range
# Live 2026-10-20 17:03:10 (Murloc Mania): Tab straight at a murloc 9.4 yd
# ahead selected nothing -- it lay dead (screenshot; tooltip "Corpse"), killed
# by someone else, so the server never set our lootable flag.  A unit the
# addon reports dead, or that an ideally placed Tab did not select, is
# skipped; the latter for a while (it may have been a corpse).
TAB_CONFIRM_SECONDS = 1.5
UNTARGETABLE_SECONDS = 120.
DEAD_SECONDS = 600.
CLOSE_IN_YARDS = 4.            # selected, nothing in range yet: melee distance
# Live 2026-10-26 14:11-14:24: the nearest mob flipped between plans (spline
# estimates move) and the agent walked to and fro between two or three of
# them.  The chosen one stays chosen unless another is clearly nearer.
AIRBORNE_ABOVE_YARDS = 8.      # live 16:53: drakes ~20 yd up still failed the walk
AIRBORNE_STOP_YARDS = 10.
AIRBORNE_TAB_YARDS = 35.
SWITCH_FACTOR = .7
ATTACKER_COST_FACTOR = .5
SWITCH_YARDS = 5.


class ServerKillTargetPolicy:
    def __init__(self) -> None:
        self.presses: dict[str, list[float]] = {}
        self.skip_until: dict[str, float] = {}
        self.pending_tab: tuple[str, float] | None = None
        self.chosen: str | None = None

    def _note_evidence(self, state: dict, now: float) -> None:
        units = [state.get("target"), state.get("mouseover"), *(state.get("soft_targets") or ())]
        for unit in units:
            if not isinstance(unit, dict) or not unit.get("guid"):
                continue
            tooltip = str(unit.get("tooltip") or "").casefold()
            if (unit.get("dead") is True or unit.get("is_dead") is True
                    or tooltip.startswith("corpse") or " corpse" in tooltip):
                self.skip_until[str(unit["guid"])] = now + DEAD_SECONDS
        if self.pending_tab is not None:
            guid, at = self.pending_tab
            selected_guid = str((state.get("target") or {}).get("guid") or "")
            if selected_guid == guid or (selected_guid and selected_guid in {
                    str(item["guid"]) for item in kill_objective_units(state)}):
                self.pending_tab = None             # selected it (or another objective mob)
            elif now-at >= TAB_CONFIRM_SECONDS:
                self.skip_until[guid] = max(self.skip_until.get(guid, 0.), now + UNTARGETABLE_SECONDS)
                self.pending_tab = None

    def _move(self, item: dict, state: dict, stop: float, reason: str, priority: float) -> Proposal:
        position = state.get("player_world_position") or {}
        player_z = number(position.get("z")) if position.get("z_observed") is True else None
        if player_z is not None and item["z"] - player_z > AIRBORNE_ABOVE_YARDS:
            # Live 2026-10-26 14:28-14:39 (Proto-Fight): proto-dragons at
            # z 217-241 over ground at 96-130; a walk to their point in the
            # air had no navmesh route, again and again.  Walk to the ground
            # below and let it come within reach (Tab / F7 there).
            return Proposal.make(
                "MOVE", "Repülő quest-mob: alá megyek a földre (navmesh), onnan Tab/F7",
                {"x": item["x"], "y": item["y"], "z_known": False, "coordinate_space": "WORLD_YARDS",
                 "instance_id": position.get("instance_id"), "map_id": state.get("map_id"),
                 "purpose": "APPROACH_SERVER_KILL_TARGET", "require_navmesh": True,
                 "stop_distance": max(stop, AIRBORNE_STOP_YARDS), "face_on_arrival": True,
                 "server_entity_guid": item["guid"], "quest_id": item["quest_id"],
                 "objective_id": item["objective_id"], "airborne_target": True},
                confidence=.75, priority=priority, evidence=("server_unit_position", "kill_objective_entry"))
        return Proposal.make(
            "MOVE", reason,
            {"x": item["x"], "y": item["y"], "z": item["z"], "z_known": True,
             "z_source": "PACKET_ENTITY", "coordinate_space": "WORLD_YARDS",
             "instance_id": position.get("instance_id"), "map_id": state.get("map_id"),
             "purpose": "APPROACH_SERVER_KILL_TARGET", "require_navmesh": True,
             "stop_distance": stop, "face_on_arrival": True, "server_entity_guid": item["guid"],
             "quest_id": item["quest_id"], "objective_id": item["objective_id"]},
            confidence=.85, priority=priority, evidence=("server_unit_position", "kill_objective_entry"))

    def propose(self, state: dict, player_z: float | None = None) -> list[Proposal]:
        now = number(state.get("monotonic_time"))
        ui_open = ((state.get("quest_ui") or {}).get("open") is True or state.get("quest_ui_open") is True
                   or (state.get("gossip_ui") or {}).get("open") is True
                   or (state.get("vendor_ui") or {}).get("open") is True)
        if (now is None or ui_open or state.get("is_in_combat") or state.get("in_vehicle") is True
                or state.get("is_dead") or state.get("is_ghost")):
            return []
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if px is None or py is None:
            return []
        if position.get("z_observed") is True and number(position.get("z")) is not None:
            # The server's own height beats the resolved layer (live
            # 2026-10-27 16:10: the resolver kept the courtyard, 44 yd below
            # the wall top Wrathion left us on; a courtyard Qalashi won).
            player_z = number(position.get("z"))
        self._note_evidence(state, now)
        from .escort_planning import escort_attackers
        listed = kill_objective_units(state)
        known = {str(item["guid"]) for item in listed}
        # P8.4 (E2): the attackers of our escort are kill targets too.
        listed.extend(item for item in escort_attackers(state) if str(item["guid"]) not in known)
        units = [item for item in listed
                 if str(item.get("instance_id")) == str(position.get("instance_id"))
                 and self.skip_until.get(str(item["guid"]), 0.) <= now]
        if not units:
            return []
        target = state.get("target") or {}
        selected = next((item for item in units if str(item["guid"]) == str(target.get("guid") or "")), None)
        if selected is not None:
            harmful_in_range = any(action.get("is_harmful") is True and action.get("in_range") is True
                                   for action in state.get("actionbar") or ())
            flying = player_z is not None and selected["z"] - player_z > AIRBORNE_ABOVE_YARDS
            if (harmful_in_range or flying
                    or math.hypot(selected["x"]-px, selected["y"]-py) <= CLOSE_IN_YARDS):
                # COMBAT owns it from here; a selected flyer is opened with
                # F7 there (use_on_target_opener), not walked up to in the air.
                return []
            return [self._move(selected, state, CLOSE_IN_YARDS,
                               "Kijelölt quest-mob (szerver-pozíció): odamegyek harctávolságra", 100)]
        flow = ObjectInteractionFlow
        ranked = []
        for item in units:
            recent = [at for at in self.presses.get(item["guid"], ()) if 0 <= now-at <= REST_SECONDS]
            self.presses[item["guid"]] = recent
            if len(recent) >= MAX_PRESSES:
                continue                       # Tab never selected it: leave it to the visual flow
            flat = math.hypot(item["x"]-px, item["y"]-py)
            dz = abs(item["z"]-player_z) if player_z is not None else 0.
            cost = flat + flow.PACKET_VERTICAL_WALK_FACTOR*dz
            if item.get("targets_me") or item.get("escort_attacker"):
                cost *= ATTACKER_COST_FACTOR      # it is coming for us (or our escort): fight it first
            ranked.append((cost, flat, item))
        if not ranked:
            return []
        best = min(ranked, key=lambda row: row[0])
        kept = next((row for row in ranked if str(row[2]["guid"]) == self.chosen), None)
        if kept is not None and not best[0] < min(kept[0]*SWITCH_FACTOR, kept[0]-SWITCH_YARDS):
            best = kept
        _, flat, item = best
        self.chosen = str(item["guid"])
        # A flying quest mob over us (Proto-Fight, live 17:04-17:06): the
        # floor rule said OTHER_FLOOR every time; measured in 3D, the WoW Tab
        # range (~40 yd) reaches it from the ground below.
        flying_target = player_z is not None and item["z"] - player_z > AIRBORNE_ABOVE_YARDS
        ready, reason = (tab_target_check(state, item["guid"], player_z, airborne=True,
                                          max_yards=AIRBORNE_TAB_YARDS) if flying_target
                         else tab_target_check(state, item["guid"], player_z))
        if ready:
            recent = self.presses.setdefault(item["guid"], [])
            if recent and now-recent[-1] < PRESS_SECONDS:
                return []
            recent.append(now)
            self.pending_tab = (str(item["guid"]), now)
            return [Proposal.make(
                "TARGET", "Quest-mob a szerver szerint előttem a legközelebbi: Tab, GUID-ellenőrzéssel",
                {"guid": item["guid"], "activation_source": TAB_SERVER_GUID, "npc_id": item.get("entry_id"),
                 "acceptable_guids": sorted(str(unit["guid"]) for unit in units)[:12],
                 "quest_ids": [item["quest_id"]], "objective_id": item["objective_id"]},
                confidence=.85, priority=96, evidence=("server_unit_position", "tab_nearest_ahead"))]
        if reason in {"SERVER_UNIT_GONE", "SERVER_UNIT_DEAD", "NO_POSE"}:
            return []
        if reason == "OTHER_UNIT_NEARER" and flat > CLOSE_IN_YARDS + 1.:
            # Something else is as near in front: get close enough that the
            # wanted mob is the nearest one.
            return [self._move(item, state, CLOSE_IN_YARDS,
                               "Quest-mob (szerver): közelebb lépek, hogy biztosan ő legyen a legközelebbi", 100)]
        stop = APPROACH_STOP_YARDS if flat > TAB_TARGET_YARDS else max(1., min(flat, APPROACH_STOP_YARDS))
        return [self._move(item, state, stop,
                           "Quest-mob pontos szerver-pozíciója: odamegyek és felé fordulok", 100)]
