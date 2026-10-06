"""QuestDomain handling of a selected friendly unit: interact, approach, range learning, turn-in.

Split out of quest_planning.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import time
from .interaction_range import recently_verified_in_range
import math
from .models import Goal, Proposal, number
from .planning_types import world_point
from .world import WorldModel
from .target_planning import interaction_out_of_range, is_player_unit


class QuestSelectedTargetMixin:
    """Methods of QuestDomain (quest_planning.py); moved verbatim."""

    def _propose_selected_friendly(self, world: WorldModel, goal: Goal, state: dict,
                                   state_time, target, result: list) -> list[Proposal] | None:
        """Proposals for a selected, relevant friendly unit (interact / approach / turn-in).

        Split out of _propose (2026-10-05); the block is unchanged.  A returned
        list ends planning with exactly that list (the former early returns);
        None continues with the target policy.
        """
        if (target and not is_player_unit(target, state)
                and target.get("attackable", target.get("is_attackable")) is False
                and self._friendly_target_relevant(world, goal, target)):
            guid = str(target.get("guid") or "")
            if guid in self.reference_arrivals:
                self.reference_arrivals.discard(guid)
                return [Proposal.make("INTERACT", "DB referenciahely elérve; tényleges interakció ellenőrzése",
                                      {"guid": guid}, priority=100)]
            mouse = state.get("mouseover") or {}
            # Tried narrowing this 2026-09-13 to only quest_role/fresh-mouseover,
            # meaning to stop the bot re-approaching irrelevant friendly NPCs --
            # but this condition also covers the FIRST interaction with whatever
            # is *currently targeted* (test_confirmed_friendly_target_is_interacted_with_before_opening_map
            # and friends rely on exactly that: try INTERACT before falling back
            # to OPEN_MAP for a target just selected, with no quest_role known
            # yet). Reverted; the actual "don't go back to an NPC with nothing
            # left to offer" fix is the interacted_guids gate below, which does
            # not touch this first-contact case at all.
            interaction_evidence = (mouse.get("guid") == target.get("guid")
                                    or target.get("quest_role") in {"QUEST_GIVER", "QUEST_TURN_IN"}
                                    or (target.get("npc_id") is not None
                                        and target.get("unit_type") == "NPC")
                                    or (target.get("npc_id") is not None
                                        and guid.startswith(("Creature-", "Vehicle-")))
                                    or bool(target.get("name")))
            if interaction_out_of_range(state) and guid:
                self.out_of_range_at[guid] = state_time
            if (interaction_out_of_range(state) and guid
                    and guid not in self.interaction_range_blocks):
                self.interaction_range_blocks[guid] = {
                    "started_at": state_time,
                    "observation_id": world.latest.observation_id if world.latest else None,
                }
            # Real-time World3D decides range for a selected friendly unit:
            # Retail exports no NPC distance and a far INTERACTTARGET is
            # often silent, so without visual proximity (or a verified
            # approach) walk there first instead of trying to interact
            # (user direction 2026-09-30).  Without active World3D vision the
            # former interact-first behaviour is kept.
            vision_active = any(isinstance(item, dict) and item.get("source") == "WORLD3D"
                                for item in state.get("visual_candidates") or ())
            range_verified = (recently_verified_in_range(self, guid, time.monotonic())
                              or self._target_visually_in_range(state, guid))
            if (guid and vision_active and interaction_evidence and not range_verified
                    and guid not in self.interaction_range_blocks):
                self.interaction_range_blocks[guid] = {
                    "started_at": state_time,
                    "observation_id": world.latest.observation_id if world.latest else None,
                    "belief": "CANDIDATE", "source": "WORLD3D_VISUAL_SCALE",
                }
            block = self.interaction_range_blocks.get(guid)
            player_position = state.get("player_world_position") or {}
            target_position = target.get("world_position") or {}
            px, py = number(player_position.get("x")), number(player_position.get("y"))
            tx, ty = number(target_position.get("x")), number(target_position.get("y"))
            same_instance = (player_position.get("instance_id") is None
                             or target_position.get("instance_id") is None
                             or player_position.get("instance_id") == target_position.get("instance_id"))
            distance = math.hypot(tx-px, ty-py) if None not in (px, py, tx, ty) and same_instance else None
            stop_distance = 4.5
            screen_anchor = target.get("screen_position") or self.confirmed_mouseover_anchors.get(guid)
            anchor_time = number((screen_anchor or {}).get("sample_time"))
            anchor_fresh = (isinstance(screen_anchor, dict)
                            and anchor_time is not None and state_time is not None
                            # World3D tracks can be newer than the addon clock.
                            and -5. <= state_time-anchor_time < 30.
                            and (screen_anchor.get("source") == "NAMEPLATE_API"
                                 or screen_anchor.get("source") in {
                                     "CONFIRMED_MOUSEOVER", "CONFIRMED_MOUSEOVER_ANCHOR",
                                     "BOUND_WORLD3D_TRACK"}))
            if not anchor_fresh and guid:
                # The mouseover anchor expires with movement/view change, but
                # the unit's live World3D track (bound to this GUID by the
                # approach that was following it) still shows where it is.
                # Live 2026-09-30: after an out_of_range the agent opened the
                # World Map while Jaina and her '!' were plainly on screen.
                live = self._target_live_track(state, guid, target)
                if live is not None:
                    screen_anchor = {
                        "x": live.get("x"), "y": live.get("y"),
                        "track_id": live.get("track_id"),
                        "visual_signature": live.get("visual_signature"),
                        "sample_time": state_time, "source": "WORLD3D_TARGET_TRACK"}
                    anchor_fresh = True
            fallback_proposal = None
            if self.allow_db_fallback and distance is None:
                from .location_fallback import reference_destination
                reference = reference_destination(state)
                fallback_key = (state.get("session_id"), guid,
                                reference.get("spawn_id") if reference else None)
                if reference and fallback_key not in self.used_spawn_fallbacks:
                    fallback_proposal = Proposal.make("REACH_OBJECT",
                        "3D és World Map keresés sikertelen: DB spawnhely fallback, helyszíni ellenőrzéssel",
                        {**reference, "target_guid": guid, "guid": guid,
                         "map_id": state.get("map_id"), "instance_id": reference["world_map_id"],
                         "purpose": "INSPECT_REFERENCE_LOCATION", "stop_distance": 4.5,
                        "fallback_key": fallback_key}, confidence=.6, priority=100)
            if block and state.get("world_map_open"):
                # Screen-space approach must never start behind the World Map:
                # the overlay invalidates the Track↔Entity visual association.
                # Closing it is a reversible UI precondition and retains the
                # exact target/GUID commitment.
                return [Proposal.make(
                    "CLOSE_MAP", "A commitolt 3D target megközelítése előtt a World Map bezárása",
                    {"guid": guid, "purpose": "RESTORE_WORLD3D_FOR_APPROACH"},
                    priority=110)]
            if block and distance is not None and distance > stop_distance:
                # Live 2026-10-06 21:54: Ralia's position had no height; the
                # former ``or 0.`` became a known z=0 and the route went back
                # down into Hrun's pit.  An unknown height is resolved by the
                # navigation (a selected, visible unit: our own floor first).
                target_z = number(target_position.get("z"))
                height = ({"z": target_z} if target_z is not None
                          and target_position.get("z_known") is not False
                          else {"z_known": False, "floor_hint": "SAME"})
                result.append(Proposal.make(
                    "REACH_OBJECT", "A commitolt interakciós objektum elérése világkoordinátán",
                    {"target_guid": target.get("guid"), "guid": target.get("guid"),
                     "purpose": "INTERACT", "coordinate_space": "WORLD_YARDS",
                     "x": tx, "y": ty, **height,
                     "instance_id": target_position.get("instance_id"),
                     "map_id": state.get("map_id"), "stop_distance": stop_distance,
                     "range_block_started_at": block.get("started_at")},
                    priority=100))
            elif block and distance is None and anchor_fresh:
                # The selected friendly unit has explicitly returned a range
                # error, while its identity and last 3D anchor are known.  Keep
                # the target commitment and approach it in screen space before
                # escalating to map search or database coordinates.
                result.append(Proposal.make(
                    "VISUAL_APPROACH",
                    "Mouseoverrel azonosított barátságos target 3D megközelítése",
                    {"guid": guid, "purpose": "INTERACT",
                     # Identity is supplied by addon mouseover; this is only
                     # the associated UNKNOWN visual track used as a live
                     # screen-space measurement by the movement skill.
                     "track_id": screen_anchor.get("track_id"),
                     "visual_signature": screen_anchor.get("visual_signature"),
                     "screen_position": screen_anchor,
                     "ready_bbox_height": self.ready_height(guid),
                     # Live 2026-10-04 (Wrathion, a dragon): a huge box "looked"
                     # in range from afar; after a client range error the
                     # approach must really advance before probing again.
                     "range_failures": (self.__dict__.get("interaction_range_failures") or {}).get(guid, 0),
                     **self._remember_target_track(guid, screen_anchor.get("track_id")),
                     "range_block_started_at": block.get("started_at")},
                    confidence=.8, priority=102))
                return result
            elif block and distance is None:
                map_moves = [p for p in result if p.skill == "MOVE"
                             and p.parameters.get("map_id") == state.get("map_id")
                             and p.key not in self.failed_map_locations]
                # Live 2026-10-05 05:41 (Westward Bound): at the turn-in point
                # (5 yd) Bjorn Stouthands stood farther off; this INTERACT was
                # sent four times in 11 s, each "out of range", with no move
                # in between.  The first call stays (live 2026-10-04 00:55,
                # Garrick); after a failed call relocate/approach the NPC
                # (search, hover, visual approach) before calling again.
                failed_at = (self.__dict__.get("interaction_range_failed_at") or {}).get(guid)
                recently_failed = (failed_at is not None and state_time is not None
                                   and 0 <= state_time-failed_at <= self.TURN_IN_RANGE_RETRY_SECONDS)
                if (self._turn_in_candidate(state, target)
                        and not recently_failed
                        and not self.recently_unresponsive(guid, state, state_time)):
                    # Live 2026-10-04 00:55: Captain Garrick (turn-in NPC of
                    # the completed quest) was selected next to the turn-in
                    # point, but the route MOVE (114) kept winning and the
                    # agent went on searching for "?" (user).  Talk to the
                    # selected unit; a range error hands INTERACT its own
                    # approach recovery, a wrong NPC opens no quest frame.
                    result.append(Proposal.make(
                        "INTERACT", "Kész quest leadási pontjánál kijelölt barátságos NPC megszólítása",
                        {"guid": guid, "purpose": "TURN_IN_CANDIDATE"}, priority=116))
                    return result
                if map_moves:
                    # Do not let the missing live NPC coordinate WAIT veto the map route.
                    return result
                if fallback_proposal:
                    result.append(fallback_proposal)
                    return result
                # Live 2026-10-01 18:15: after running past Jaina she was
                # selected but off-screen; REACH_OBJECT needs world XYZ and
                # VISUAL_APPROACH a fresh anchor, so the agent sat in WAIT.
                # Bring the selected unit back into view instead.
                commitment = world.runtime_context.get("commitment") or {}
                stale = screen_anchor if isinstance(screen_anchor, dict) else {}
                # Only a unit that was on screen and just got lost; a never
                # seen one keeps the World3D -> map -> DB discovery order.
                seen_before = (number(stale.get("x")) is not None
                               and number(stale.get("y")) is not None
                               and 0 < float(stale["x"]) < 1 and 0 < float(stale["y"]) < 1)
                if seen_before and str(commitment.get("target_guid") or "") == str(guid):
                    result.append(Proposal.make(
                        "REACQUIRE_TARGET",
                        "Kijelölt, de képen kívüli target visszahozása a képbe (utolsó ismert irány)",
                        {"guid": guid, "target_x": stale["x"], "target_y": stale["y"]},
                        confidence=.75, priority=92))
                elif (seen_before and not state.get("world_map_open")
                      and not state.get("is_in_combat")):
                    result.append(Proposal.make(
                        "SEEK_VISUAL_CUE",
                        "Kijelölt, de képen kívüli target keresése körbenézéssel",
                        {"source": "WORLD3D", "kind": "active_visual_search",
                         "purpose": "REACQUIRE_SELECTED_TARGET", "x": .5, "y": .45},
                        confidence=.7, priority=91))
                if not self.allow_db_fallback:
                    return result
                block_age = (state_time - float(block["started_at"])
                             if state_time is not None and number(block.get("started_at")) is not None
                             else None)
                if block_age is not None and block_age >= self.SELECTED_TARGET_WAIT_SECONDS:
                    # Live 2026-10-04 00:24: an out-of-range friendly target
                    # (Alaria, no world position, no fresh anchor) kept this
                    # WAIT as the only proposal, which hid the generic search
                    # fallbacks until the user cleared the target with Esc.
                    return result
                result.append(Proposal.make(
                    "WAIT", "A REACH_OBJECT nem indulhat bizonyított player/target világkoordináta nélkül",
                    {"guid": target.get("guid"), "missing": "WORLD_YARDS_POSITION",
                     # Live-observed 2026-09-12: this WAIT can persist for 20+
                     # seconds with no further fallback once the one-shot DB
                     # spawn fallback (fallback_proposal) has already been
                     # consumed via used_spawn_fallbacks for this guid, and
                     # anchor_fresh stays false the whole time -- deadlocked
                     # between REACH_OBJECT (needs distance) and VISUAL_APPROACH
                     # (needs a fresh screen anchor), with neither available.
                     # Diagnostics only, to confirm which side is actually
                     # missing before changing the fallback/retry logic.
                     "anchor_fresh": anchor_fresh,
                     "screen_anchor_present": screen_anchor is not None,
                     "screen_anchor_source": (screen_anchor or {}).get("source"),
                     # self.allow_db_fallback is guaranteed True here (the
                     # line above already returned if it weren't), and it's
                     # exactly fallback_proposal's own gating condition
                     # (line ~298), so fallback_key was always assigned.
                     "fallback_already_used": fallback_key in self.used_spawn_fallbacks},
                    # Low priority: without a fresh screen anchor the way out
                    # is visual (SEEK toward the symbol/subject group, hover to
                    # re-anchor the selected GUID).  At 100 this WAIT vetoed
                    # both indefinitely (live 2026-09-12, again 2026-09-30).
                    priority=20))
            elif fallback_proposal:
                result.append(fallback_proposal)
                return result
            elif block is not None:
                self.interaction_range_blocks.pop(guid, None)
                result.append(Proposal.make("INTERACT", "A REACH_OBJECT által elért barátságos egység interakciója", {"guid": target.get("guid")}, priority=70))
            handled_signature = self.interacted_guids.get(guid)
            handled_at = number(self.interacted_at.get(guid))
            # Detail-lane quest arrays can briefly disappear and reappear, so
            # a signature cycle alone must not clear this anti-loop gate. It
            # is nevertheless not a permanent NPC blacklist: in the second
            # PID 1468 run Jaina was selected again 146 seconds after the old
            # interaction, but the reused [] signature suppressed INTERACT
            # and let OPEN_MAP win. Bound the same-signature suppression while
            # retaining legacy entries without timestamps conservatively.
            handled_recently = (handled_at is None or state_time is None
                                or state_time-handled_at < 60.)
            already_handled = ((handled_signature == WorldModel.quest_signature(state)
                                and handled_recently)
                               or self.recently_unresponsive(guid, state, state_time))
            if (interaction_evidence and not already_handled
                    and (range_verified or not vision_active)):
                # Once INTERACT/TALK/QUEST_DIALOG already succeeded against
                # this guid at the current quest_signature, there is nothing
                # new here -- re-proposing this forever (this NPC still
                # legitimately carries quest_role=QUEST_GIVER) sent the bot
                # back to an already-accepted quest giver instead of the
                # actual objective. A changed signature (fresh accept,
                # objective completed) clears the gate again.
                result.append(Proposal.make("INTERACT", "A kijelölt barátságos egység interakciójának ellenőrzése", {"guid": target.get("guid")}, priority=70))
        return None

    def _turn_in_candidate(self, state: dict, target: dict) -> bool:
        """A selected friendly unit that is plausibly a completed quest's ender.

        Named by a completed quest's objective text, or selected while the
        player stands near a completed quest's API turn-in point.
        """
        if target.get("attackable", target.get("is_attackable")) is not False:
            return False
        completed = {str(quest.get("quest_id")): quest for quest in state.get("active_quests") or ()
                     if isinstance(quest, dict) and quest.get("is_complete") is True}
        if not completed:
            return False
        name = str(target.get("name") or "").strip().casefold()
        if name and any(name in str(objective.get("description") or "").casefold()
                        for quest in completed.values()
                        for objective in quest.get("objectives") or () if isinstance(objective, dict)):
            return True
        from .quest_turn_in import turn_in_names
        if name and any(name == turn_in.casefold() for turn_in in turn_in_names(state)):
            return True          # quest text / giver / LLM names this NPC as the ender
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if px is None or py is None:
            return False
        for location in state.get("quest_locations") or ():
            where = world_point(location) if isinstance(location, dict) else None
            if (where and str(location.get("quest_id")) in completed
                    and math.hypot(float(where["x"])-px, float(where["y"])-py) <= self.TURN_IN_CANDIDATE_YARDS):
                return True
        return False

    def ready_height(self, guid: str) -> float:
        return float(self.interaction_ready_height.get(str(guid or ""),
                                                        self.VISUAL_INTERACTION_HEIGHT))

    def learn_out_of_range(self, state: dict, guid: str) -> None:
        """Client says too far at the current visual size: require more."""
        guid = str(guid or "")
        if not guid:
            return
        self.approach_verified_at.pop(guid, None)
        height = self.target_visual_height(state, guid)
        required = self.ready_height(guid)
        # Grow at least 25 % per client range error so a few failures reach
        # real range (live: .13 -> .156 -> .213 took three failed INTERACTs).
        required = max(required*1.25, height*1.3 if height is not None else 0.)
        self.interaction_ready_height[guid] = min(.6, required)
        failures = self.__dict__.setdefault("interaction_range_failures", {})
        failures[guid] = failures.get(guid, 0)+1
        self.__dict__.setdefault("interaction_range_failed_at", {})[guid] = number(state.get("monotonic_time"))

    def _remember_target_track(self, guid: str, track_id) -> dict:
        if guid and track_id:
            self.target_tracks[str(guid)] = str(track_id)
        return {}

    def _target_live_track(self, state: dict, guid: str, target: dict) -> dict | None:
        """The selected unit's currently observed World3D track, if known."""
        anchor = (state.get("confirmed_mouseover_anchors") or {}).get(guid) or {}
        track_ids = {str(value) for value in (
            target.get("visual_track_id"), anchor.get("track_id"),
            self.target_tracks.get(str(guid))) if value}
        for item in state.get("visual_candidates") or ():
            if (isinstance(item, dict) and item.get("source") == "WORLD3D"
                    and str(item.get("track_id")) in track_ids
                    and str(item.get("lifecycle") or item.get("state") or "ACTIVE").upper()
                    in {"ACTIVE", "REACQUIRE_CANDIDATE", "TENTATIVE"}
                    and number(item.get("x")) is not None and number(item.get("y")) is not None):
                return item
        return None

    def target_visual_height(self, state: dict, guid: str) -> float | None:
        target = state.get("target") or {}
        anchor = (state.get("confirmed_mouseover_anchors") or {}).get(guid) or {}
        track_ids = {str(value) for value in (anchor.get("track_id"), target.get("visual_track_id"))
                     if value}
        for item in state.get("visual_candidates") or ():
            if (isinstance(item, dict) and str(item.get("track_id")) in track_ids
                    and str(item.get("lifecycle") or item.get("state") or "ACTIVE").upper()
                    not in {"LOST_TEMPORARY", "TERMINATED"}):
                height = number(item.get("bbox_height_fraction"))
                if height is not None:
                    return height
        return None

    def _target_visually_in_range(self, state: dict, guid: str) -> bool:
        """The selected unit's own live World3D box is interaction-sized.

        Same proxy the visual approach uses for INTERACTION_READY (box height
        >= 13 % of the view); the track is the one bound to the GUID by a
        confirmed mouseover anchor or the target association.
        """
        target = state.get("target") or {}
        anchor = (state.get("confirmed_mouseover_anchors") or {}).get(guid) or {}
        track_ids = {str(value) for value in (anchor.get("track_id"), target.get("visual_track_id"))
                     if value}
        if not track_ids:
            return False
        for item in state.get("visual_candidates") or ():
            if not isinstance(item, dict) or str(item.get("track_id")) not in track_ids:
                continue
            if str(item.get("lifecycle") or item.get("state") or "ACTIVE").upper() in {
                    "LOST_TEMPORARY", "TERMINATED"}:
                continue
            height = number(item.get("bbox_height_fraction"))
            if height is not None and height >= self.ready_height(guid):
                return True
        return False
