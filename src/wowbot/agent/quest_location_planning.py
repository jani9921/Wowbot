"""Quest localisation proposals separated from high-level ranking."""
from __future__ import annotations

import math

from .models import Proposal, number
from .objective_locator import ObjectiveLocator
from .planning_types import point, world_point
from .turnin_resolver import TurnInLocationKind, TurnInResolver
from .travel_reach_fallback import TravelReachFallbackPolicy
from .escort_follow import EscortFollowPolicy
from .object_interaction_flow import ObjectInteractionFlow
from .tooltip_quest import effective_mouseover
from .entity_objective_flows import KillObjectiveFlow, SpeakObjectiveFlow
from .map_poi_planning import MapPoiPlanningPolicy
from .world import WorldModel


class QuestLocationPlanningPolicy:
    """Resolve explicit quest locations without owning movement or input."""

    def __init__(self) -> None:
        self.objective_locator = ObjectiveLocator()
        self.turnin_resolver = TurnInResolver()
        self.travel_fallback = TravelReachFallbackPolicy()
        self.escort_follow = EscortFollowPolicy()
        self.object_interaction = ObjectInteractionFlow()
        self.speak_flow = SpeakObjectiveFlow()
        self.kill_flow = KillObjectiveFlow()
        self.reached_quest_locations: dict[tuple, str] = {}
        self.quest_search_regions: dict[tuple[str, int], dict] = {}
        self.map_pois = MapPoiPlanningPolicy()
        # quest_id -> (x, y) of the API turn-in point the MOVE arrived at.
        self.turn_in_arrivals: dict[str, tuple[float, float]] = {}
        from .quest_area_memory import QuestAreaMemory
        # Objective areas learned from the minimap's blue outline.
        self.quest_areas = QuestAreaMemory()

    # Live 2026-10-02 21:27: the turn-in POI (-423, -2611) lay ~14 yd from
    # Jaina.  The MOVE arrived within 6 yd, was proposed again, made no more
    # progress, the route was temporarily blocked (WAIT) and the same MOVE
    # came back -- for minutes, while its priority-110 route suppressed every
    # visual search.  Within this distance of an arrived turn-in point the
    # agent looks for the turn-in NPC instead of walking to the point again.
    TURN_IN_ARRIVED_YARDS = 12.
    TURN_IN_SEARCH_RADIUS_YARDS = 35.
    TURN_IN_SEARCH_AREA_YARDS = 18.

    def _remember_blue_search_region(self, state: dict, quest_id: str,
                                     map_where: dict | None,
                                     route_where: dict | None) -> dict | None:
        """Associate UNKNOWN blue appearance with quest POI evidence.

        Blue never means quest by itself.  Association requires the active
        quest's normalized POI to fall inside/near the observed World Map area
        and Blizzard's authoritative affine map->world transform.
        """
        if not map_where or not route_where:
            return self.quest_search_regions.get((str(quest_id), int(map_where.get("map_id") or 0))) if map_where else None
        map_id = int(map_where.get("map_id") or 0)
        key = (str(quest_id), map_id)
        transform = state.get("map_world_transform") or {}
        if (transform.get("ui_map_id") != map_id
                or transform.get("instance_id") != route_where.get("instance_id")):
            return self.quest_search_regions.get(key)
        candidates = []
        px, py = number(map_where.get("x")), number(map_where.get("y"))
        for candidate in state.get("visual_candidates") or []:
            if (candidate.get("source") != "WORLD_MAP_CV"
                    or "blue_region_like" not in (candidate.get("candidate_labels") or [])):
                continue
            bounds = candidate.get("map_local_bounds") or {}
            left, top = number(bounds.get("left")), number(bounds.get("top"))
            right, bottom = number(bounds.get("right")), number(bounds.get("bottom"))
            if None in {px, py, left, top, right, bottom}:
                continue
            distance = max(left-px, px-right, top-py, py-bottom, 0.)
            if distance <= .06:
                candidates.append((distance, -(right-left)*(bottom-top), bounds))
        if not candidates:
            return self.quest_search_regions.get(key)
        bounds = min(candidates)[2]
        origin = transform.get("origin") or {}
        x_axis, y_axis = transform.get("x_axis") or {}, transform.get("y_axis") or {}
        ox, oy = number(origin.get("x")), number(origin.get("y"))
        ax, ay = number(x_axis.get("x")), number(x_axis.get("y"))
        bx, by = number(y_axis.get("x")), number(y_axis.get("y"))
        if None in {ox, oy, ax, ay, bx, by}:
            return self.quest_search_regions.get(key)
        points = []
        for fy in (0., .5, 1.):
            for fx in (0., .5, 1.):
                mx = bounds["left"] + (bounds["right"]-bounds["left"])*fx
                my = bounds["top"] + (bounds["bottom"]-bounds["top"])*fy
                points.append({"x": ox+ax*mx+bx*my, "y": oy+ay*mx+by*my})
        region = {**route_where, "map_id": map_id,
                  "coverage_points": points, "region_source": "BLUE_REGION_LIKE_ASSOCIATED",
                  "blue_region_bounds": dict(bounds), "require_navmesh": True}
        self.quest_search_regions[key] = region
        return region

    @staticmethod
    def location_key(location: dict) -> tuple:
        from .models import number
        return (str(location.get("quest_id")), location.get("map_id"),
                round(number(location.get("location_map_x", location.get("x"))) or -1., 5),
                round(number(location.get("location_map_y", location.get("y"))) or -1., 5),
                str(location.get("location_source", location.get("source")) or ""))

    def mark_reached(self, location: dict, state: dict) -> None:
        if location.get("quest_id") is not None:
            self.reached_quest_locations[self.location_key(location)] = WorldModel.quest_signature(state)
            x, y = number(location.get("x")), number(location.get("y"))
            if (location.get("purpose") == "LOCATE_TURN_IN_REGION"
                    and location.get("coordinate_space") == "WORLD_YARDS"
                    and x is not None and y is not None):
                self.turn_in_arrivals[str(location["quest_id"])] = (x, y)
        self.map_pois.mark_reached(location, number(state.get("monotonic_time")) or 0.)

    @staticmethod
    def has_actionable_turnin_world_location(state: dict) -> bool:
        """Whether addon evidence already supplies a routable turn-in region.

        World-map/World3D search is active perception for missing location
        evidence.  It must not pre-empt a completed quest whose API waypoint
        has already been converted to same-instance world coordinates.
        """
        completed = {str(quest.get("quest_id")) for quest in state.get("active_quests", [])
                     if quest.get("quest_id") is not None and quest.get("is_complete") is True}
        return any(
            str(location.get("quest_id")) in completed
            and isinstance(location.get("world_position"), dict)
            and location["world_position"].get("coordinate_space") == "WORLD_YARDS"
            and location["world_position"].get("instance_id") is not None
            and number(location["world_position"].get("x")) is not None
            and number(location["world_position"].get("y")) is not None
            for location in state.get("quest_locations", []))

    def turn_in_arrived(self, quest_id, destination: dict, state: dict) -> bool:
        """The agent stands at this completed quest's API turn-in point."""
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        dx, dy = number(destination.get("x")), number(destination.get("y"))
        if None in (px, py, dx, dy) or destination.get("coordinate_space") != "WORLD_YARDS":
            return False
        if (position.get("instance_id") is not None and destination.get("instance_id") is not None
                and str(position["instance_id"]) != str(destination["instance_id"])):
            return False
        distance = math.hypot(px-dx, py-dy)
        if distance <= self.TURN_IN_ARRIVED_YARDS:
            return True
        arrived = self.turn_in_arrivals.get(str(quest_id))
        return (arrived is not None and math.hypot(arrived[0]-dx, arrived[1]-dy) <= 5.
                and distance <= self.TURN_IN_SEARCH_RADIUS_YARDS)

    OBJECTIVE_AREA_ARRIVED_YARDS = 20.

    def _within_objective_area(self, destination: dict, state: dict, quest_id=None) -> bool:
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        dx, dy = number(destination.get("x")), number(destination.get("y"))
        if None in (px, py, dx, dy):
            return False
        areas = self.__dict__.get("quest_areas")
        if quest_id is not None and areas is not None and areas.contains(quest_id, px, py):
            return True   # inside the area learned from the minimap outline
        if (position.get("instance_id") is not None and destination.get("instance_id") is not None
                and str(position["instance_id"]) != str(destination["instance_id"])):
            return False
        return math.hypot(px-dx, py-dy) <= self.OBJECTIVE_AREA_ARRIVED_YARDS

    def turn_in_search(self, quest_id, destination: dict) -> Proposal:
        """Look for the turn-in NPC ("?") around an arrived turn-in point.

        Retail exposes no NPC world position, so the API point is only the
        neighbourhood.  The SEEK sweeps the camera (it prefers symbol-topped
        subjects); the navigation adapter alternates sweeps with walks to the
        cells of a small mmap-validated search area around the point.
        """
        area = {"x": float(destination["x"]), "y": float(destination["y"]),
                "coordinate_space": "WORLD_YARDS",
                "instance_id": destination.get("instance_id"),
                "map_id": destination.get("map_id"),
                "radius": self.TURN_IN_SEARCH_AREA_YARDS}
        return Proposal.make(
            "SEEK_VISUAL_CUE",
            "Leadási hely elérve: a leadó NPC (?) keresése körbenézéssel és a környék bejárásával",
            {"source": "WORLD3D", "kind": "active_visual_search",
             "purpose": "SEARCH_TURN_IN_AREA", "x": .5, "y": .45, "scan_budget": 4,
             "quest_id": quest_id, "search_area": area},
            confidence=.7, priority=66)

    def propose_turnins(self, records: dict, state: dict, primary_context: dict,
                        *, deferred=frozenset()) -> list[Proposal]:
        result: list[Proposal] = []
        for quest in records.values():
            qid = quest.quest_id
            if str(qid) in deferred:
                continue
            if (quest.current_state != "COMPLETED"
                    and str(getattr(quest, "lifecycle_state", ""))
                    not in {"OBJECTIVES_COMPLETE", "READY_TO_TURN_IN", "TURNING_IN"}):
                continue
            completion_mode = str(primary_context.get("completion_mode") or "UNKNOWN")
            turnin = self.turnin_resolver.locate(quest, state, completion_mode)
            if turnin.kind is TurnInLocationKind.LOCAL_ENTITY:
                result.append(Proposal.make(
                    "TALK", "Élő telemetria által igazolt quest leadó entity",
                    {"guid": turnin.entity_guid, "quest_id": qid,
                     "completion_mode": turnin.completion_mode,
                     "turnin_evidence": list(turnin.evidence)}, priority=92))
            elif (turnin.location
                  and turnin.location.get("coordinate_space") == "WORLD_YARDS"):
                if self.turn_in_arrived(qid, turnin.location, state):
                    result.append(self.turn_in_search(qid, turnin.location))
                    continue
                result.append(Proposal.make(
                    "MOVE", "Quest API által jelzett quest leadási keresési régió",
                    {**turnin.location, "quest_id": qid,
                     "completion_mode": turnin.completion_mode,
                     "turnin_kind": turnin.kind.value,
                     "turnin_evidence": list(turnin.evidence),
                     "purpose": "LOCATE_TURN_IN_REGION",
                     "require_navmesh": True}, priority=110))
        return result

    def propose_objective(self, world, obj, record, qid: str) -> list[Proposal]:
        if record is None:
            return []
        state = world.state
        if obj.type in {"ESCORT", "FOLLOW"}:
            return self.escort_follow.propose(obj, record, state)
        located = self.objective_locator.locate(obj, record, state)
        map_where = point(located.coordinates) if located and located.coordinates else None
        route_where = world_point(located.coordinates) if located and located.coordinates else None
        learned_search_region = self._remember_blue_search_region(
            state, record.quest_id, map_where, route_where)
        # Map coordinates are perception/location evidence. Physical movement
        # is authorized only by Blizzard's explicit same-instance WORLD_YARDS
        # conversion so NavigationService can build an mmap corridor.
        where = route_where or map_where
        if where:
            params = {**where, "quest_id": record.quest_id,
                      "objective_id": obj.objective_id, "objective_type": obj.type,
                      "location_status": located.status.value,
                      "location_evidence": list(located.evidence)}
            if route_where:
                params.update({
                    "purpose": "LOCATE_QUEST_OBJECTIVE_REGION",
                    "require_navmesh": True,
                    "stop_distance": 8.0,
                })
            entity_flow = (self.speak_flow if obj.type in self.speak_flow.objective_types
                           else self.kill_flow if obj.type in self.kill_flow.objective_types
                           else None)
            entity_target_confirmed = bool(
                entity_flow and entity_flow.matches_target(obj, state.get("target") or {}))
            reached_entity_area = bool(
                entity_flow
                and (self.reached_quest_locations.get(self.location_key(params))
                     == WorldModel.quest_signature(state)
                     or (located.status.value == "SEARCH_AREA"
                         and where.get("map_id") == state.get("map_id")
                         and world.distance(where) is not None
                         and world.distance(where) <= .003)))
            if entity_target_confirmed:
                # CombatPlanningPolicy or QuestDomain now owns the validated
                # target handoff; do not emit another navigation proposal.
                return []
            if reached_entity_area:
                return entity_flow.propose_local_search(obj, record, params)
            object_objective = obj.type in {"USE_OBJECT", "INTERACT"} and bool(
                getattr(obj, "target_object", None)
                or self.object_interaction.expected_identity(obj).get("expected_tooltips"))
            object_identity_confirmed = (
                object_objective
                and self.object_interaction.mouseover_matches(
                    self.object_interaction.expected_identity(obj),
                    effective_mouseover(state)))
            reached_object_area = (
                object_objective
                and (self.reached_quest_locations.get(self.location_key(params))
                     == WorldModel.quest_signature(state)
                     or (located.status.value == "SEARCH_AREA"
                         and where.get("map_id") == state.get("map_id")
                         and world.distance(where) is not None
                         and world.distance(where) <= .003)))
            if object_identity_confirmed:
                # QuestDomain will now emit OBJECT_USE from the same fresh
                # addon mouseover/cursor sample. Do not obscure it with MOVE.
                return []
            if reached_object_area:
                return self.object_interaction.propose_local_search(obj, record, params)
            reached_without_credit = (
                obj.type in {"TRAVEL_TO", "REACH_AREA"}
                and self.reached_quest_locations.get(self.location_key(params))
                == WorldModel.quest_signature(state))
            if reached_without_credit:
                return self.travel_fallback.propose(obj, record, state, params)
            confidence, priority = obj.confidence, 40 if obj.optional else 45
            at_search_area = (located.status.value == "SEARCH_AREA"
                              and where.get("map_id") == state.get("map_id")
                              and not (state.get("target") or (state.get("mouseover") or {}).get("guid"))
                              and (world.distance(where) is not None and world.distance(where) <= .003))
            if at_search_area:
                search_area = dict(learned_search_region or route_where or where)
                return [Proposal.make(
                    "SEEK_VISUAL_CUE", "Az objective keresési területére érve: korlátos helyi vizuális keresés",
                    {"purpose": "SEARCH_LOCAL_OBJECTIVE_AREA", "search_area": search_area,
                     "quest_id": record.quest_id, "objective_id": obj.objective_id,
                     "objective_type": obj.type, "scan_budget": 4, "time_budget": 22.},
                    confidence=confidence, priority=55)]
            if route_where is None:
                # A normalized marker can guide World Map perception and
                # arrival checks, but must not become direct-line locomotion.
                return []
            if located.status.value == "KNOWN_LOCATION":
                best = max(obj.location_candidates, key=lambda item: item.get("confidence", 0))
                params.update({"hypothesis_identity_key": best.get("identity_key"),
                               "hypothesis_source": best.get("source")})
                confidence, priority = min(obj.confidence, best.get("confidence", .3)), 35
            return [Proposal.make("MOVE", "Quest objective graph következő elérhető helye",
                                  params, confidence=confidence, priority=priority)]
        if obj.location_candidates:
            best = max(obj.location_candidates, key=lambda item: item.get("confidence", 0))
            candidate = world_point(best)
            if candidate:
                return [Proposal.make(
                    "MOVE", "Automatikus quest-hipotézis: korábbi entity/location candidate ellenőrzése",
                    {**candidate, "quest_id": record.quest_id, "objective_id": obj.objective_id,
                     "objective_type": obj.type, "hypothesis_identity_key": best.get("identity_key"),
                     "hypothesis_source": best.get("source"),
                     "purpose": "LOCATE_QUEST_OBJECTIVE_REGION",
                     "require_navmesh": True, "stop_distance": 8.0},
                    confidence=min(obj.confidence, best.get("confidence", .3)), priority=35)]
        return []

    # Stop at charge distance (user 2026-10-04): Captain Garrick pushes a
    # walking player back; 15 yd is inside Charge's 8-25 yd band, and the
    # minimap dot is only ~5 yd/px precise at the default zoom anyway.
    DOT_ARRIVED_YARDS = 15.
    DOT_ASSOCIATION_YARDS = 150.
    DOT_TURN_IN_YARDS = 30.
    LOCAL_AREA_FOCUS_SECONDS = 120.

    def _local_area_focus(self, state: dict) -> str | None:
        """The unfinished quest whose objective area holds the player, while
        its bounded local-focus window lasts."""
        open_ids = {str(quest.get("quest_id")) for quest in state.get("active_quests") or ()
                    if isinstance(quest, dict) and quest.get("is_complete") is not True}
        local = None
        for location in state.get("quest_locations") or ():
            destination = world_point(location) if isinstance(location, dict) else None
            qid = str(location.get("quest_id")) if isinstance(location, dict) else None
            if destination and qid in open_ids and self._within_objective_area(destination, state, qid):
                local = qid
                break
        now = number(state.get("monotonic_time"))
        focus = self.__dict__.setdefault("_area_focus", {})
        if local is None or now is None:
            focus.clear()
            return None
        started = focus.setdefault(local, now)
        for other in [key for key in focus if key != local]:
            focus.pop(other)
        return local if now - started <= self.LOCAL_AREA_FOCUS_SECONDS else None

    def minimap_dot_move(self, world) -> Proposal | None:
        """Walk to the nearest yellow quest-objective dot on the minimap.

        User 2026-10-04: Captain Garrick (Enhanced Combat Tactics) showed as
        a yellow minimap dot ~38 yd away while the agent searched the camp
        visually.  No API exposes NPC or blip positions; the dot's offset,
        the addon's minimap view radius and the player position give a
        WORLD_YARDS point.  A selected unit is also drawn as a yellow dot
        (user), so the dot is used only with no target selected.
        """
        state = world.state
        candidate = next((item for item in state.get("visual_candidates") or ()
                          if isinstance(item, dict) and item.get("kind") == "minimap_quest_dot"
                          and item.get("dots")), None)
        if candidate is None:
            return None
        open_quests = [quest for quest in state.get("active_quests") or ()
                       if isinstance(quest, dict) and quest.get("is_complete") is not True]
        if not open_quests:
            return None
        if (state.get("target") or {}).get("guid"):
            # A selected unit is drawn as a yellow dot too (user): it may be
            # the dot.  The objective NPC itself is handled by COMBAT/INTERACT.
            return None
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        geometry = state.get("minimap_geometry") or {}
        view = number(candidate.get("view_radius_yards")) or number(geometry.get("view_radius_yards"))
        if px is None or py is None or not view:
            return None
        from wowbot.vision.minimap_quest_area import offsets_to_world
        rotate = bool(candidate.get("rotate_minimap", geometry.get("rotate_minimap")))
        points = offsets_to_world([dot["offset"] for dot in candidate["dots"]],
                                  player_x=px, player_y=py, view_radius_yards=view,
                                  rotate=rotate, facing=number(state.get("orientation")))
        if not points:
            return None
        open_ids = {str(quest.get("quest_id")) for quest in open_quests}
        completed_ids = {str(quest.get("quest_id")) for quest in state.get("active_quests") or ()
                         if isinstance(quest, dict) and quest.get("is_complete") is True}
        pois = []
        for location in state.get("quest_locations") or ():
            where = world_point(location) if isinstance(location, dict) else None
            if where:
                pois.append((str(location.get("quest_id")), float(where["x"]), float(where["y"])))
        candidates = []
        for x, y in points:
            near_turn_in = any(qid in completed_ids
                               and math.hypot(qx-x, qy-y) <= self.DOT_TURN_IN_YARDS
                               for qid, qx, qy in pois)
            if near_turn_in:
                # Live 2026-10-04 09:20: the dot 10-15 yd from Down with the
                # Quilboar's turn-in point was its quest ender; with one open
                # quest it was attributed to Quilboar Shadow Magic (200 yd
                # away) and the agent walked off to the turn-in NPC.
                continue
            associated = [(math.hypot(qx-x, qy-y), qid) for qid, qx, qy in pois
                          if qid in open_ids and math.hypot(qx-x, qy-y) <= self.DOT_ASSOCIATION_YARDS]
            if associated:
                candidates.append((x, y, min(associated)[1]))
            elif len(open_quests) == 1 and not any(qid in open_ids for qid, _, _ in pois):
                candidates.append((x, y, str(open_quests[0].get("quest_id"))))
        if not candidates:
            return None
        dx, dy, quest_key = min(candidates, key=lambda item: math.hypot(item[0]-px, item[1]-py))
        if math.hypot(dx-px, dy-py) <= self.DOT_ARRIVED_YARDS:
            return None        # there: local hover/tooltip search identifies the NPC
        quest_id = next((quest.get("quest_id") for quest in open_quests
                         if str(quest.get("quest_id")) == quest_key), quest_key)
        return Proposal.make(
            "MOVE", "Sárga quest-pötty a minimapon: odamegyek, ott azonosítom az NPC-t",
            {"x": round(dx, 1), "y": round(dy, 1), "coordinate_space": "WORLD_YARDS",
             "instance_id": position.get("instance_id"), "map_id": state.get("map_id"),
             "quest_id": quest_id, "purpose": "APPROACH_MINIMAP_QUEST_DOT",
             "stop_distance": self.DOT_ARRIVED_YARDS, "require_navmesh": True,
             "dot_world": [round(dx, 1), round(dy, 1)]},
            confidence=.7, priority=88)

    def propose_known_locations(
        self, world, runtime_map_scan_started: float | None = None,
        *, deferred=frozenset(),
    ) -> list[Proposal]:
        state = world.state
        result: list[Proposal] = []
        local_quest = self._local_area_focus(state)
        dot_move = self.minimap_dot_move(world)
        if dot_move is not None and (local_quest is None
                                     or str(dot_move.parameters.get("quest_id")) == local_quest):
            result.append(dot_move)
        searched: list[tuple[float, float]] = []
        for location in state.get("quest_locations", []):
            where = point(location)
            qid = location.get("quest_id")
            completed = any(q.get("quest_id") == qid and q.get("is_complete")
                            for q in state.get("active_quests", []))
            if completed and str(qid) in deferred:
                # Nearby unfinished quests come first; turn in together later.
                continue
            # A completed quest's normalized map marker is only a search
            # region.  It must never launch direct-line movement across
            # terrain.  C_Map's explicit world conversion is the only route
            # endpoint accepted here, and it requires an mmap corridor.
            destination = world_point(location)
            if destination and completed and self.turn_in_arrived(qid, destination, state):
                spot = (float(destination["x"]), float(destination["y"]))
                if not any(math.hypot(spot[0]-x, spot[1]-y) <= 5. for x, y in searched):
                    searched.append(spot)
                    result.append(self.turn_in_search(qid, destination))
                continue
            if destination and not completed and self._within_objective_area(destination, state, qid):
                # Live 2026-10-03: inside the objective area every kill credit
                # changed the quest signature, so the "reached" mark went stale
                # and the same MOVE came back, made no progress and was blocked
                # (WAIT "út ideiglenesen tiltva").  Local search owns this area.
                continue
            if destination and not completed and local_quest is not None and str(qid) != local_quest:
                # Live 2026-10-04 09:15: at 1/7 inside the Quilboar Shadow
                # Magic area the other quest's MOVE (and its minimap dot) won
                # and the agent left.  Finish the local area first, bounded.
                continue
            if destination:
                reached = self.reached_quest_locations.get(self.location_key(location))
                if completed or reached != WorldModel.quest_signature(state):
                    result.append(Proposal.make(
                        "MOVE", "Leadási hely mmap útvonalon" if completed else "Quest térképi helyének felderítése",
                        {**destination,
                         "quest_id": qid,
                         # Preserve the originating UI marker identity only
                         # for reached-location bookkeeping. Physical control
                         # still consumes destination WORLD_YARDS x/y.
                         "location_map_x": location.get("x"),
                         "location_map_y": location.get("y"),
                         "location_source": location.get("source"),
                         "stop_distance": 6.0 if completed else 8.0,
                         "purpose": ("LOCATE_TURN_IN_REGION" if completed
                                     else "LOCATE_QUEST_OBJECTIVE_REGION"),
                         "require_navmesh": True},
                        # A confirmed completed-quest world endpoint is the
                        # active subgoal, not background exploration.  Keep it
                        # above generic INSPECT/SEEK proposals even after the
                        # ranker's bounded distance cost.
                        priority=110 if completed else 40))
        # No active quest: the Retail quest-line API names the available "!"
        # givers with world positions (user 2026-10-01), ahead of map CV.
        result.extend(self.map_pois.quest_giver_moves(world))
        for location in world.query.remembered_locations({"QUEST_GIVER", "QUEST_TURN_IN", "QUEST_RELATED"}):
            if location.get("source") == "TDB_REFERENCE":
                continue
            where = point(location)
            provenance = location.get("provenance") or {}
            observed = number(provenance.get("observed_monotonic"))
            runtime_map_validated = bool(
                runtime_map_scan_started is not None and observed is not None
                and observed >= runtime_map_scan_started
                and provenance.get("session_id") == world.session_id
                and provenance.get("marker_associated") is True)
            if (where and location.get("semantic_type") in
                    {"QUEST_GIVER", "QUEST_TURN_IN", "QUEST_RELATED"}
                    and runtime_map_validated):
                result.append(Proposal.make(
                    "MOVE", "Korábbi térképi megfigyelés felkeresése; újraazonosítás szükséges",
                    where, confidence=.65, priority=58))
        return result
