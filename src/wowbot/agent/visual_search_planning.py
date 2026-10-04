"""Input-free visual search and perception-fallback proposal policy."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .models import Proposal, number
from wowbot.vision.world3d.learned_detector import RUNTIME_SUBJECT_CONFIDENCE


@dataclass(frozen=True, slots=True)
class VisualSearchPlanningResult:
    proposals: tuple[Proposal, ...]
    camera_search_step: int
    camera_search_next_at: float
    camera_search_position: tuple[float, float] | None


class VisualSearchPlanningPolicy:
    """Arbitrate UNKNOWN inspection/search fallbacks without executing them."""

    QUEST_AREA_RADIUS_YARDS = 30.
    LOCAL_SEARCH_RETRY_SECONDS = 12.
    QUEST_AREA_MAX_DISTANCE_YARDS = 150.

    @classmethod
    def active_quest_area(cls, state: dict, quest_areas=None) -> dict | None:
        """The nearest unfinished quest's API objective area (WORLD_YARDS)."""
        from .planning_types import world_point
        quests = {str(quest.get("quest_id")): quest for quest in state.get("active_quests") or ()
                  if isinstance(quest, dict) and quest.get("is_complete") is not True}
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if not quests or px is None or py is None:
            return None
        best = None
        for location in state.get("quest_locations") or ():
            point = world_point(location) if isinstance(location, dict) else None
            quest_id = str((location or {}).get("quest_id"))
            if point is None or quest_id not in quests:
                continue
            if (position.get("instance_id") is not None
                    and str(position["instance_id"]) != str(point.get("instance_id"))):
                continue
            distance = math.hypot(point["x"]-px, point["y"]-py)
            if distance <= cls.QUEST_AREA_MAX_DISTANCE_YARDS and (best is None or distance < best[0]):
                best = (distance, quest_id, point)
        if best is None:
            return None
        _, quest_id, point = best
        objective = next((item for item in quests[quest_id].get("objectives") or ()
                          if isinstance(item, dict) and item.get("is_complete") is not True), {})
        search_area = {"x": point["x"], "y": point["y"],
                       "coordinate_space": "WORLD_YARDS",
                       "instance_id": point.get("instance_id"),
                       "map_id": point.get("map_id"),
                       "radius": cls.QUEST_AREA_RADIUS_YARDS}
        # The real shape learned from the minimap outline, when available.
        coverage = quest_areas.coverage_points(quest_id) if quest_areas is not None else []
        extent = quest_areas.extent(quest_id) if coverage else None
        if coverage and extent is not None:
            search_area.update({"x": extent[0], "y": extent[1], "radius": max(8., extent[2]),
                                "coverage_points": coverage,
                                "region_source": "MINIMAP_QUEST_AREA_OUTLINE"})
        return {"quest_id": quests[quest_id].get("quest_id"),
                "objective_id": f"{quest_id}:area",
                "objective_type": str(objective.get("type") or "UNKNOWN").upper(),
                "search_area": search_area}

    @staticmethod
    def _irrelevant_selection(world, target: dict, matching_objectives) -> bool:
        from .target_planning import is_player_unit
        guid = str((target or {}).get("guid") or "")
        if not guid:
            return False
        state = world.state
        commitment = (getattr(world, "runtime_context", {}) or {}).get("commitment") or {}
        if str(commitment.get("target_guid") or "") == guid:
            return False
        # Another player is never a quest NPC (live 2026-10-01: a gnome
        # player stayed selected and the search waited for a manual clear).
        # An NPC selection keeps the existing interaction/discovery order.
        return is_player_unit(target, state) and not (
            state.get("is_in_combat") and target.get("attackable", target.get("is_attackable")))

    def propose(
        self,
        proposals: list[Proposal],
        *,
        world,
        goal,
        now: float,
        target: dict,
        matching_objectives,
        active_perception,
        blocked_until: dict[str, float],
        world3d_probe_count: int,
        camera_search_step: int,
        camera_search_next_at: float,
        camera_search_position,
        quest_areas=None,
    ) -> VisualSearchPlanningResult:
        state = world.state
        values = list(proposals)
        # User 2026-10-01: an unrelated selection (another player, a random
        # NPC) must not block the quest-giver search until it is cleared by
        # hand.  The agent may simply click the right unit, which replaces
        # the selection; the old target is not acted on meanwhile.
        if self._irrelevant_selection(world, target, matching_objectives):
            target = {}
        # A client-selected GUID is identity evidence only. TAB may select an
        # off-screen unit; that must not suppress active visual search as if a
        # usable local target had already been found.
        target_guid = str(target.get("guid") or "")
        target_anchor = (target.get("screen_position") or
                         (state.get("confirmed_mouseover_anchors") or {}).get(target_guid))
        target_in_range = any(
            action.get("is_harmful") is True and action.get("in_range") is True
            for action in state.get("actionbar", []))
        local_target = target if (target_anchor or target_in_range) else {}
        # Only a goal-relevant selected identity is a useful clue for this
        # search. An arbitrary Rabbit/old friendly selection must not trigger
        # camera scanning or outrank the normal map/location hierarchy.
        blind_selected_identity = (bool(target_guid) and not local_target
                                   and bool(matching_objectives))
        search_target_absent = not target or blind_selected_identity

        # A distant stable UNKNOWN subject is approached only for better
        # evidence.  No badge/colour becomes an entity or quest fact here.
        if (goal.domain == "QUEST" and search_target_absent and not state.get("world_map_open")
                and not state.get("is_in_combat")
                and not any(p.skill in {"TARGET", "INTERACT", "TALK", "QUEST_DIALOG", "FIELD_TURN_IN"}
                            for p in values)
                and not any(
                    p.skill == "MOVE" and p.parameters.get("require_navmesh") is True
                    and p.parameters.get("purpose") in {
                        "LOCATE_TURN_IN_REGION", "LOCATE_QUEST_OBJECTIVE_REGION"}
                    for p in values)):
            distant = []
            from .quest_giver_evidence import subject_has_quest_symbol
            world3d = [item for item in state.get("visual_candidates") or ()
                       if isinstance(item, dict) and item.get("source") == "WORLD3D"]
            for marker in world.query.visual_tracks(source="WORLD3D"):
                if (marker.get("self_player_avatar") is True
                        or (isinstance(marker.get("visual_identity"), dict)
                            and marker["visual_identity"].get("kind") == "SELF_PLAYER")):
                    continue
                kind = str(marker.get("detector_kind") or marker.get("kind") or "")
                height = (number(marker.get("servo_scale_fraction"))
                          or number(marker.get("bbox_height_fraction")))
                relations = marker.get("visual_relations") or []
                overhead = any(str(edge.get("type") or "").upper() == "ABOVE"
                               for edge in relations)
                appearance = marker.get("appearance") or {}
                active = active_perception.evaluate(marker, world, goal)
                rejected = str(
                    (active.get("rejection") or {}).get("belief") or "UNKNOWN").upper()
                visual_group = (marker.get("visual_group")
                                if isinstance(marker.get("visual_group"), dict) else {})
                labels = {str(value).lower() for value in marker.get("candidate_labels") or ()}
                labels.update(str(value).lower() for value in
                              appearance.get("anchor_candidate_labels") or ())
                labels.update(str(value).lower() for value in
                              visual_group.get("appearance_labels") or ())
                anchor = appearance.get("anchor_appearance") or {}
                hue = str(
                    appearance.get("hue_family") or anchor.get("hue_family") or "").lower()
                badge_like = ("quest_badge_like" in labels
                              or (number(appearance.get("quest_badge_likeness")) or 0) >= .52)
                quest_coloured_overhead = (
                    overhead and hue in {"yellow", "orange"}
                    and "quest_marker_like" in labels)
                body_supported = (number(appearance.get("body_geometry")) or 0) >= .65
                # A temporally supported symbol<->subject group is already
                # sufficient evidence to justify active perception.  It is
                # deliberately *not* recognition: the subject stays UNKNOWN
                # until mouseover/addon evidence supplies identity or role.
                group_supported = str(
                    visual_group.get("belief") or "UNKNOWN").upper() == "SUPPORTED"
                # A learned overhead glyph spatially attached to a subject is
                # still UNKNOWN, but it is a much better first observation
                # during quest-giver discovery than an unrelated bare body.
                # Live PID 1468 detected both Jaina's glyph/body and Ke-La's
                # body; effective fusion confidence reduced the derived Jaina
                # probe to .304, so the old generic .65 threshold discarded it
                # and the priority-85 bare-body INSPECT won.  Treat the stable
                # group as attention evidence only; addon mouseover remains
                # the identity/quest-role authority.
                grouped_overhead_cue = (
                    overhead and group_supported
                    and bool(labels & {
                        "learned_symbol_like", "overhead_symbol_like",
                        "overhead_symbol_like_cue", "quest_marker_like",
                    }))
                learned_label = str(
                    appearance.get("learned_label_hypothesis") or "").lower()
                learned_subject = ("learned_subject_like" in labels
                                   or learned_label in {
                                       "humanoid_unit_like", "creature_unit_like"})
                interesting = (badge_like or quest_coloured_overhead
                               or learned_subject
                               or (number(appearance.get("proposal_score")) or 0) >= .70
                               or (overhead and body_supported)
                               or (overhead and group_supported))
                minimum_confidence = (.24 if (kind == "unknown_subject_probe"
                                               and grouped_overhead_cue)
                                      else RUNTIME_SUBJECT_CONFIDENCE
                                      if learned_subject else .65)
                if ("subject" in kind and height is not None and height < .09
                        and (number(marker.get("stable_frames")) or 0) >= 3
                        and (number(marker.get("confidence")) or 0) >= minimum_confidence
                        and interesting and rejected not in {"SUPPRESSED", "REJECTED"}):
                    # A "!"/"?" box right over the body is the strongest cue
                    # for a quest giver or turn-in NPC (user 2026-10-03).
                    symbol_subject = subject_has_quest_symbol(marker, world3d)
                    cue_rank = (2 if badge_like or symbol_subject
                                else 1 if grouped_overhead_cue else 0)
                    # Quest-giver discovery (user 2026-09-30: "Keressen quest
                    # givert").  Live 18:37 SEEK chased bare bodies 4-8 % tall
                    # with 1-57 hits that vanished within ~2 s.  Without any
                    # overhead evidence a body is only worth an approach once
                    # it is an established, currently observed, non-tiny track.
                    if (not state.get("active_quests") and cue_rank == 0
                            and not (overhead and (group_supported or body_supported))
                            and ((number(marker.get("stable_frames")) or 0) < 10
                                 or marker.get("coasting") is True
                                 or (number(marker.get("age")) or 0) < .6
                                 or height < .045)):
                        continue
                    distant.append(
                        (cue_rank, active.get("utility", 0), marker, active))
            if distant:
                cue_rank, _, marker, active = max(
                    distant, key=lambda row: (row[0], row[1]))
                values = [proposal for proposal in values
                          if not (proposal.skill == "INSPECT"
                                  and proposal.parameters.get("track_id")
                                  == marker.get("track_id"))]
                if cue_rank:
                    values = [proposal for proposal in values
                              if not (proposal.skill == "INSPECT"
                                      and proposal.parameters.get("source") == "WORLD3D")]
                values.append(Proposal.make(
                    "SEEK_VISUAL_CUE",
                    "Távoli, érdekes UNKNOWN World3D track óvatos vizuális megközelítése",
                    {**marker, "active_perception": active,
                     "purpose": "IDENTIFY", "ready_bbox_height": .09},
                    confidence=.7, priority=87 if cue_rank == 2 else 86 if cue_rank == 1 else 78))

        local_world3d = [proposal for proposal in values
                         if proposal.skill == "INSPECT"
                         and proposal.parameters.get("source") == "WORLD3D"
                         and blocked_until.get(proposal.key, 0) <= now]
        if (goal.domain == "QUEST" and not target and not state.get("world_map_open")
                and not state.get("is_in_combat") and local_world3d
                and world3d_probe_count < 4):
            values = [proposal for proposal in values if proposal.skill != "OPEN_MAP"]

        position = world.player_position()
        if (position is not None and camera_search_position is not None
                and math.hypot(position[0] - camera_search_position[0],
                               position[1] - camera_search_position[1]) > .004):
            camera_search_step = 0
            camera_search_next_at = 0.
        if position is not None:
            camera_search_position = position

        actionable_location = any(
            proposal.skill in {"MOVE", "REACH_LOCATION", "REACH_OBJECT"}
            and (proposal.skill != "MOVE"
                 or (world.distance(proposal.parameters) or 0) > .003)
            for proposal in values)
        arrived_location = any(
            proposal.skill == "MOVE"
            and (distance := world.distance(proposal.parameters)) is not None
            and distance <= .003 for proposal in values)
        relevant_target = bool(local_target) and (bool(matching_objectives) or (
            state.get("is_in_combat")
            and target.get("attackable", target.get("is_attackable")) is True))
        explicit_local = any(
            proposal.skill in {
                "TARGET", "QUEST_DIALOG", "FIELD_TURN_IN", "EXTRA_ACTION", "GATHER", "HERB",
                "MINE", "OBJECT_USE"}
            for proposal in values)
        inspectable_local = any(
            proposal.skill == "INSPECT"
            and proposal.parameters.get("source") == "WORLD3D"
            and blocked_until.get(proposal.key, 0) <= now
            for proposal in values)
        domain_actionable = any(
            proposal.skill not in {
                "OPEN_MAP", "INSPECT", "SEEK_VISUAL_CUE", "WAIT",
                "CAMERA_CONTROL", "ACQUIRE_TARGET"}
            and not (proposal.skill == "MOVE"
                     and (world.distance(proposal.parameters) or 0) <= .003)
            and blocked_until.get(proposal.key, 0) <= now
            for proposal in values)
        quest_transition_now = any(
            event.get("event_type") in {"QUEST_ACCEPTED", "QUEST_TURNED_IN"}
            for event in state.get("events", []))

        objective_local_search = (
            goal.domain == "QUEST" and bool(state.get("active_quests"))
            and search_target_absent and not state.get("world_map_open")
            and not state.get("is_in_combat") and not actionable_location
            and not relevant_target and not explicit_local and not domain_actionable
            and inspectable_local and world3d_probe_count >= 1
            and camera_search_step < 4
            # Live 2026-10-04 10:36: this SEEK's postcondition (a visible
            # candidate) already held, so it ended in 0.1 s with no input,
            # and re-proposing it every tick filtered out the INSPECT hovers
            # for minutes (SEEK/WAIT loop).  A re-request within the window
            # means the last one did nothing: let the INSPECTs through.
            and now - float(self.__dict__.get("_local_search_at", -1e9)) >= self.LOCAL_SEARCH_RETRY_SECONDS)
        if objective_local_search:
            self.__dict__["_local_search_at"] = now
            values = [proposal for proposal in values
                      if not ((proposal.skill in {"INSPECT", "OPEN_MAP"}
                               and proposal.parameters.get("source") == "WORLD3D")
                              or proposal.skill == "OPEN_MAP")]
            values.append(Proposal.make(
                "SEEK_VISUAL_CUE",
                "Aktív quest célterületén az első hover után célzott World3D keresés",
                {"source": "WORLD3D", "kind": "active_visual_search",
                 "purpose": "SEARCH_LOCAL_OBJECTIVE_AREA", "x": .5, "y": .45,
                 "scan_budget": 4},
                confidence=.75, priority=88))

        if goal.domain == "QUEST" and not state.get("active_quests") and world3d_probe_count >= 4:
            values = [proposal for proposal in values
                      if not (proposal.skill == "INSPECT"
                              and proposal.parameters.get("source") == "WORLD3D")]

        if (goal.domain == "QUEST" and (not state.get("active_quests") or arrived_location
                                        or blind_selected_identity
                                        or self.active_quest_area(state, quest_areas) is not None)
                and search_target_absent and not state.get("world_map_open")
                and not state.get("is_in_combat") and not actionable_location
                and not relevant_target and not explicit_local and not inspectable_local
                and not domain_actionable and not quest_transition_now
                and not any(proposal.skill == "SEEK_VISUAL_CUE" for proposal in values)
                and camera_search_step < 4 and now >= camera_search_next_at):
            pan_x = (.36, .64, .32, .68)[camera_search_step]
            values = [proposal for proposal in values if proposal.skill != "OPEN_MAP"]
            values.append(Proposal.make(
                "SEEK_VISUAL_CUE", "Nincs helyi cél: persistent World3D vizuális keresés",
                {"source": "WORLD3D", "kind": "active_visual_search",
                 "purpose": "FIND_LOCAL_QUEST_RELEVANT_SUBJECT",
                 "x": pan_x, "y": .45}, confidence=.7, priority=78))

        # The camera sweep at this spot found nothing and there is no quest:
        # walk to another navmesh cell and sweep again (user 2026-09-30).  The
        # navigation adapter turns this into an mmap-validated MOVE; arriving
        # there resets camera_search_step, so move -> sweep -> move repeats.
        if (goal.domain == "QUEST" and not state.get("active_quests")
                and search_target_absent and not state.get("world_map_open")
                and not state.get("is_in_combat") and not actionable_location
                and not relevant_target and not explicit_local and not inspectable_local
                and not domain_actionable and not quest_transition_now
                and not any(proposal.skill in {"SEEK_VISUAL_CUE", "OPEN_MAP"}
                            for proposal in values)
                and camera_search_step >= 4 and now >= camera_search_next_at
                and isinstance(state.get("player_world_position"), dict)):
            # Last resort after World3D -> world map -> TDB role location: an
            # available OPEN_MAP / REACH_LOCATION keeps its documented order.
            values.append(Proposal.make(
                "SEEK_VISUAL_CUE",
                "Nincs quest és helyi cue: quest giver keresés a navmesh-en belül (mozgás + körbenézés)",
                {"source": "WORLD3D", "kind": "active_visual_search",
                 "purpose": "FIND_QUEST_GIVER_AREA", "x": .5, "y": .45},
                confidence=.65, priority=77))

        # An active quest's area was reached, the camera sweeps found nothing
        # and nothing else is actionable.  Live 2026-10-03 (Cooking Meat:
        # collect Raw Meat from wildlife) the agent then waited 2 minutes.
        # Walk the quest's API area cell by cell and sweep at every cell.
        if (goal.domain == "QUEST" and state.get("active_quests")
                and search_target_absent and not state.get("world_map_open")
                and not state.get("is_in_combat") and not actionable_location
                and not relevant_target and not explicit_local and not inspectable_local
                and not domain_actionable and not quest_transition_now
                and not any(proposal.skill == "SEEK_VISUAL_CUE" for proposal in values)
                and camera_search_step >= 4 and now >= camera_search_next_at
                and isinstance(state.get("player_world_position"), dict)):
            area = self.active_quest_area(state, quest_areas)
            if area is not None:
                values = [proposal for proposal in values if proposal.skill != "OPEN_MAP"]
                values.append(Proposal.make(
                    "SEEK_VISUAL_CUE",
                    "Aktív quest területén nincs helyi cél: a terület bejárása cellánként, ott körbenézés",
                    {"source": "WORLD3D", "kind": "active_visual_search",
                     "purpose": "SEARCH_LOCAL_OBJECTIVE_AREA", "x": .5, "y": .45,
                     "scan_budget": 4, "roam_quest_area": True, **area},
                    confidence=.65, priority=76))

        # Confirmed identity or an already actionable selected target outranks
        # unrelated information gathering; this is proposal filtering only.
        if any(proposal.skill == "TARGET"
               and proposal.parameters.get("ground_truth_handoff")
               for proposal in values):
            values = [proposal for proposal in values
                      if proposal.skill not in {"INSPECT", "SEEK_VISUAL_CUE"}]
        if target.get("guid") and any(proposal.skill in {
                "INTERACT", "TALK", "QUEST_DIALOG", "FIELD_TURN_IN", "COMBAT", "ASSIST",
                "USE_ON_TARGET", "GATHER", "HERB", "MINE", "FISH",
        } for proposal in values):
            values = [proposal for proposal in values
                      if not (proposal.skill == "INSPECT"
                              and proposal.parameters.get("source") == "WORLD3D")]

        return VisualSearchPlanningResult(
            tuple(values), camera_search_step, camera_search_next_at,
            camera_search_position)
