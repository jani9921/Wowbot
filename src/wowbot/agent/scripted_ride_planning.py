"""Hold still while a client scene carries the player (no vehicle UI).

Live 2026-10-20 09:58:38-09:59:30 (Who Lurks in the Pit, "Ride Ralia
Dreamchaser to escape"): Interact on the creature Ralia started a client
scene.  A second later the cursor named a ``ClientActor`` "Ralia
Dreamchaser"; the server creature stayed where it stood, the exported player
position froze for 52 s and ``in_vehicle``/``on_taxi`` stayed false.  The
planner kept proposing searches, hovers, turns and three floor-cue MOVEs the
character could not perform (``no_layer_matching_floor_cue`` x3 in 0.34 s);
the user: the ride is scripted, one cannot get off before the top.

A ride is recognised only when an objective NPC that was just a creature
under the cursor/target comes back as a ClientActor of the same name: the
scene took the NPC over.  Bare ClientActors (e.g. the Monstrous Cadavers of a
vehicle quest) start nothing.  The hold proposes no input and ends with the
objective's credit, a landing (position jump), combat or a time limit.
"""
from __future__ import annotations

import math

from .models import Proposal, number

TAKEOVER_SECONDS = 6.          # creature -> ClientActor of the same name
HOLD_SECONDS = 120.            # since the scene actor was last seen
LANDED_YARDS = 10.


def _units(state: dict) -> list[dict]:
    units = [state.get("target"), state.get("mouseover"), *(state.get("soft_targets") or ())]
    return [unit for unit in units if isinstance(unit, dict) and unit.get("guid") and unit.get("name")]


def _ride_objective(state: dict, name: str) -> tuple[str, str] | None:
    """(quest id, objective id) of an open objective whose text names this NPC."""
    folded = name.casefold()
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        for index, objective in enumerate(quest.get("objectives") or ()):
            if (isinstance(objective, dict) and objective.get("is_complete") is not True
                    and folded in str(objective.get("description") or objective.get("text") or "").casefold()):
                return (str(quest.get("quest_id")),
                        str(objective.get("objective_id") or f"{quest.get('quest_id')}:{index}"))
    return None


class ScriptedRideHold:
    def __init__(self) -> None:
        self.creatures: dict[str, float] = {}
        self.ride: dict | None = None

    def propose(self, state: dict) -> list[Proposal]:
        now = number(state.get("monotonic_time"))
        if now is None:
            return []
        units = _units(state)
        for unit in units:
            if str(unit["guid"]).startswith("Creature-"):
                self.creatures[str(unit["name"]).casefold()] = now
        if state.get("in_vehicle") or state.get("has_vehicle_ui") or state.get("on_taxi"):
            self.ride = None                   # vehicle/taxi logic owns these
            return []
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        for unit in units:
            if not str(unit["guid"]).startswith("ClientActor-"):
                continue
            name = str(unit["name"]).casefold()
            if self.ride is not None and self.ride["name"] == name:
                self.ride["seen_at"] = now
                continue
            seen = self.creatures.get(name)
            objective = _ride_objective(state, str(unit["name"]))
            if seen is not None and 0 <= now-seen <= TAKEOVER_SECONDS and objective is not None:
                self.ride = {"name": name, "quest_id": objective[0], "objective_id": objective[1],
                             "at": now, "seen_at": now, "x": px, "y": py}
        ride = self.ride
        if ride is None:
            return []
        objective = _ride_objective(state, ride["name"])
        if objective is None or objective[1] != ride["objective_id"] or now-ride["seen_at"] > HOLD_SECONDS:
            self.ride = None                   # credited (landed), abandoned or too long
            return []
        if (None not in (px, py, ride["x"], ride["y"])
                and math.hypot(px-ride["x"], py-ride["y"]) > LANDED_YARDS):
            self.ride = None                   # set down somewhere: free again
            return []
        if state.get("is_in_combat"):
            return []                          # combat/defend own a fight
        return [Proposal.make(
            "WAIT_EVENT", "Szkriptelt utazás (kliens-scene) folyamatban: nem mozdulok, amíg letesz",
            {"quest_ids": [ride["quest_id"]], "objective_ids": [ride["objective_id"]],
             "objective_kind": "SCRIPTED_RIDE", "scene_actor_name": ride["name"],
             # One attempt spans the ride (live 52 s): the 15 s WAIT_EVENT
             # timeout failed it and searches/turns ran mid-ride.
             "wait_seconds": HOLD_SECONDS},
            confidence=.9, priority=121, evidence=("objective_npc_became_client_actor",))]
