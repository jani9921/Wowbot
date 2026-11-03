"""One shared target cost for objective pursuit (user 2026-10-27).

Live 2026-10-27 16:10 (Obsidian Citadel): Wrathion carried the player onto
the wall where the usable South Siege Arbalest stood (same level, 60 yd).
The kill hunt went for a courtyard Qalashi 45 yd below by flat distance.
Each policy (kill hunt 116, linked object 119, NPC) ranks only its own
candidates, by flat distance, so the two kinds never met on one scale.

User, agreed: "valami elsőbbséget fel kéne vegyen, hogy ami közelebb van,
vagy értelemszerűen egy z-n van vele ... wrathion vitt fel a híd tetejére
ahol van az arbalest, tehát akkor azt a questet kellene preferálni".

The ranker adds this bounded adjustment to every objective-pursuit
proposal:
1. Route cost instead of flat distance: height difference costs walking.
2. Placed-here bonus: after a scripted ride, scene, vehicle/taxi exit or map
   transfer, targets near the landing point on its level.
3. One-shot objectives before counted kills: "0/12 slain" is background work
   unless its target is near.
4. A fresh quest (just accepted) wins ties.

``better_than_commitment`` lets a clearly better target release a committed
subgoal, so a long walk cannot hide a better choice that appeared later.
"""
from __future__ import annotations

import math
import re

from .models import number

OBJECTIVE_PURPOSES = frozenset({"APPROACH_SERVER_KILL_TARGET", "APPROACH_QUEST_OBJECT_SPAWN",
                                "APPROACH_SERVER_NPC", "LOCATE_QUEST_OBJECTIVE_REGION"})
OBJECTIVE_SKILLS = frozenset({"OBJECT_USE", "TARGET", "INTERACT", "USE_ON_TARGET", "ASSIST"})
KILL_PURPOSES = frozenset({"APPROACH_SERVER_KILL_TARGET"})

VERTICAL_FACTOR = 3.          # a yard of height costs ~3 yd of walking (ramps, stairs)
LEVEL_SLACK_YARDS = 4.
ROUTE_YARDS_PER_POINT = 15.
ROUTE_PENALTY_CAP = 8.
LANDING_BONUS = 6.
LANDING_RADIUS_YARDS = 80.
LANDING_LEVEL_YARDS = 10.
LANDING_SECONDS = 120.
COUNTED_REQUIRED = 3
COUNTED_PENALTY = 3.
NEARBY_YARDS = 25.
FRESH_BONUS = 1.5
FRESH_SECONDS = 120.
TELEPORT_YARDS = 40.
TELEPORT_SECONDS = 2.
PREEMPT_MARGIN = 6.
PREEMPT_MIN_SECONDS = 3.


def is_objective_pursuit(proposal) -> bool:
    params = proposal.parameters
    if proposal.skill == "MOVE":
        return params.get("purpose") in OBJECTIVE_PURPOSES
    return proposal.skill in OBJECTIVE_SKILLS and bool(params.get("quest_id") or params.get("quest_ids"))


def own_height(state: dict) -> float | None:
    position = state.get("player_world_position") or {}
    return number(position.get("z")) if position.get("z_observed") is True else None


def proposal_point(proposal, state: dict) -> dict | None:
    """World x,y(,z) the proposal works toward, if it names one."""
    params = proposal.parameters
    x, y = number(params.get("x")), number(params.get("y"))
    if params.get("coordinate_space") == "WORLD_YARDS" and x is not None and y is not None:
        z = number(params.get("z")) if params.get("z_known") is not False else None
        return {"x": x, "y": y, "z": z}
    guid = params.get("server_entity_guid") or params.get("object_guid") or params.get("guid")
    entity = (state.get("packet_entities") or {}).get(str(guid)) if guid else None
    position = (entity or {}).get("position") or {}
    point = position.get("estimate") or position
    if number(point.get("x")) is None or number(point.get("y")) is None:
        return None
    return {"x": number(point["x"]), "y": number(point["y"]), "z": number(point.get("z"))}


def effective_yards(state: dict, point: dict) -> float | None:
    """Flat yards plus the walk a height difference costs (own server height)."""
    position = state.get("player_world_position") or {}
    px, py = number(position.get("x")), number(position.get("y"))
    if px is None or py is None:
        return None
    flat = math.hypot(point["x"]-px, point["y"]-py)
    pz, z = own_height(state), point.get("z")
    if pz is None or z is None:
        return flat
    return flat + VERTICAL_FACTOR*max(0., abs(z-pz)-LEVEL_SLACK_YARDS)


def _quest_of(params: dict) -> str | None:
    quest = params.get("quest_id")
    if quest is None and params.get("quest_ids"):
        quest = params["quest_ids"][0]
    return str(quest) if quest is not None else None


