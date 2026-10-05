"""Adapt high-level proposals through navigation-owned planning state."""
from __future__ import annotations

import math

from .models import Proposal
from .navigation_situation import NavigationSituationPolicy


class NavigationProposalAdapter:
    """Return a navigation-ready proposal; never start movement or input."""

    def __init__(self, navigation, registry=None, map_search_policy=None) -> None:
        self.navigation = navigation
        self.registry = registry
        self.map_search_policy = map_search_policy
        self.situation = NavigationSituationPolicy()
        self._roam = self._new_roam()
        self._turn_in_search: dict = {}

    @staticmethod
    def _new_roam() -> dict:
        return {"generation": 0, "region_id": None, "explored": [], "cell": None}

    def adapt(self, proposal: Proposal, proposals: list[Proposal], world,
              now: float, *, last_result: dict | None = None) -> Proposal:
        if last_result is None:
            runtime_context = getattr(world, "runtime_context", {}) or {}
            candidate = runtime_context.get("last_result")
            last_result = candidate if isinstance(candidate, dict) else {}
        proposal = self._search_waypoint(proposal, world, now, last_result=last_result)
        proposal = self.situation.adapt(
            proposal, world=world, navigation=self.navigation,
            last_result=last_result,
            map_relocalization_exhausted=bool(
                self.map_search_policy is not None
                and self.map_search_policy.state.exhausted))
        if (self.registry is not None and proposal.skill != "WAIT"
                and not self.registry.available(proposal, world)):
            return Proposal.make(
                "WAIT", "A navigation-context által kért skill előfeltétele hiányzik",
                {"blocked_skill": proposal.skill,
                 "purpose": proposal.parameters.get("purpose"),
                 "navigation_context": proposal.parameters.get("navigation_context")},
                confidence=proposal.confidence,
                evidence=proposal.evidence)
        if proposal.skill not in {"MOVE", "FOLLOW"}:
            return proposal
        if proposal.skill == "MOVE":
            guarded = self._guard_physical_move(proposal, world)
            if guarded is None:
                return Proposal.make(
                    "WAIT", "Mozgás elutasítva: nincs azonos-instance WORLD_YARDS + MMAP útvonal-kontraktus",
                    {"blocked_skill": "MOVE", "purpose": proposal.parameters.get("purpose"),
                     "movement_guard": "MMAP_SAME_INSTANCE_REQUIRED"},
                    confidence=proposal.confidence, evidence=proposal.evidence)
            proposal = guarded
        if not self.navigation.permits(world, proposal.parameters, now):
            # Live 2026-10-05 12:25: Alaria's pin (38 yd west) was briefly
            # blocked; the "alternative" was the Harpy pin 155 yd east, so the
            # agent walked east for the 5 s cooldown and back (user: "oda-vissza
            # ment két quest között").  A detour that is much longer than the
            # blocked trip is no alternative; waiting/looking around is.
            distance_of = getattr(world, "distance", None)
            blocked_distance = distance_of(proposal.parameters) if callable(distance_of) else None
            alternatives = [
                item for item in proposals
                if item.key != proposal.key
                and (item.confidence >= .55
                     or item.skill in {"WAIT", "INSPECT", "DEFEND", "ESCAPE", "COMBAT"})
                and (item.skill not in {"MOVE", "FOLLOW"}
                     or (self.navigation.permits(world, item.parameters, now)
                         and not self._much_farther(world, item, blocked_distance)))]
            if alternatives:
                return alternatives[0]
            retry_lookup = getattr(self.navigation, "retry_at", None)
            retry_at = (retry_lookup(world, proposal.parameters, now)
                        if callable(retry_lookup) else None)
            return Proposal.make(
                "WAIT", "Nincs tartós közeledés vagy supported akadály: az út ideiglenesen tiltva; új helybizonyíték szükséges",
                {"blocked_skill": proposal.skill,
                 "blocked_proposal": proposal.key,
                 "blocked_reason": "NAVIGATION_DESTINATION_TEMPORARILY_BLOCKED",
                 "retry_at": retry_at,
                 "waiting_for": ["ALTERNATIVE_ROUTE", "FRESH_LOCATION_EVIDENCE",
                                 "NAVIGATION_RETRY_DEADLINE"],
                 "next_action": "REPLAN_ALTERNATIVE_OR_RETRY"},
                confidence=proposal.confidence, evidence=proposal.evidence)
        waypoint = self.navigation.waypoint(world, proposal.parameters)
        return Proposal.make(
            proposal.skill, proposal.reason, waypoint,
            proposal.confidence, proposal.priority, proposal.evidence)

    @staticmethod
    def _much_farther(world, item: Proposal, blocked_distance) -> bool:
        """A WORLD_YARDS alternative more than twice (and 40 yd) farther."""
        distance_of = getattr(world, "distance", None)
        if (blocked_distance is None or not callable(distance_of)
                or item.parameters.get("coordinate_space") != "WORLD_YARDS"):
            return False
        distance = distance_of(item.parameters)
        return distance is not None and distance > 2.*blocked_distance + 40.

    @staticmethod
    def _guard_physical_move(proposal: Proposal, world) -> Proposal | None:
        """Make every coordinate-bearing MOVE a same-instance mmap request.

        Cross-zone travel is intentionally deferred.  Screen/minimap/map
        pixels remain perception evidence and can never become locomotion.
        """
        parameters = dict(proposal.parameters)
        # Deterministic legacy/unit fixtures use normalized coordinates and a
        # synthetic test session with no world/instance telemetry.  They do
        # not control a client. Keep that pure simulation path available;
        # every real decoded session remains fail-closed below.
        session_id = str(world.state.get("session_id") or "")
        if (not world.state.get("player_world_position")
                and (not session_id or session_id.startswith("test:"))):
            return proposal
        if parameters.get("coordinate_space") != "WORLD_YARDS":
            return None
        player = world.state.get("player_world_position") or {}
        player_instance = player.get("instance_id")
        destination_instance = parameters.get("instance_id", parameters.get("world_map_id"))
        if player_instance is None or destination_instance is None:
            return None
        try:
            same_instance = int(player_instance) == int(destination_instance)
        except (TypeError, ValueError):
            return None
        if not same_instance:
            return None
        parameters.update({"instance_id": int(destination_instance),
                           "world_map_id": int(destination_instance),
                           "require_navmesh": True})
        return Proposal.make(proposal.skill, proposal.reason, parameters,
                             proposal.confidence, proposal.priority, proposal.evidence)

    # Quest-giver roaming: a ring of candidate cells around the spot where a
    # roaming region starts, each verified to lie on a walkable mmap polygon.
    ROAM_RADIUS_YARDS = 28.
    ROAM_RING_POINTS = 8
    ROAM_EXPLORED_RADIUS_YARDS = 14.
    ROAM_CELL_TIMEOUT_SECONDS = 40.
    ROAM_MAX_Z_DELTA_YARDS = 12.
    ROAM_MAX_REGIONS = 12

    def _quest_giver_roam(self, proposal: Proposal, world, now: float) -> Proposal:
        """FIND_QUEST_GIVER_AREA -> the next unexplored navmesh cell (MOVE).

        Returns the unchanged SEEK (a camera sweep in place) when no position,
        no navmesh surface or no unexplored walkable cell is available.
        """
        state = world.state
        roam = self._roam
        position = state.get("player_world_position") or {}
        try:
            px, py = float(position["x"]), float(position["y"])
            instance = int(position["instance_id"])
        except (KeyError, TypeError, ValueError):
            return proposal
        pz = position.get("z") if isinstance(position.get("z"), (int, float)) else None
        walkable = getattr(self.navigation, "walkable_point", None)
        if not callable(walkable):
            return proposal
        units = (state.get("target") or {}, state.get("mouseover") or {})
        quest_giver_seen = any(
            unit.get("guid") and unit.get("quest_role") in {"QUEST_GIVER", "QUEST_TURN_IN"}
            for unit in units)
        region_id = roam["region_id"]
        cell = roam["cell"]
        if region_id is not None and cell is not None:
            # Arrival (or giving up on an unreachable cell) retires it.
            cell_id, cx, cy, emitted_at = cell
            if (math.hypot(px-cx, py-cy) <= 4.
                    or now-emitted_at > self.ROAM_CELL_TIMEOUT_SECONDS):
                self.navigation.mark_search_cell_visited(region_id, cell_id, now)
                roam["explored"].append((cx, cy))
                roam["cell"] = None
        for _ in range(2):
            if region_id is None or self.navigation.search_region_completed(region_id):
                if roam["generation"] >= self.ROAM_MAX_REGIONS:
                    return proposal
                roam["generation"] += 1
                roam["explored"].append((px, py))
                points = []
                for index in range(self.ROAM_RING_POINTS):
                    angle = 2*math.pi*index/self.ROAM_RING_POINTS
                    x = px + self.ROAM_RADIUS_YARDS*math.cos(angle)
                    y = py + self.ROAM_RADIUS_YARDS*math.sin(angle)
                    if any(math.hypot(x-ex, y-ey) < self.ROAM_EXPLORED_RADIUS_YARDS
                           for ex, ey in roam["explored"]):
                        continue
                    surface = walkable(instance, {"x": x, "y": y}, z_hint=pz)
                    if surface is None:
                        continue
                    if (pz is not None and isinstance(surface.get("z"), (int, float))
                            and abs(float(surface["z"])-pz) > self.ROAM_MAX_Z_DELTA_YARDS):
                        continue
                    points.append({"x": x, "y": y})
                if not points:
                    return proposal
                region_id = f"quest_giver_roam:{instance}:{roam['generation']}"
                roam["region_id"], roam["cell"] = region_id, None
                self.navigation.begin_search_region(region_id, {
                    "x": px, "y": py, "coordinate_space": "WORLD_YARDS",
                    "instance_id": instance, "map_id": position.get("map_id"),
                    "radius": self.ROAM_RADIUS_YARDS, "coverage_points": points})
            self.navigation.observe_search_region(
                region_id, state, now, target_detected=quest_giver_seen)
            waypoint = self.navigation.next_search_waypoint(region_id, state)
            if waypoint is not None:
                break
            region_id = None
        else:
            return proposal
        if roam["cell"] is None or roam["cell"][0] != waypoint.get("search_cell_id"):
            roam["cell"] = (waypoint.get("search_cell_id"), float(waypoint["x"]),
                            float(waypoint["y"]), now)
        return Proposal.make(
            "MOVE", "Quest giver keresés: következő feltáratlan navmesh cella, ott körbenézés",
            {**waypoint, "purpose": "FIND_QUEST_GIVER_AREA", "require_navmesh": True},
            proposal.confidence, proposal.priority, proposal.evidence)

    # Turn-in NPC search around an arrived API turn-in point (user
    # 2026-10-03: "go right up to it"): sweep the camera, walk to the next
    # mmap-validated cell of the small area, sweep again, and so on.
    TURN_IN_SWEEP_TIMEOUT_SECONDS = 30.
    TURN_IN_CELL_TIMEOUT_SECONDS = 25.
    TURN_IN_CELL_ARRIVED_YARDS = 3.5

    def _turn_in_area_search(self, proposal: Proposal, world, now: float,
                             last_result: dict | None) -> Proposal:
        params = proposal.parameters
        area = params["search_area"]
        position = world.state.get("player_world_position") or {}
        try:
            px, py = float(position["x"]), float(position["y"])
            ax, ay = float(area["x"]), float(area["y"])
        except (KeyError, TypeError, ValueError):
            return proposal
        search = self._turn_in_search
        last = last_result if isinstance(last_result, dict) else {}
        spot = f"{params.get('quest_id')}:{round(ax)}:{round(ay)}"
        if search.get("spot") != spot:
            search.clear()
            search.update(spot=spot, generation=0, swept=False, cell=None,
                          sweep_started=now, seen_action=last.get("action_id"))
        region_id = f"turn_in:{spot}:{search['generation']}"
        self.navigation.begin_search_region(region_id, area)
        if (last.get("skill") == "SEEK_VISUAL_CUE" and last.get("purpose") == "SEARCH_TURN_IN_AREA"
                and last.get("action_id") != search.get("seen_action")):
            search["seen_action"] = last.get("action_id")
            search["swept"] = True
        cell = search.get("cell")
        if cell is not None:
            cell_id, cx, cy, started = cell
            if (math.hypot(px-cx, py-cy) <= self.TURN_IN_CELL_ARRIVED_YARDS
                    or now-started > self.TURN_IN_CELL_TIMEOUT_SECONDS):
                self.navigation.mark_search_cell_visited(region_id, cell_id, now)
                search.update(cell=None, swept=False, sweep_started=now)
            else:
                return self._turn_in_cell_move(proposal, cell, area)
        if not search["swept"] and now-search["sweep_started"] < self.TURN_IN_SWEEP_TIMEOUT_SECONDS:
            return proposal   # look around here first
        self.navigation.observe_search_region(region_id, world.state, now, target_detected=False)
        waypoint = self.navigation.next_search_waypoint(region_id, world.state)
        if waypoint is None:
            # Every cell was visited: start the same small area over.
            search.update(generation=search["generation"]+1, swept=False, sweep_started=now)
            return proposal
        cell = (waypoint.get("search_cell_id"), float(waypoint["x"]), float(waypoint["y"]), now)
        search["cell"] = cell
        return self._turn_in_cell_move(proposal, cell, area, waypoint)

    @staticmethod
    def _turn_in_cell_move(proposal: Proposal, cell, area: dict, waypoint: dict | None = None) -> Proposal:
        base = dict(waypoint or {})
        base.update({"x": cell[1], "y": cell[2], "coordinate_space": "WORLD_YARDS",
                     "instance_id": area.get("instance_id"), "world_map_id": area.get("instance_id"),
                     "map_id": area.get("map_id"), "search_cell_id": cell[0],
                     "stop_distance": 2.5})
        return Proposal.make(
            "MOVE", "Leadó NPC keresése: a leadási pont következő környékbeli cellája, ott körbenézés",
            {**base, "quest_id": proposal.parameters.get("quest_id"),
             "search_area": area, "purpose": "SEARCH_TURN_IN_AREA", "require_navmesh": True},
            proposal.confidence, proposal.priority, proposal.evidence)

    def _search_waypoint(self, proposal: Proposal, world, now: float,
                         *, last_result: dict | None = None) -> Proposal:
        if world.state.get("active_quests") and self._roam["generation"]:
            self._roam = self._new_roam()   # the next no-quest search starts fresh
        if (proposal.skill == "SEEK_VISUAL_CUE"
                and proposal.parameters.get("purpose") == "SEARCH_TURN_IN_AREA"
                and isinstance(proposal.parameters.get("search_area"), dict)):
            return self._turn_in_area_search(proposal, world, now, last_result)
        if (proposal.skill == "SEEK_VISUAL_CUE"
                and proposal.parameters.get("purpose") == "FIND_QUEST_GIVER_AREA"):
            return self._quest_giver_roam(proposal, world, now)
        if not (proposal.skill == "SEEK_VISUAL_CUE"
                and proposal.parameters.get("purpose") == "SEARCH_LOCAL_OBJECTIVE_AREA"
                and isinstance(proposal.parameters.get("search_area"), dict)):
            return proposal
        area = proposal.parameters["search_area"]
        region_id = ":".join((str(proposal.parameters.get("quest_id") or ""),
                              str(proposal.parameters.get("objective_id") or ""),
                              str(area.get("map_id") or "")))
        roam = proposal.parameters.get("roam_quest_area") is True
        if roam:
            # A quest-area roam restarts once every cell was visited.
            generations = self.__dict__.setdefault("_area_generations", {})
            region_id = f"{region_id}:{generations.get(region_id, 0)}"
        self.navigation.begin_search_region(region_id, area)
        objective_type = str(proposal.parameters.get("objective_type") or "").upper()
        units = (world.state.get("target") or {}, world.state.get("mouseover") or {})
        if objective_type in {"KILL", "KILL_CREDIT", "COMBAT"} or roam:
            target_detected = any(
                unit.get("guid") and unit.get("is_attackable", unit.get("attackable")) is True
                and unit.get("is_dead", unit.get("dead")) is not True
                for unit in units)
        elif objective_type in {"TALK", "SPEAK", "INTERACT", "USE_OBJECT"}:
            target_detected = any(unit.get("guid") for unit in units)
        else:
            target_detected = any(unit.get("guid") for unit in units)
        self.navigation.observe_search_region(
            region_id, world.state, now, target_detected=target_detected)
        waypoint = self.navigation.next_search_waypoint(region_id, world.state)
        if waypoint is None:
            if roam:
                base = region_id.rsplit(":", 1)[0]
                self._area_generations[base] = self._area_generations.get(base, 0) + 1
            return proposal
        return Proposal.make(
            "MOVE", "Quest keresési régió szisztematikus következő cellája",
            {**waypoint, "quest_id": proposal.parameters.get("quest_id"),
             "objective_id": proposal.parameters.get("objective_id"),
             "objective_type": proposal.parameters.get("objective_type"),
             "search_area": area, "purpose": "SEARCH_LOCAL_OBJECTIVE_AREA",
             "require_navmesh": True},
            proposal.confidence, proposal.priority, proposal.evidence)
