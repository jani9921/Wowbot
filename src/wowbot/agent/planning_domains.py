"""Non-quest proposal domains used by the high-level planner.

They only construct proposals from the read-only WorldQuery boundary.  They
never mutate planner state, choose input bindings, or execute commands.
"""
from __future__ import annotations

from .models import Goal, Proposal, number, words
from .map_poi_planning import MapPoiPlanningPolicy
from .planning_types import point
from .world import WorldModel


class ResourceDomain:
    def __init__(self, memory=None):
        self.memory = memory

    def propose(self, world: WorldModel, goal: Goal) -> list[Proposal]:
        result = []
        for node in world.query.resources(goal.domain):
            kind = str(node.get("kind") or node.get("resource_type") or "").upper()
            if kind != goal.domain or not node.get("confirmed"):
                continue
            location = point(node)
            if location:
                result.append(Proposal.make("MOVE", "Megerősített gyűjtési hely", location, priority=40))
            if node.get("x_client") is not None and node.get("y_client") is not None:
                skill = kind if kind in {"HERB", "MINE"} else "GATHER"
                result.append(Proposal.make(skill, "Tooltip által megerősített gyűjthető objektum", {
                    "x": node["x_client"], "y": node["y_client"], "node_id": node.get("id"),
                    "resource_type": kind, "map_id": node.get("map_id", world.state.get("map_id")),
                    "world_x": node.get("x"), "world_y": node.get("y")}, priority=50))
        if self.memory and goal.domain in {"HERB", "MINE"}:
            for site in self.memory.resource_sites(world.state, goal.domain):
                result.append(Proposal.make("MOVE", "Ismételten igazolt resource-site újravizsgálata",
                                            {"map_id": site["map_id"], "x": site["x"], "y": site["y"],
                                             "resource_type": goal.domain, "site_key": site["site_key"]},
                                            confidence=site["reliability"], priority=32))
        if goal.domain == "FISH":
            bobber = world.query.fishing()
            if bobber.get("bite_confirmed") and bobber.get("x") is not None and bobber.get("y") is not None:
                result.append(Proposal.make("GATHER", "Megerősített kapás", bobber, priority=80))
            elif not world.state.get("is_casting") and not bobber.get("active"):
                for action in world.state.get("actionbar", []):
                    if "fishing" in words(str(action.get("name", ""))) and action.get("is_usable") is True:
                        result.append(Proposal.make("FISH", "Elérhető Fishing képesség",
                                                    {"binding": action.get("action")}, priority=30))
        return result


class InventoryDomain:
    """Capacity constraint only; it never chooses items to destroy or sell."""
    def propose(self, world: WorldModel, goal: Goal) -> list[Proposal]:
        inventory = world.query.inventory()
        if inventory.get("free_slots") != 0:
            return []
        destination = point(goal.parameters.get("inventory_destination"))
        if destination:
            return [Proposal.make("MOVE", "Inventory full: explicit vendor/bank destination",
                                  {**destination, "inventory_subgoal": "RETURN"}, priority=88)]
        return [Proposal.make("WAIT", "Inventory full: nincs explicit vendor/bank cél vagy biztonságos item policy",
                              {"constraint": "INVENTORY_FULL"}, priority=88)]


class DungeonDomain:
    """Dungeon constraints only; execution stays in shared skills."""
    def __init__(self) -> None:
        self.map_pois = MapPoiPlanningPolicy()

    def propose(self, world: WorldModel, goal: Goal) -> list[Proposal]:
        state = world.query.instance()
        if state.get("inside") is not True:
            # Outside: the Encounter Journal API entrance is the route target.
            return self.map_pois.entrance_moves(world, goal)
        result = []
        destination = point(state.get("objective_location"))
        if destination:
            result.append(Proposal.make("MOVE", "Dungeon objective explicit telemetry location",
                                        {**destination, "encounter_id": state.get("encounter_id")},
                                        confidence=number(state.get("confidence")) or .8, priority=65))
        group = world.query.group()
        leader = point(group.get("leader_position"))
        if leader and (world.distance(leader) or 0) > .005:
            result.append(Proposal.make("FOLLOW", "Group leader explicit telemetry position",
                                        {**leader, "group_role": "FOLLOW", "follow_group_leader": True,
                                         "follow_entity_guid": (group.get("leader_guid")
                                                                or (group.get("leader") or {}).get("guid")),
                                         "follow_min_distance": .003,
                                         "follow_max_distance": .008}, confidence=.8, priority=60))
        mechanic = point(state.get("safe_location") or state.get("mechanic_location"))
        if mechanic and state.get("mechanic_active"):
            result.append(Proposal.make("MOVE", "Aktív encounter-mechanika explicit safe location",
                                        {**mechanic, "mechanic_id": state.get("mechanic_id")},
                                        confidence=number(state.get("mechanic_confidence")) or .8,
                                        priority=92))
        if group.get("ready") is False or state.get("pull_allowed") is False:
            result.append(Proposal.make("WAIT", "Group/encounter gate: pull még nem engedélyezett",
                                        {"group_gate": True}, priority=89))
        return result


class PvPDomain:
    """PvP objective/team hints only; no independent combat or input path."""
    def propose(self, world: WorldModel, goal: Goal) -> list[Proposal]:
        state = world.query.pvp()
        if state.get("match_active") is not True:
            return []
        destination = point(state.get("objective_location"))
        result = []
        health, maximum = number(world.state.get("health")), number(world.state.get("max_health"))
        retreat = point(state.get("retreat_location"))
        if retreat and health is not None and maximum and health/maximum <= .25:
            result.append(Proposal.make("MOVE", "PvP survival retreat explicit safe region",
                {**retreat, "pvp_policy": "RETREAT"}, confidence=.9, priority=95))
        if destination:
            result.append(Proposal.make("MOVE", "PvP objective explicit telemetry location",
                {**destination, "pvp_objective_id": state.get("objective_id"),
                 "pvp_policy": "DEFEND" if state.get("defend") else "CAPTURE"},
                confidence=number(state.get("confidence")) or .75, priority=65))
        return result