def _counted_kill(proposal, state: dict) -> bool:
    """The proposal serves an unfinished "N/M slain" objective with M >= 3."""
    params = proposal.parameters
    if not (proposal.skill == "MOVE" and params.get("purpose") in KILL_PURPOSES
            or proposal.skill == "TARGET"):
        return False
    quest_id = _quest_of(params)
    quest = next((q for q in state.get("active_quests") or ()
                  if isinstance(q, dict) and str(q.get("quest_id")) == quest_id), None)
    if quest is None:
        return False
    objectives = [o for o in quest.get("objectives") or () if isinstance(o, dict)]
    match = re.fullmatch(r"\d+:(\d+)", str(params.get("objective_id") or ""))
    if match and int(match.group(1)) < len(objectives):
        objectives = [objectives[int(match.group(1))]]
    return any(o.get("is_complete") is not True and (number(o.get("required")) or 0) >= COUNTED_REQUIRED
               and str(o.get("type") or "").upper() == "KILL" for o in objectives)


class ObjectiveContext:
    """Landing points and freshly accepted quests, observed every tick."""

    def __init__(self) -> None:
        self.landing: dict | None = None
        self.pending: str | None = None
        self.quests_seen: dict[str, float] = {}
        self.previous: dict = {}

    def observe(self, state: dict, now: float) -> None:
        position = state.get("player_world_position") or {}
        x, y = number(position.get("x")), number(position.get("y"))
        scene = state.get("packet_scene") or {}
        current = {"on_taxi": state.get("on_taxi") is True, "in_vehicle": state.get("in_vehicle") is True,
                   "scene": scene.get("active") is True,
                   "server_map": (state.get("packet_server_map") or {}).get("sampled_at"),
                   "x": x, "y": y, "at": now}
        before = self.previous
        if before:
            reason = None
            if before["on_taxi"] and not current["on_taxi"]:
                reason = "TAXI_ENDED"
            elif before["in_vehicle"] and not current["in_vehicle"]:
                reason = "VEHICLE_EXITED"
            elif before["scene"] and not current["scene"]:
                reason = "SCENE_ENDED"
            elif current["server_map"] is not None and current["server_map"] != before["server_map"]:
                reason = "MAP_TRANSFER"
            elif (None not in (x, y, before["x"], before["y"]) and 0 <= now-before["at"] <= TELEPORT_SECONDS
                  and math.hypot(x-before["x"], y-before["y"]) > TELEPORT_YARDS
                  and (state.get("movement") or {}).get("flying") is not True):
                reason = "TELEPORTED"
            if reason:
                self.pending = reason
        if self.pending and x is not None and y is not None and not current["in_vehicle"] \
                and not current["on_taxi"] and not current["scene"]:
            self.landing = {"x": x, "y": y, "z": own_height(state), "at": now, "reason": self.pending}
            self.pending = None
        self.previous = current
        quests = {str(q.get("quest_id")) for q in state.get("active_quests") or ()
                  if isinstance(q, dict) and q.get("quest_id") is not None}
        first = not self.quests_seen and not before
        for quest in quests - set(self.quests_seen):
            self.quests_seen[quest] = -math.inf if first else now
        for quest in set(self.quests_seen) - quests:
            del self.quests_seen[quest]

    def snapshot(self) -> dict:
        return {"landing": dict(self.landing) if self.landing else None,
                "quests_seen": dict(self.quests_seen)}


def objective_adjustment(proposal, state: dict, context: dict | None, now: float) -> dict | None:
    """Bounded score adjustment of one objective-pursuit proposal, explained."""
    if context is None or not is_objective_pursuit(proposal):
        return None
    point = proposal_point(proposal, state)
    yards = effective_yards(state, point) if point else None
    parts = {"route": 0., "landing": 0., "counted": 0., "fresh": 0.}
    if yards is not None:
        parts["route"] = -min(ROUTE_PENALTY_CAP, yards/ROUTE_YARDS_PER_POINT)
    landing = context.get("landing")
    if landing and point and 0 <= now-landing["at"] <= LANDING_SECONDS:
        near = math.hypot(point["x"]-landing["x"], point["y"]-landing["y"]) <= LANDING_RADIUS_YARDS
        level = (landing.get("z") is None or point.get("z") is None
                 or abs(point["z"]-landing["z"]) <= LANDING_LEVEL_YARDS)
        if near and level:
            parts["landing"] = LANDING_BONUS
    if _counted_kill(proposal, state) and (yards is None or yards > NEARBY_YARDS):
        parts["counted"] = -COUNTED_PENALTY
    seen = (context.get("quests_seen") or {}).get(_quest_of(proposal.parameters) or "")
    if seen is not None and 0 <= now-seen <= FRESH_SECONDS:
        parts["fresh"] = FRESH_BONUS
    return {**{k: round(v, 2) for k, v in parts.items()},
            "effective_yards": round(yards, 1) if yards is not None else None,
            "total": round(sum(parts.values()), 2)}


def better_than_commitment(preferred, matching: list, scores: dict) -> bool:
    """A clearly better objective target than anything serving the commitment."""
    if not is_objective_pursuit(preferred) or preferred.key not in scores:
        return False
    best = max((scores[p.key]["total"] for p in matching if p.key in scores), default=None)
    return best is not None and scores[preferred.key]["total"] - best >= PREEMPT_MARGIN
