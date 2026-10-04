"""Quest-domain proposal policy composed by the single high-level Planner.

This module has no input, movement, runtime-finalization or WorldModel write
authority.  It only projects quest evidence into candidate Proposal objects.
"""
from __future__ import annotations

import time

from .interaction_range import recently_verified_in_range

import math

from .collect_strategy import CollectStrategy, CollectStrategyTracker
from .credit_failure_escalation import CreditFailureAction, CreditFailureEscalation
from .models import Goal, Proposal, number, words
from .planning_types import world_point
from .world import WorldModel
from .quest_semantics import (combat_subjects, target_matches_objective,
                              target_matches_structured_entity, use_on_subjects,
                              subject_matches_name, world_object_subjects)
from .quest_batch_planning import QuestBatchPolicy
from .quest_dialog_planning import QuestDialogPlanningPolicy
from .quest_location_planning import QuestLocationPlanningPolicy
from .target_planning import (TARGET_HANDOFF_MAX_SAMPLE_AGE_SECONDS,
                              TargetPlanningPolicy, interaction_out_of_range,
                              is_player_unit)


class QuestDomain:
    def __init__(self, attempt_memory=None):
        # A client-confirmed range error opens one persistent REACH_OBJECT
        # requirement. The Movement Skill owns it until world-space arrival.
        self.interaction_range_blocks: dict[str, dict] = {}
        self.failed_map_locations = set()
        self.used_spawn_fallbacks = set()
        self.reference_arrivals = set()
        self.allow_db_fallback = False
        # Ground-truth identity comes from addon mouseover.  The cursor point
        # is only a short-lived visual anchor for steering toward that same
        # identity; it is not an NPC classification or a world coordinate.
        self.confirmed_mouseover_anchors: dict[str, dict] = {}
        # guid -> quest_signature at the moment INTERACT/TALK/QUEST_DIALOG last
        # succeeded against it. Gates the generic friendly-target INTERACT
        # proposal below so an already-handled quest giver (nothing new to
        # accept/turn in) is not re-approached forever; a changed signature
        # (new accept, objective completed) clears the gate again.
        self.interacted_guids: dict[str, str] = {}
        self.interacted_at: dict[str, float] = {}
        # guid -> (quest_signature, addon time) of a friendly INTERACT that got
        # no response at all.  Live 2026-09-30: with no quest yet, Kee-La (no
        # quest marker, nothing to offer) was hovered, targeted and interacted
        # with three times in 26 s because only *successful* interactions
        # were gated.  Bounded and signature-scoped like interacted_guids.
        self.unresponsive_guids: dict[str, tuple[str, float | None]] = {}
        # GUID -> time a "!"-less NPC answered INTERACT with nothing while no
        # quest was active (user 2026-10-02: skip such NPCs for a while).
        self.not_quest_giver_at: dict[str, float] = {}
        # guid -> addon time of the last Retail "need to be closer" error for
        # it.  A later silent INTERACT against that NPC is a range problem,
        # not proof that it has nothing to offer.
        self.out_of_range_at: dict[str, float | None] = {}
        self.item_range_blocks: dict[str, float | None] = {}
        # A successful visual approach to this GUID (INTERACTION_READY) is the
        # only interaction-range evidence Retail gives us for NPCs.
        self.approach_verified_at: dict[str, float] = {}
        # Per-GUID interaction-sized box height, raised whenever the client
        # still answers "too far" at the current size (camera zoom and model
        # size make one global threshold wrong; live 2026-09-30 Jaina).
        self.interaction_ready_height: dict[str, float] = {}
        # GUID -> World3D track the approach last followed for that unit.
        self.target_tracks: dict[str, str] = {}
        # A completed combat animation is not proof of quest credit.  Keep a
        # tiny, quest-signature-scoped hold after an otherwise successful
        # combat action so delayed addon quest telemetry can arrive.  If it
        # never arrives, suppress only that GUID/objective combination for a
        # bounded period.  This prevents repeatedly selecting a non-crediting
        # target while retaining other targets and self-defence.
        self.no_credit_targets: dict[tuple[str, tuple[str, ...], tuple[str, ...]], dict] = {}
        # V4-070: tiered escalation ladder, layered on top of the bounded
        # single-target suppression above. Recording is additive and does
        # not change record_uncredited_target's existing bool contract.
        from .quest_attempt_memory import QuestAttemptMemory
        self.attempt_memory = attempt_memory or QuestAttemptMemory()
        self.strategy_history = self.attempt_memory.strategy_history
        self.credit_escalation = CreditFailureEscalation(history=self.strategy_history)
        # V4-051: adaptive belief about *how* a COLLECT objective's source is
        # actually satisfied (ground object / mob loot / direct interact /
        # quest-item mechanic / scripted). Queried, not auto-applied -- a
        # caller decides what to do with the current best guess.
        self.collect_strategy = CollectStrategyTracker(history=self.strategy_history)
        self.location_policy = QuestLocationPlanningPolicy()
        # Compatibility views during the engine migration; the state itself is
        # owned only by QuestLocationPlanningPolicy.
        self.reached_quest_locations = self.location_policy.reached_quest_locations
        self.objective_locator = self.location_policy.objective_locator
        self.dialog_policy = QuestDialogPlanningPolicy()
        self.target_policy = TargetPlanningPolicy()
        self.batch_policy = QuestBatchPolicy()

    # 60 s breaks the observed 26 s re-interaction loop while bounding the cost
    # of a wrong verdict (live 09:12: a far-away quest giver was gated).
    UNRESPONSIVE_NPC_SECONDS = 60.
    # An unreachable selected friendly unit may hold the planner this long.
    SELECTED_TARGET_WAIT_SECONDS = 10.

    def recently_verified_in_range(self, guid, now: float | None) -> bool:
        return recently_verified_in_range(self, guid, now)

    # Live 2026-10-01 (Jaina, default zoom): the client still said "need to
    # be closer" at box heights .13 and .156; accepts succeeded at ~.186.
    VISUAL_INTERACTION_HEIGHT = .19

    TURN_IN_CANDIDATE_YARDS = 35.
    ITEM_RANGE_BLOCK_SECONDS = 20.

    def _item_target_approach(self, state: dict, target: dict, obj, record, qid, state_time):
        """Walk to a selected item-use target that answered "too far"."""
        guid = str(target.get("guid") or "")
        params = {"guid": guid, "objective_id": obj.objective_id,
                  "quest_ids": [record.quest_id if record else qid]}
        anchor = target.get("screen_position") or {}
        sample = number(anchor.get("sample_time"))
        if (number(anchor.get("x")) is not None and number(anchor.get("y")) is not None
                and sample is not None and state_time is not None
                and -5. <= state_time - sample < 30.):
            return Proposal.make(
                "VISUAL_APPROACH", "Quest item célpontja túl messze: képernyőn követett megközelítés",
                {**params, "purpose": "INTERACT", "track_id": anchor.get("track_id"),
                 "visual_signature": anchor.get("visual_signature"), "screen_position": anchor,
                 "ready_bbox_height": self.VISUAL_INTERACTION_HEIGHT},
                confidence=.8, priority=84)
        where = target.get("world_position") or {}
        if (where.get("coordinate_space") == "WORLD_YARDS"
                and number(where.get("x")) is not None and number(where.get("y")) is not None):
            # A minimap target marker estimate (user 2026-10-04) or API position.
            return Proposal.make(
                "MOVE", "Quest item célpontja túl messze: odamegyek a becsült helyére",
                {**params, "x": where["x"], "y": where["y"], "coordinate_space": "WORLD_YARDS",
                 "instance_id": where.get("instance_id"), "map_id": state.get("map_id"),
                 "purpose": "APPROACH_ITEM_TARGET", "stop_distance": 6.0, "require_navmesh": True},
                confidence=.7, priority=84)
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

    def recently_unresponsive(self, guid, state: dict, state_time: float | None) -> bool:
        entry = self.unresponsive_guids.get(str(guid or ""))
        if not entry or entry[0] != WorldModel.quest_signature(state):
            return False
        return entry[1] is None or state_time is None or state_time-entry[1] < self.UNRESPONSIVE_NPC_SECONDS

    def unresponsive_guid_set(self, state: dict, state_time: float | None) -> frozenset[str]:
        skipped = {guid for guid in self.unresponsive_guids
                   if self.recently_unresponsive(guid, state, state_time)}
        if not state.get("active_quests") and state_time is not None:
            from .quest_giver_evidence import NOT_QUEST_GIVER_SECONDS
            skipped.update(guid for guid, at in self.__dict__.get("not_quest_giver_at", {}).items()
                           if 0 <= state_time-at <= NOT_QUEST_GIVER_SECONDS)
        return frozenset(skipped)

    @staticmethod
    def _friendly_target_relevant(world, goal, target: dict) -> bool:
        """Approach/talk to a selected friendly unit only when questing needs it."""
        from .quest_giver_evidence import friendly_npc_relevant, is_companion_pet
        if is_companion_pet(target):
            return False
        if getattr(goal, "domain", None) != "QUEST":
            return True
        state = world.state
        if not state.get("active_quests"):
            return True   # discovery keeps its own "!"-based selection rule
        from .quest_giver_evidence import npc_objective_subjects
        ready = world.quest_model.ready()
        types = {str(getattr(obj, "type", "") or "") for obj in ready}
        return friendly_npc_relevant(state, str(target.get("guid") or ""), types,
                                     unit_name=target.get("name"),
                                     npc_subjects=npc_objective_subjects(ready))

    @staticmethod
    def _quest_location_key(location: dict) -> tuple:
        return QuestLocationPlanningPolicy.location_key(location)

    def mark_location_reached(self, location: dict, state: dict) -> None:
        self.location_policy.mark_reached(location, state)

    @staticmethod
    def _credit_target_key(guid, quest_ids, objective_ids) -> tuple[str, tuple[str, ...], tuple[str, ...]] | None:
        guid = str(guid or "")
        objectives = tuple(sorted({str(value) for value in objective_ids if value is not None}))
        if not guid or not objectives:
            return None
        quests = tuple(sorted({str(value) for value in quest_ids if value is not None}))
        return guid, quests, objectives

    def record_uncredited_target(self, guid, quest_ids, objective_ids, state: dict, now: float) -> bool:
        """Begin a short credit-observation window for one killed target.

        The method deliberately does not mark the target rejected yet: the
        retail export can lag behind the visual death/combat result.  A future
        planner tick either observes a changed quest signature (and deletes
        the record) or turns it into a bounded suppression.
        """
        key = self._credit_target_key(guid, quest_ids, objective_ids)
        if key is None:
            return False
        self.no_credit_targets[key] = {
            "quest_signature": WorldModel.quest_signature(state),
            "await_until": now + 2.0,
            "suppress_until": now + 45.0,
        }
        # V4-070: feed the tiered escalation ladder. This is additive
        # bookkeeping only -- it does not change this method's bool result.
        _, quests, objectives = key
        for quest_id in (quests or ("",)):
            for objective_id in objectives:
                self.credit_escalation.record_no_credit(
                    quest_id, objective_id, candidate=str(guid or ""), strategy="COMBAT")
        return True

    def credit_escalation_action(self, quest_id, objective_id) -> CreditFailureAction:
        """Query-only: current V4-070 tier for this objective's no-credit history."""
        return self.credit_escalation.current_action(quest_id, objective_id)

    def credit_gate(self, guid, quest_ids, objective_ids, state: dict, now: float) -> str | None:
        """Return a non-semantic gate reason for an uncredited target.

        A quest-state change is authoritative evidence that the old record is
        stale, so it invalidates the memory immediately.  No identity is
        inferred here; this is only action-selection memory.
        """
        key = self._credit_target_key(guid, quest_ids, objective_ids)
        if key is None:
            return None
        entry = self.no_credit_targets.get(key)
        if entry is None:
            return None
        if entry.get("quest_signature") != WorldModel.quest_signature(state):
            del self.no_credit_targets[key]
            return None
        if now < entry["await_until"]:
            return "AWAITING_QUEST_CREDIT"
        if now < entry["suppress_until"]:
            return "NO_QUEST_CREDIT"
        del self.no_credit_targets[key]
        return None

    def apply_collect_strategy(self, proposals: list[Proposal], world: WorldModel) -> list[Proposal]:
        """Bias existing COLLECT proposals from learned quest-credit evidence.

        UNKNOWN preserves the original proposal. A learned strategy only adds
        a bounded priority bonus; it never fabricates or suppresses candidates.
        """
        collect_objectives = {
            str(obj.objective_id): str(record.quest_id)
            for record in world.quest_model.records.values()
            for obj in record.objectives
            if obj.type == "COLLECT" and obj.completion_state != "COMPLETE"
        }
        if not collect_objectives:
            return proposals
        guided: list[Proposal] = []
        for proposal in proposals:
            params = proposal.parameters
            objective_ids = params.get("objective_ids") or (
                [params.get("objective_id")] if params.get("objective_id") is not None else [])
            best = None
            for objective_id in objective_ids:
                quest_id = collect_objectives.get(str(objective_id))
                if quest_id is None:
                    continue
                strategy, confidence, adjustment = self.collect_strategy.guidance(
                    quest_id, objective_id, proposal.skill)
                if adjustment > 0 and (best is None or adjustment > best[2]):
                    best = (strategy, confidence, adjustment, quest_id, str(objective_id))
            if best is None:
                guided.append(proposal)
                continue
            strategy, confidence, adjustment, quest_id, objective_id = best
            guided.append(Proposal.make(
                proposal.skill,
                proposal.reason + f"; tanult COLLECT-forrás: {strategy.value}",
                {**params, "collect_strategy_guidance": {
                    "strategy": strategy.value, "confidence": confidence,
                    "quest_id": quest_id, "objective_id": objective_id,
                    "priority_adjustment": adjustment}},
                proposal.confidence, proposal.priority + adjustment,
                proposal.evidence))
        return guided

    # Campaign first (user 2026-10-03, option B + C).
    CAMPAIGN_PRIORITY_BONUS = 4.
    SIDE_QUEST_DETOUR_YARDS = 120.

    def propose(
        self, world: WorldModel, goal: Goal,
        *, runtime_map_scan_started: float | None = None,
    ) -> list[Proposal]:
        proposals = self._propose(world, goal, runtime_map_scan_started=runtime_map_scan_started)
        return self.prefer_campaign(proposals, world.state)

    @classmethod
    def prefer_campaign(cls, proposals: list[Proposal], state: dict) -> list[Proposal]:
        """Campaign quest work first; far side-quest trips wait for the campaign."""
        quests = [quest for quest in state.get("active_quests") or () if isinstance(quest, dict)]
        campaign = {str(quest.get("quest_id")) for quest in quests if quest.get("is_campaign") is True}
        if not campaign:
            return proposals
        campaign_open = any(quest.get("is_campaign") is True and quest.get("is_complete") is not True
                            for quest in quests)
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        result = []
        for proposal in proposals:
            params = proposal.parameters
            ids = {str(value) for value in (params.get("quest_ids") or ()) if value is not None}
            if params.get("quest_id") is not None:
                ids.add(str(params["quest_id"]))
            if ids & campaign:
                result.append(Proposal.make(
                    proposal.skill, proposal.reason, params, proposal.confidence,
                    proposal.priority + cls.CAMPAIGN_PRIORITY_BONUS, proposal.evidence))
                continue
            far_side_trip = False
            if (ids and campaign_open and proposal.skill == "MOVE"
                    and params.get("purpose") in {"LOCATE_QUEST_OBJECTIVE_REGION",
                                                  "LOCATE_TURN_IN_REGION"}
                    and params.get("coordinate_space") == "WORLD_YARDS"
                    and None not in (px, py, number(params.get("x")), number(params.get("y")))):
                far_side_trip = (math.hypot(float(params["x"])-px, float(params["y"])-py)
                                 > cls.SIDE_QUEST_DETOUR_YARDS)
            if not far_side_trip:
                result.append(proposal)
        return result

    def _propose(
        self, world: WorldModel, goal: Goal,
        *, runtime_map_scan_started: float | None = None,
    ) -> list[Proposal]:
        state = world.state
        result = []
        # WorldModel owns scene validity. Never retain a screen point that it
        # expired after movement or a view change.
        self.confirmed_mouseover_anchors = dict(state.get("confirmed_mouseover_anchors") or {})
        state_time = number(state.get("monotonic_time"))
        mouseover = state.get("mouseover") or {}
        cursor = state.get("cursor_position") or {}
        map_surface = (state.get("map_mouseover") or {}).get("surface")
        mouse_guid = str(mouseover.get("guid") or "")
        cursor_x, cursor_y = number(cursor.get("nx")), number(cursor.get("ny"))
        mouse_time = number(state.get("mouseover_sample_time", state_time))
        cursor_time = number(state.get("cursor_sample_time", state_time))
        cursor_matches_mouseover = (None not in (state_time, mouse_time, cursor_time)
                                    and 0 <= state_time-mouse_time <= TARGET_HANDOFF_MAX_SAMPLE_AGE_SECONDS
                                    and 0 <= state_time-cursor_time <= TARGET_HANDOFF_MAX_SAMPLE_AGE_SECONDS
                                    and abs(mouse_time-cursor_time) <= .05)
        if state_time is not None:
            self.confirmed_mouseover_anchors = {
                guid: anchor for guid, anchor in self.confirmed_mouseover_anchors.items()
                if state_time-(number(anchor.get("sample_time")) or -math.inf) < 30.
            }
        ui = state.get("quest_ui") or {}
        primary_context = world.runtime_context.get("primary_quest") or {}
        primary_quest_id = str(primary_context.get("quest_id") or "")
        primary_objective_id = str(primary_context.get("objective_id") or "")
        result.extend(self.dialog_policy.propose(state, goal, primary_quest_id=primary_quest_id))
        batch_policy = self.__dict__.setdefault("batch_policy", QuestBatchPolicy())
        deferred_turnins = batch_policy.deferred_turnins(state, state_time)
        quest_areas = getattr(self.location_policy, "quest_areas", None)
        if quest_areas is not None:
            quest_areas.observe(state)
        records = world.quest_model.records
        if primary_quest_id:
            records = {quest_id: record for quest_id, record in records.items()
                       if str(quest_id) == primary_quest_id}
        # Retail's Extra Action button is a quest tool, not a generic hotkey.
        # Admit it only when the addon exposes its exact action identity. The
        # automatic path is deliberately narrow: an item-type action must
        # equal the active quest's API-reported special item. Other action
        # types need an explicit goal policy with the exact exported identity.
        extra_action = state.get("extra_action") or {}
        goal_parameters = getattr(goal, "parameters", {}) or {}
        for record in records.values():
            special_item = (record.raw.get("special_item") or {}).get("item_id")
            observed_type = str(extra_action.get("action_type") or "").lower()
            observed_id = extra_action.get("action_id")
            explicit_match = (
                goal_parameters.get("allow_extra_action") is True
                and str(goal_parameters.get("extra_action_type") or "").lower() == observed_type
                and goal_parameters.get("extra_action_id") is not None
                and str(goal_parameters.get("extra_action_id")) == str(observed_id)
            )
            special_item_match = (
                observed_type == "item" and special_item is not None
                and str(special_item) == str(observed_id)
            )
            if (extra_action.get("visible") is not True or extra_action.get("usable") is not True
                    or str(extra_action.get("action") or "").upper() != "EXTRAACTIONBUTTON1"
                    or not (explicit_match or special_item_match)):
                continue
            for obj in record.objectives:
                if obj.type != "USE_OBJECT" or obj.completion_state == "COMPLETE":
                    continue
                readiness = world.quest_model.readiness().get(obj.objective_id, {})
                if readiness.get("status") != "READY":
                    continue
                result.append(Proposal.make(
                    "EXTRA_ACTION", "Addon által azonosított, questhez kötött Extra Action eszköz",
                    {"extra_action_type": observed_type, "extra_action_id": observed_id,
                     "quest_ids": [record.quest_id], "objective_ids": [obj.objective_id],
                     "authorization": ("EXACT_ACTIVE_QUEST_SPECIAL_ITEM" if special_item_match
                                       else "EXPLICIT_GOAL_EXACT_ACTION")},
                    confidence=.98, priority=78,
                ))
        result.extend(self.location_policy.propose_turnins(
            records, state, primary_context, deferred=deferred_turnins))
        for obj in world.quest_model.ready():
            qid = obj.objective_id.split(":", 1)[0]
            if primary_quest_id and qid != primary_quest_id:
                continue
            if primary_objective_id and obj.objective_id != primary_objective_id:
                continue
            record = next((value for value in records.values() if str(value.quest_id) == qid), None)
            location_proposals = self.location_policy.propose_objective(world, obj, record, qid)
            result.extend(location_proposals)
            if obj.type in {"WAIT", "DEFEND"}:
                # Travel only when a concrete location is already known.
                # Missing/ambiguous markers must not turn a defend/wait event
                # into free-roaming SEARCH/INSPECT behavior.
                concrete_route = any(item.skill in {
                    "MOVE", "REACH_LOCATION", "REACH_OBJECT"
                } for item in location_proposals)
                if not concrete_route:
                    result.append(Proposal.make(
                        "WAIT_EVENT",
                        "Helyben maradó, bounded quest-esemény figyelés",
                        {"quest_ids": [record.quest_id if record else qid],
                         "objective_ids": [obj.objective_id],
                         "objective_kind": obj.type},
                        confidence=obj.confidence, priority=76,
                        evidence=("defend_wait_objective", "no_concrete_route")))
                    continue
            target = world.query.target()
            item_id = (obj.target_object or {}).get("item_id")
            subjects = use_on_subjects({**obj.raw, "description": obj.description}) if item_id is not None else []
            selected_item_target = bool(
                subjects and target and target.get("name")
                and subject_matches_name(subjects, target.get("name"))
                and not target.get("dead", target.get("is_dead")))
            if (any(proposal.skill == "SEEK_VISUAL_CUE" for proposal in location_proposals)
                    and not selected_item_target):
                # Live 2026-10-04 10:50: the local search SEEK also skipped
                # the item use on an already selected Wandering Boar.
                continue
            action = next((item for item in state.get("actionbar", [])
                           if item.get("kind") == "item" and str(item.get("id")) == str(item_id)
                           and item.get("is_usable") is True), None)
            inventory_item = next((item for item in (state.get("inventory") or {}).get("items", [])
                                   if str(item.get("item_id")) == str(item_id)
                                   and item.get("is_locked") is not True), None)
            activation = None
            if action:
                activation = {"binding": action.get("action"), "activation_source": "ACTIONBAR"}
            elif (state.get("bags_open") is True and inventory_item
                  and inventory_item.get("coordinate_space") == "CLIENT_BOTTOM_LEFT"
                  and number(inventory_item.get("x")) is not None
                  and number(inventory_item.get("y")) is not None):
                activation = {
                    "activation_source": "INVENTORY_COORDINATE",
                    "bag": inventory_item.get("bag"), "slot": inventory_item.get("slot"),
                    "x": inventory_item.get("x"), "y": inventory_item.get("y"),
                    "coordinate_space": "CLIENT_BOTTOM_LEFT",
                }
            elif inventory_item and selected_item_target and any(
                    str((quest.get("special_item") or {}).get("item_id")) == str(item_id)
                    for quest in state.get("active_quests") or ()):
                # Live 2026-10-04 10:44: the Re-Sizer credit came from the
                # Interact key on the selected boar -- Retail's interact uses
                # an active quest's special item on its objective target.
                activation = {"binding": "INTERACTTARGET", "activation_source": "INTERACT_KEY"}
            guid = str(target.get("guid") or "") if target else ""
            last_result = (world.runtime_context.get("last_result") or {}) if hasattr(world, "runtime_context") else {}
            from wowbot.verification.interaction import classify_ui_error
            item_position_failure = (
                last_result.get("skill") == "USE_ON_TARGET"
                and any(token in str(last_result.get("reason") or "").casefold()
                        for token in ("range", "facing", "line_of_sight", "sight")))
            ui_position_error = classify_ui_error(state.get("ui_error"), state.get("ui_error_code"))
            if (guid in self.item_range_blocks and last_result.get("outcome") == "SUCCESS"
                    and last_result.get("skill") in {"VISUAL_APPROACH", "MOVE"}):
                self.item_range_blocks.pop(guid, None)     # approached: try the item again
            elif selected_item_target and guid and (ui_position_error or item_position_failure):
                # Too far, not in line of sight, or behind us (user): approach,
                # which also turns toward the target.
                self.item_range_blocks[guid] = state_time
            range_blocked = (selected_item_target and guid in self.item_range_blocks
                             and state_time is not None
                             and state_time - float(self.item_range_blocks[guid] or 0.) <= self.ITEM_RANGE_BLOCK_SECONDS)
            if range_blocked:
                approach = self._item_target_approach(state, target, obj, record, qid, state_time)
                if approach is not None:
                    result.append(approach)
                    continue
            target_matches_item_use = bool(
                subjects and target and target.get("name")
                and subject_matches_name(subjects, target.get("name"))
                and not target.get("dead", target.get("is_dead")))
            if (target_matches_item_use and not action and inventory_item
                    and state.get("bags_open") is not True):
                result.append(Proposal.make(
                    "OPEN_BAGS", "Quest special item pontos bag-slotjának megnyitása",
                    {"purpose": "QUEST_ITEM", "item_id": item_id,
                     "objective_id": obj.objective_id,
                     "quest_ids": [record.quest_id if record else qid]},
                    confidence=obj.confidence, priority=81,
                    evidence=("exact_active_quest_item", "inventory_item_present")))
            if (subjects and target and target.get("name")
                    and subject_matches_name(subjects, target.get("name"))
                    and target.get("attackable", target.get("is_attackable")) is False
                    and not target.get("dead", target.get("is_dead"))):
                if activation:
                    result.append(Proposal.make(
                        "ASSIST", "Névvel azonosított barátságos target: quest item használata",
                        {"guid": target.get("guid"), "item_id": item_id,
                         **activation, "objective_id": obj.objective_id,
                         "quest_ids": [record.quest_id if record else qid]},
                        confidence=obj.confidence, priority=78))
            elif (subjects and target and target.get("name")
                    and subject_matches_name(subjects, target.get("name"))
                    and not target.get("dead", target.get("is_dead"))):
                if activation:
                    result.append(Proposal.make(
                        "USE_ON_TARGET", "Quest item használata névvel egyező, élő targeten",
                        {"guid": target.get("guid"), "item_id": item_id,
                         **activation, "objective_id": obj.objective_id,
                         "quest_ids": [record.quest_id if record else qid]},
                        confidence=obj.confidence, priority=80))
            mouse = state.get("mouseover") or {}
            if (subjects and mouse.get("guid") and mouse.get("guid") != target.get("guid")
                    and subject_matches_name(subjects, mouse.get("name"))):
                cursor = state.get("cursor_position") or {}
                if number(cursor.get("nx")) is not None and number(cursor.get("ny")) is not None:
                    result.append(Proposal.make(
                        "TARGET", "Quest item névvel egyező mouseover targetjének kijelölése",
                        {"x": cursor["nx"], "y": cursor["ny"], "guid": mouse["guid"],
                         "objective_id": obj.objective_id},
                        confidence=obj.confidence, priority=79))
            vendor = state.get("vendor_ui") or {}
            if obj.type == "BUY" and vendor.get("open") is True:
                money = number(state.get("money"))
                candidates = [item for item in vendor.get("items", [])
                              if item.get("is_purchasable") is True
                              and number(item.get("x")) is not None and number(item.get("y")) is not None
                              and number(item.get("price")) is not None
                              and money is not None and item["price"] <= money]
                if candidates:
                    item = min(candidates, key=lambda value: (value.get("price", 0), value.get("slot", 0)))
                    result.append(Proposal.make(
                        "BUY_VENDOR", "Aktív quest vásárlási célja: legolcsóbb megvehető vendor-item",
                        {"x": item["x"], "y": item["y"], "slot": item.get("slot"),
                         "item_id": item.get("item_id"), "price": item.get("price"),
                         "objective_id": obj.objective_id,
                         "quest_ids": [record.quest_id if record else qid]},
                        confidence=obj.confidence, priority=82))
            if obj.type == "SELL" and vendor.get("open") is True:
                if state.get("bags_open") is not True:
                    result.append(Proposal.make(
                        "OPEN_BAGS", "Aktív quest eladási céljához meg kell nyitni a táskákat",
                        {"objective_id": obj.objective_id}, confidence=obj.confidence, priority=83))
                else:
                    sellable = [item for item in (state.get("inventory") or {}).get("items", [])
                                if item.get("is_quest_item") is not True and item.get("is_locked") is not True
                                and item.get("is_equippable") is not True
                                and (number(item.get("sell_price")) or 0) > 0
                                and number(item.get("x")) is not None and number(item.get("y")) is not None]
                    if sellable:
                        item = min(sellable, key=lambda value: (value.get("quality", 99), value.get("sell_price", 0)))
                        result.append(Proposal.make(
                            "SELL_VENDOR", "Aktív quest eladási célja: nem quest- és nem felszerelhető bag item",
                            {"x": item["x"], "y": item["y"], "bag": item.get("bag"),
                             "slot": item.get("slot"), "item_id": item.get("item_id"),
                             "count": item.get("count"), "objective_id": obj.objective_id,
                             "quest_ids": [record.quest_id if record else qid]},
                            confidence=obj.confidence, priority=82))
            if (obj.type in {"BUY", "SELL"} and vendor.get("open") is not True
                    and target_matches_structured_entity(target, obj.target_entity)
                    and target.get("attackable", target.get("is_attackable")) is False):
                # The named vendor is selected: interacting opens its shop.
                result.append(Proposal.make(
                    "INTERACT", "Quest vásárlás/eladás: a névvel azonosított vendor megnyitása",
                    {"guid": target.get("guid"), "purpose": "OPEN_VENDOR",
                     "objective_id": obj.objective_id,
                     "quest_id": record.quest_id if record else qid},
                    confidence=obj.confidence, priority=74))
            if obj.type in {"TALK_TO", "INTERACT_NPC", "INTERACT"} and target_matches_structured_entity(target, obj.target_entity):
                if target.get("attackable", target.get("is_attackable")) is False:
                    vehicle = (str(target.get("guid") or "").startswith("Vehicle-")
                               or (obj.target_entity or {}).get("source") == "OBJECTIVE_TEXT")
                    # A vehicle NPC (Scout-o-Matic 5000) seats the player and
                    # opens no dialog: INTERACT's verifier accepts the seat.
                    result.append(Proposal.make("TALK" if obj.type in {"TALK_TO", "INTERACT_NPC"} and not vehicle
                                                else "INTERACT",
                                                "Strukturált quest target explicit identity egyezés",
                                                {"guid": target.get("guid"), "objective_id": obj.objective_id,
                                                 "quest_id": record.quest_id if record else qid},
                                                confidence=obj.confidence, priority=72))
            from .tooltip_quest import effective_mouseover
            mouse = effective_mouseover(state)
            expected_object = obj.target_object or {}
            object_identity = self.location_policy.object_interaction.expected_identity(obj)
            object_match = self.location_policy.object_interaction.mouseover_matches(
                object_identity, mouse)
            cursor = state.get("cursor_position") or {}
            if obj.type in {"USE_OBJECT", "INTERACT"} and object_match and all(number(cursor.get(k)) is not None for k in ("nx", "ny")):
                result.append(Proposal.make("OBJECT_USE", "Strukturált quest object és addon mouseover egyezés",
                                            {"x": cursor["nx"], "y": cursor["ny"],
                                             "object_id": expected_object.get("object_id"),
                                             "item_id": expected_object.get("item_id"),
                                             "mouseover_tooltip": mouse.get("tooltip"),
                                             "objective_id": obj.objective_id,
                                             "quest_ids": [record.quest_id if record else qid]},
                                            confidence=obj.confidence, priority=75))
        result.extend(self.location_policy.propose_known_locations(
            world, runtime_map_scan_started, deferred=deferred_turnins))
        target = world.query.target()
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
                result.append(Proposal.make(
                    "REACH_OBJECT", "A commitolt interakciós objektum elérése világkoordinátán",
                    {"target_guid": target.get("guid"), "guid": target.get("guid"),
                     "purpose": "INTERACT", "coordinate_space": "WORLD_YARDS",
                     "x": tx, "y": ty, "z": number(target_position.get("z")) or 0.,
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
                if (self._turn_in_candidate(state, target)
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
        result.extend(self.target_policy.propose(
            world, goal, target=target,
            cursor_matches_mouseover=cursor_matches_mouseover,
            state_time=state_time, mouse_time=mouse_time,
            skip_friendly_guids=self.unresponsive_guid_set(state, state_time),
        ))
        # Do not use TARGETNEARESTENEMY as an exploration/search primitive.
        # TAB can select an off-screen or quest-irrelevant unit and provides
        # identity without a usable screen/world location.  Quest targets are
        # acquired through World3D/hover evidence; ACQUIRE_TARGET remains an
        # in-combat defensive fallback in CombatPlanningPolicy only.
        return result
