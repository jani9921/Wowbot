"""Read-only visual inspection proposal policy.

Raw detections remain UNKNOWN observations.  This module only ranks eligible
inspection locations and builds proposals; it cannot recognize an entity,
select the global winning proposal, dispatch input, or mutate WorldModel.
"""
from __future__ import annotations

from .models import Proposal, number
from wowbot.vision.entity_memory import EntityMemory
from wowbot.vision.world3d.learned_detector import RUNTIME_SUBJECT_CONFIDENCE


class VisualInspectionPolicy:
    """Project visual tracks into bounded INSPECT proposals."""

    # Live 2026-10-03: one screen point was hovered 12 times in ~100 s and
    # another 11 times, every hover empty ("valid zero information"); the
    # long-term rejection memory needs several 30 s evidence groups first.
    # An empty hover suppresses that point while the view is unchanged.
    EMPTY_HOVER_RADIUS = .03
    # Shorter than the long-term rejection memory's 30 s evidence groups, so
    # both work: this stops the 7-10 s retry loop, that one learns REJECTED.
    EMPTY_HOVER_SECONDS = 25.
    CORPSE_HOVER_SECONDS = 120.
    # Live 2026-10-04 19:36: Quartermaster Richter, Captain Garrick and
    # Private Cole (stable tracks 9/11/51) were hovered in turn four times
    # in ~25 s although every hover had already named them (user).  A unit
    # the hover identified, which questing does not need (or which is
    # already the target), is not hovered again while the view holds.
    KNOWN_HOVER_SECONDS = 20.          # was 60 (user 2026-10-05: blocked Garrick and Private Cole)
    KNOWN_HOVER_MOVE_YARDS = 5.
    VIEW_MOVE_YARDS = 3.
    VIEW_TURN_RADIANS = .2

    @staticmethod
    def _view(world) -> tuple | None:
        from .models import number
        state = world.state
        position = state.get("player_world_position") or {}
        x, y = number(position.get("x")), number(position.get("y"))
        facing = number(state.get("orientation"))
        return None if None in (x, y, facing) else (x, y, facing)

    def _note_inspect_outcome(self, world, now: float) -> None:
        pending = self.__dict__.setdefault("_inspect_points", {})
        empty = self.__dict__.setdefault("_empty_hovers", [])
        result = (world.runtime_context.get("last_result") or {}) if hasattr(world, "runtime_context") else {}
        action = result.get("action_id")
        if (result.get("skill") == "INSPECT" and action
                and action != self.__dict__.get("_last_inspect_action")):
            self.__dict__["_last_inspect_action"] = action
            point = pending.get(result.get("key"))
            mouse = world.state.get("mouseover") or {}
            uninformative_unit = bool(mouse.get("guid")) and (
                mouse.get("is_dead") is True or mouse.get("dead") is True
                or mouse.get("is_player") is True)
            if point is not None and result.get("reason") == "expected_observation_missing":
                empty.append({**point, "at": now})
            elif point is not None and uninformative_unit:
                # Live 2026-10-04 09:20: seven hovers on the same looted
                # Quilboar Geomancer corpse and two on the player, while the
                # quest area went unexplored (user).  A corpse/own-character
                # hover answers nothing new; skip the spot and its track longer.
                empty.append({**point, "at": now, "ttl": self.CORPSE_HOVER_SECONDS})
            elif point is not None and mouse.get("guid"):
                known = self.__dict__.setdefault("_known_hovers", [])
                known.append({**point, "at": now, "guid": str(mouse["guid"]),
                              "name": mouse.get("name"),
                              "quest_related": mouse.get("quest_related") is True,
                              "attackable": mouse.get("is_attackable",
                                                      mouse.get("attackable")) is True,
                              "quest_signature": self._quest_signature(world.state)})
        known = self.__dict__.setdefault("_known_hovers", [])
        known[:] = [item for item in known if now - item["at"] <= self.KNOWN_HOVER_SECONDS][-60:]
        empty[:] = [item for item in empty
                    if now - item["at"] <= item.get("ttl", self.EMPTY_HOVER_SECONDS)][-30:]

    def _recently_empty(self, world, x: float, y: float, now: float, track_id=None) -> bool:
        import math
        view = self._view(world)
        for item in self.__dict__.get("_empty_hovers") or ():
            if track_id is not None and item.get("track_id") == track_id and item.get("ttl"):
                return True       # the same corpse/own-character track, wherever it is now
            if abs(item["x"]-x) > self.EMPTY_HOVER_RADIUS or abs(item["y"]-y) > self.EMPTY_HOVER_RADIUS:
                continue
            old = item.get("view")
            if view is None or old is None:
                continue          # no pose evidence: the view may have changed
            turned = abs((view[2]-old[2] + math.pi) % math.tau - math.pi)
            if (math.hypot(view[0]-old[0], view[1]-old[1]) < self.VIEW_MOVE_YARDS
                    and turned < self.VIEW_TURN_RADIANS):
                return True
        return False

    def _same_view_spot(self, world, item: dict, x: float, y: float) -> bool:
        import math
        if abs(item["x"]-x) > self.EMPTY_HOVER_RADIUS or abs(item["y"]-y) > self.EMPTY_HOVER_RADIUS:
            return False
        view, old = self._view(world), item.get("view")
        if view is None or old is None:
            return False
        turned = abs((view[2]-old[2] + math.pi) % math.tau - math.pi)
        return (math.hypot(view[0]-old[0], view[1]-old[1]) < self.VIEW_MOVE_YARDS
                and turned < self.VIEW_TURN_RADIANS)

    def _known_unneeded(self, world, x: float, y: float, track_id) -> bool:
        """The hover already named the unit here and questing does not need it."""
        target_guid = str((world.state.get("target") or {}).get("guid") or "")
        for item in reversed(self.__dict__.get("_known_hovers") or ()):
            same_track = track_id is not None and item.get("track_id") == track_id
            if not same_track and not self._same_view_spot(world, item, x, y):
                continue
            if target_guid and item["guid"] == target_guid:
                return True           # already selected: hovering adds nothing
            # Live 2026-10-05 05:39: with no quest, Private Cole was judged
            # from afar; the agent then walked to the API '!' spot where he
            # stood but never hovered him again and went to other givers
            # (user).  Whether a unit is needed depends on where the player
            # is (API giver proximity) and what is in view, so the verdict
            # holds only near the spot it was made, and never while
            # searching for a quest giver.
            if not self._near_hover_position(world, item):
                return False
            if not world.state.get("active_quests") and not item.get("attackable"):
                # User 2026-10-05 ("ne legyen felesleges sok inspect"): when
                # every "!" pin here has a remembered giver, a unit that is
                # none of them needs no second hover; otherwise keep looking.
                from .quest_creature_memory import remembered_creature
                creatures = world.state.get("quest_creatures") or {}
                return bool(creatures.get("pin_givers_known")) and remembered_creature(
                    world.state, item["guid"], name=item.get("name"), pin_givers=True) is None
            if item.get("quest_signature") != self._quest_signature(world.state):
                # Live 2026-10-05 05:38: Captain Garrick was named while the
                # vendor quest was open; once it completed he was its turn-in
                # NPC but stayed skipped (user).  "Not needed" holds only for
                # the quest state it was judged in.
                return False
            return not self._hover_identity_needed(world, item)
        return False

    def _near_hover_position(self, world, item: dict) -> bool:
        import math
        view, old = self._view(world), item.get("view")
        return (view is not None and old is not None
                and math.hypot(view[0]-old[0], view[1]-old[1]) <= self.KNOWN_HOVER_MOVE_YARDS)

    @staticmethod
    def _quest_signature(state: dict) -> tuple:
        return tuple(
            (str(quest.get("quest_id")), quest.get("is_complete") is True,
             tuple((objective.get("current"), objective.get("is_complete") is True)
                   for objective in quest.get("objectives") or () if isinstance(objective, dict)))
            for quest in state.get("active_quests") or () if isinstance(quest, dict))

    @staticmethod
    def _hover_identity_needed(world, item: dict) -> bool:
        if item.get("quest_related"):
            return True               # its tooltip lists an open objective
        if item.get("attackable"):
            return False
        from .quest_giver_evidence import friendly_npc_relevant, npc_objective_subjects
        quest_model = getattr(world, "quest_model", None)
        ready = quest_model.ready() if quest_model is not None else []
        types = {str(getattr(obj, "type", "") or "") for obj in ready}
        return friendly_npc_relevant(world.state, item["guid"], types, unit_name=item.get("name"),
                                     npc_subjects=npc_objective_subjects(ready))

    def propose(
        self,
        world,
        now: float,
        *,
        goal,
        registry,
        active_perception,
        blocked_until: dict[str, float],
        recent: dict[str, float],
        source=None,
        map_zoom_count: int = 0,
        map_zoom_requested: bool = False,
    ) -> list[Proposal]:
        result: list[Proposal] = []
        self._note_inspect_outcome(world, now)
        target = world.query.target()
        committed_identity = EntityMemory.identity_key(target) if target else None
        target_alive = bool(committed_identity) and not target.get("dead", target.get("is_dead"))
        nameplates = world.state.get("nameplates") or []
        markers = world.query.visual_tracks(source=source)

        # ActivePerception is the sole information-value authority. This
        # policy only turns its ordering into executable INSPECT proposals.
        recognition_by_track = {
            str(marker.get("track_id")): world.query.recognition_candidates(marker.get("track_id"))
            for marker in markers
            if marker.get("source") == "WORLD3D" and marker.get("track_id") is not None
        }
        world3d_attention = active_perception.rank_world3d(
            markers, world, goal, recognition_by_track=recognition_by_track)
        attention_by_track = {
            str(row["track_id"]): {**row, "rank": index + 1}
            for index, row in enumerate(world3d_attention)
            if row.get("track_id") is not None
        }

        from .quest_giver_evidence import subject_has_quest_symbol
        from .object_interaction_flow import only_object_objectives_open
        objects_only = only_object_objectives_open(world.state)
        world3d = [item for item in world.state.get("visual_candidates") or ()
                   if isinstance(item, dict) and item.get("source") == "WORLD3D"]
        for marker in markers:
            if (marker.get("source") == "WORLD_MAP_CV" and map_zoom_count
                    and marker.get("map_zoom_revision") != map_zoom_count):
                continue
            if source and marker.get("source") != source:
                continue
            # Detector kind is appearance evidence, never semantic truth.
            kind = marker.get("detector_kind") or marker.get("kind")
            if kind in {"obstacle_candidate", "visual_candidate"} or marker.get("inspectable") is False:
                continue
            if (world.state.get("is_in_combat")
                    and marker.get("track_id") != (target or {}).get("track_id")):
                continue
            if target_alive:
                recognition = world.query.recognition_candidates(marker.get("track_id"))
                matched = {candidate.get("identity_key") for item in recognition
                           for candidate in item.get("entity_candidates", [])}
                if committed_identity in matched:
                    continue

            on_map = marker.get("source") in {"MINIMAP_CV", "WORLD_MAP_CV"}
            quest_marker = kind in {
                "quest", "quest_giver", "quest_turn_in", "quest_related", "quest_area"}
            unknown_minimap = marker.get("source") == "MINIMAP_CV" and kind == "minimap_candidate"
            selected_minimap_target = marker.get("source") == "MINIMAP_CV" and kind == "target"
            unknown_map = marker.get("source") == "WORLD_MAP_CV" and kind == "unknown_map_marker"
            if on_map and not (quest_marker or unknown_minimap or selected_minimap_target or unknown_map):
                continue
            marker_appearance = marker.get("appearance") or {}
            marker_visual_group = (marker.get("visual_group")
                                   if isinstance(marker.get("visual_group"), dict) else {})
            marker_labels = {str(value).lower() for value in marker.get("candidate_labels") or ()}
            marker_labels.update(str(value).lower() for value in
                                 marker_appearance.get("anchor_candidate_labels") or ())
            marker_labels.update(str(value).lower() for value in
                                 marker_visual_group.get("appearance_labels") or ())
            learned_label = str(
                marker_appearance.get("learned_label_hypothesis") or "").lower()
            learned_subject = bool(
                marker.get("source") == "WORLD3D"
                and ("learned_subject_like" in marker_labels
                     or learned_label in {"humanoid_unit_like", "creature_unit_like"}))
            threshold = (.56 if marker.get("source") == "WORLD_MAP_CV"
                         else .60 if kind == "object_candidate" else .65)
            # A learned humanoid/creature proposal is still only UNKNOWN, but
            # repeated temporal support is exactly why it was retained.  The
            # old generic .65 gate discarded every admitted live humanoid
            # proposal (the reviewed sequence peaked at .599), so the agent
            # could see and track a unit without ever mouseover-inspecting it.
            # Let stability lower the observation threshold; mouseover remains
            # the semantic confirmation authority.
            if learned_subject:
                threshold = RUNTIME_SUBJECT_CONFIDENCE
            if kind == "object_candidate" and marker.get("stable_frames", 0) < 3:
                continue
            if kind in {"entity_candidate", "minimap_candidate", "target"} and marker.get("stable_frames", 0) < 3:
                continue
            x, y = number(marker.get("x")), number(marker.get("y"))
            if (number(marker.get("confidence")) or 0) < threshold or x is None or y is None:
                continue

            if marker.get("source") == "WORLD3D" and nameplates and not learned_subject:
                if "quest_marker_like" not in marker_labels and not any(
                        number(plate.get("nx")) is not None
                        and abs(number(plate.get("nx")) - x) <= .20
                        for plate in nameplates):
                    continue

            identity = marker.get("track_id")
            if identity is None:
                identity = f"{round(x * 40)}:{round(y * 40)}"
            inspection_id = (
                f"{world.session_id}:{world.state.get('map_id')}:"
                f"{marker.get('source')}:{kind}:{identity}")
            attention = attention_by_track.get(str(marker.get("track_id")))
            recognition = (recognition_by_track.get(str(marker.get("track_id")))
                           if marker.get("track_id") is not None else None)
            active = active_perception.evaluate(
                marker, world, goal, recognition_candidates=recognition)
            # The pixels and UNKNOWN track remain in the WorldModel, but a
            # probable third-person self-avatar view is not an inspection
            # target. Independent overhead/group evidence makes the same
            # overlapping region eligible again inside ActivePerception.
            if (marker.get("source") == "WORLD3D"
                    and active.get("world3d_features", {}).get("self_avatar_suppressed")):
                continue
            zoom_retry = (marker.get("source") == "WORLD_MAP_CV"
                          and map_zoom_requested and map_zoom_count < 5)
            if (active.get("rejection", {}).get("belief") in {"SUPPRESSED", "REJECTED"}
                    and not zoom_retry):
                continue

            relations = marker.get("visual_relations") or []
            supported_overhead = any(
                edge.get("type") == "ABOVE"
                and str(edge.get("belief", "")).upper() == "SUPPORTED"
                for edge in relations)
            candidate_overhead = any(edge.get("type") == "ABOVE" for edge in relations)
            is_subject_probe = kind == "unknown_subject_probe"
            visual_scale = (number(marker.get("servo_scale_fraction"))
                            or number(marker.get("bbox_height_fraction")))
            # A supported overhead quest symbol above the subject is strong
            # evidence; hovering it is worth it at a smaller scale (live
            # 2026-09-30: Lady Jaina with '!' at 8.3 % height was never
            # hovered).  The hover itself verifies identity by GUID.
            symbol_subject = (marker.get("source") == "WORLD3D"
                              and subject_has_quest_symbol(marker, world3d))
            if (learned_subject and not (supported_overhead or symbol_subject)
                    and not marker.get("quest_related") and objects_only):
                continue
            minimum_scale = .05 if supported_overhead or symbol_subject else .09
            if (not on_map and "subject" in str(kind)
                    and visual_scale is not None and visual_scale < minimum_scale):
                continue
            if marker.get("source") == "WORLD3D" and attention is not None:
                inspection_priority = 86 - min(10, int(attention["rank"]) - 1)
            else:
                inspection_base = (
                    86 if not on_map and supported_overhead and is_subject_probe
                    else 84 if not on_map and supported_overhead
                    else 46 if not on_map and candidate_overhead
                    else 75 if on_map else 5 if kind == "object_candidate"
                    else 35 if marker.get("source") == "WORLD3D" else 12)
                inspection_priority = (inspection_base if not on_map and supported_overhead
                                       else inspection_base + min(15, active["utility"] * 15))
            if symbol_subject:
                # Hover the unit under a "!"/"?" box before any other body.
                inspection_priority = max(inspection_priority, 88)
            proposal = Proposal.make(
                "INSPECT",
                "Quest marker tooltipjének ellenőrzése" if on_map
                else "Képi hipotézis ellenőrzése mouseoverrel",
                {**marker, "inspection_id": inspection_id, "active_perception": active,
                 **({"attention_rank": attention["rank"],
                     "attention_authority": "PLANNER_INSPECT_SELECTION"}
                    if attention is not None else {})},
                confidence=threshold,
                priority=inspection_priority,
            )
            if (marker.get("source") == "WORLD_MAP_CV" and map_zoom_requested
                    and map_zoom_count < 5 and world.state.get("world_map_open")
                    and not world.state.get("is_in_combat")):
                proposal = Proposal.make(
                    "INSPECT", "Bizonytalan World Map marker nagyítása és újravizsgálata",
                    {**proposal.parameters, "map_zoom_in": True,
                     "zoom_step": map_zoom_count + 1},
                    confidence=threshold, priority=proposal.priority)
            px, py = proposal.parameters.get("x"), proposal.parameters.get("y")
            if (not on_map and isinstance(px, (int, float)) and isinstance(py, (int, float))
                    and self._recently_empty(world, float(px), float(py), now,
                                             proposal.parameters.get("track_id"))):
                # User 2026-10-05: a unit the hover already named is hovered
                # again when chosen (no `_known_unneeded` block any more); the
                # hover/target round trips were made faster instead.  Empty
                # spots, corpses and the own character stay suppressed.
                continue
            if (blocked_until.get(proposal.key, 0) <= now
                    and recent.get(proposal.key, 0) <= now
                    and registry.available(proposal, world)):
                if isinstance(px, (int, float)) and isinstance(py, (int, float)):
                    self.__dict__.setdefault("_inspect_points", {})[proposal.key] = {
                        "x": float(px), "y": float(py), "view": self._view(world),
                        "track_id": proposal.parameters.get("track_id")}
                    points = self.__dict__["_inspect_points"]
                    while len(points) > 200:
                        points.pop(next(iter(points)))
                result.append(proposal)

        ordered = sorted(
            result, key=lambda proposal: (
                -proposal.priority, -proposal.parameters.get("confidence", 0), proposal.key))
        domain = str(getattr(goal, "domain", "") or "")
        if domain in {"QUEST", "COMBAT", "GATHER"}:
            world3d, other, seen_groups = [], [], set()
            for proposal in ordered:
                if proposal.parameters.get("source") != "WORLD3D":
                    other.append(proposal)
                    continue
                group_key = (proposal.parameters.get("visual_group_id")
                             or proposal.parameters.get("track_id") or proposal.key)
                if group_key in seen_groups:
                    continue
                seen_groups.add(group_key)
                if len(world3d) < 3:
                    world3d.append(proposal)
            ordered = sorted(
                [*world3d, *other],
                key=lambda proposal: (
                    -proposal.priority, -proposal.parameters.get("confidence", 0), proposal.key))
        return ordered
