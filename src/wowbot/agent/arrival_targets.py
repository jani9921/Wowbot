"""Explicit arrival targets for ARRIVE / AREA_TRIGGER objectives (REV4 P8.4).

The census: ~940 objectives "go / reach / explore / locate", handled only by a
walk to the quest POI and a zone sweep.  Many name a client AreaTrigger:

* a quest objective of type 10 (AREATRIGGER) carries the trigger ID;
* TDB ``areatrigger_involvedrelation`` lists the exploration triggers of
  older quests (63 rows, e.g. 62 "The Fargodeep Mine" -> trigger 88).

The client DB2 AreaTrigger row gives the exact centre (x, y, z, with height),
the continent and the radius / box.  That is an arrival target, not a guessed
area: the server grants the credit when the player enters it.  Unknown shapes
fall back to the radius only when it is positive; no shape is invented.
"""
from __future__ import annotations

import math

from .models import Proposal, number

ARRIVE_MECHANISMS = frozenset({"ARRIVE", "AREA_TRIGGER"})
AREATRIGGER_OBJECTIVE = 10
PRIORITY = 58.                 # above the POI region walk (56), below known handlers
MAX_STOP_YARDS = 6.


def _trigger(supplement, trigger_id) -> dict | None:
    try:
        value = supplement.area_trigger(int(trigger_id)) or {}
    except Exception:
        return None
    row = value.get("trigger") or {}
    pos = row.get("Pos")
    if not (isinstance(pos, (list, tuple)) and len(pos) == 3 and all(number(v) is not None for v in pos)):
        return None
    radius = number(row.get("Radius")) or 0.
    box = [number(row.get(k)) or 0. for k in ("Box_length", "Box_width", "Box_height")]
    if radius <= 0 and not all(v > 0 for v in box[:2]):
        return None
    return {"id": int(trigger_id), "x": float(pos[0]), "y": float(pos[1]), "z": float(pos[2]),
            "continent": row.get("ContinentID"), "radius": radius if radius > 0 else min(box[:2]) / 2.,
            "shape": "SPHERE" if radius > 0 else "BOX"}


def inside(player: dict, trigger: dict) -> bool:
    px, py, pz = (number(player.get(k)) for k in ("x", "y", "z"))
    if px is None or py is None:
        return False
    flat = math.hypot(trigger["x"]-px, trigger["y"]-py)
    if pz is None or player.get("z_observed") is not True:
        return flat <= trigger["radius"]
    return math.dist((px, py, pz), (trigger["x"], trigger["y"], trigger["z"])) <= trigger["radius"]


class ArrivalTargetPolicy:
    def __init__(self, supplement=None) -> None:
        self._supplement = supplement
        self.diagnostic: dict[str, str] = {}

    def _client(self):
        if self._supplement is None:
            from wowbot.quests.client_supplement import ClientSupplement
            self._supplement = ClientSupplement()
        return self._supplement

    @staticmethod
    def trigger_ids(state: dict, quest_id: str, objective, open_count: int) -> list[int]:
        from .quest_reference_matching import reference_objectives
        quest = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(quest_id)) or {}
        rows = reference_objectives(str(quest_id), objective.objective_id, objective.description,
                                    quest.get("objectives"))
        row = rows[0] if len(rows) == 1 else {}
        identifier = number(row.get("credit_object_id"))
        if row.get("raw_type") == AREATRIGGER_OBJECTIVE and identifier is not None and identifier > 0:
            return [int(identifier)]
        # An exploration quest's trigger belongs to its one open objective.
        if open_count == 1:
            return [int(v) for v in quest.get("area_triggers") or () if number(v) is not None]
        return []

    def propose(self, world, state: dict) -> list[Proposal]:
        if state.get("is_in_combat") or state.get("is_dead") or state.get("is_ghost"):
            return []
        from .objective_probes import objective_mechanism
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        if px is None or py is None:
            return []
        best = None
        for record in getattr(world.quest_model, "records", {}).values():
            if record.current_state != "ACTIVE":
                continue
            open_objectives = [o for o in record.objectives if o.completion_state != "COMPLETE"]
            for objective in open_objectives:
                if objective_mechanism(state, record.quest_id, objective) not in ARRIVE_MECHANISMS:
                    continue
                key = f"{record.quest_id}:{objective.objective_id}"
                ids = self.trigger_ids(state, record.quest_id, objective, len(open_objectives))
                triggers = [t for t in (_trigger(self._client(), i) for i in ids) if t is not None
                            and str(t["continent"]) == str(player.get("instance_id"))]
                if not triggers:
                    self.diagnostic[key] = "no_area_trigger" if not ids else "trigger_not_on_this_continent"
                    continue
                if any(inside(player, t) for t in triggers):
                    self.diagnostic[key] = "inside_trigger_awaiting_credit"
                    continue
                trigger = min(triggers, key=lambda t: math.hypot(t["x"]-px, t["y"]-py))
                self.diagnostic[key] = f"trigger:{trigger['id']}"
                flat = math.hypot(trigger["x"]-px, trigger["y"]-py)
                if best is None or flat < best[0]:
                    best = (flat, str(record.quest_id), objective, trigger)
        if best is None:
            return []
        _flat, quest_id, objective, trigger = best
        return [Proposal.make(
            "MOVE", "Felfedező objective: a kliens AreaTrigger pontos helyére megyek (XYZ, sugár)",
            {"x": trigger["x"], "y": trigger["y"], "z": trigger["z"], "z_known": True,
             "z_source": "CLIENT_DB2_AREATRIGGER", "coordinate_space": "WORLD_YARDS",
             "instance_id": player.get("instance_id"), "map_id": state.get("map_id"),
             "purpose": "ARRIVE_AREA_TRIGGER", "require_navmesh": True,
             "stop_distance": max(1.5, min(MAX_STOP_YARDS, trigger["radius"]*.5)),
             "area_trigger_id": trigger["id"], "area_trigger_radius": trigger["radius"],
             "quest_id": quest_id, "objective_id": str(objective.objective_id)},
            confidence=.8, priority=PRIORITY, evidence=("client_db2_areatrigger", "objective_arrive"))]
