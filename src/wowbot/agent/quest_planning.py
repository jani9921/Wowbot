"""Quest-domain proposal policy composed by the single high-level Planner.

This module has no input, movement, runtime-finalization or WorldModel write
authority.  It only projects quest evidence into candidate Proposal objects.
"""
from __future__ import annotations

import math

from .interaction_range import recently_verified_in_range
from .collect_strategy import CollectStrategyTracker
from .credit_failure_escalation import CreditFailureAction, CreditFailureEscalation
from .models import Goal, Proposal, number
from .world import WorldModel
from .quest_batch_planning import QuestBatchPolicy
from .quest_dialog_planning import QuestDialogPlanningPolicy
from .quest_location_planning import QuestLocationPlanningPolicy
from .target_planning import TARGET_HANDOFF_MAX_SAMPLE_AGE_SECONDS, TargetPlanningPolicy
from .quest_objective_planning import QuestObjectivePlanningMixin
from .quest_target_planning import QuestSelectedTargetMixin


class QuestDomain(QuestSelectedTargetMixin, QuestObjectivePlanningMixin):
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
    TURN_IN_RANGE_RETRY_SECONDS = 20.

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

    # A friendly unit talked to this recently, with an empty quest log and no
    # "!" over it, has nothing left for us (see _friendly_target_relevant).
    HANDLED_TARGET_RELEASE_SECONDS = 300.

    def _friendly_target_relevant(self, world, goal, target: dict) -> bool:
        """Approach/talk to a selected friendly unit only when questing needs it."""
        from .quest_giver_evidence import (friendly_npc_relevant, is_companion_pet,
                                           selected_npc_shows_quest_symbol)
        if is_companion_pet(target):
            return False
        if getattr(goal, "domain", None) != "QUEST":
            return True
        state = world.state
        if not state.get("active_quests"):
            # Discovery keeps its own "!"-based selection rule, but a unit we
            # already dealt with is released (live 2026-10-05 05:39, pid 1212):
            # Captain Garrick stayed selected after the turn-in, this branch
            # kept him "relevant" and ended planning before the mouseover
            # hand-off -- Private Cole ("!") and Henry Garrick were hovered
            # and left.  No CLEARTARGET binding exists in Retail 12.1 and a
            # blind Esc may open the game menu, so the release is logical:
            # the next TARGET replaces the selection.
            guid = str(target.get("guid") or "")
            handled_at = number(self.__dict__.get("interacted_at", {}).get(guid))
            now = number(state.get("monotonic_time"))
            handled = (handled_at is not None and now is not None
                       and 0 <= now-handled_at <= self.HANDLED_TARGET_RELEASE_SECONDS)
            # Live 2026-10-06 22:12: at Private Cole's "!" the client's soft-
            # interact unit was Cole while Lady Jaina (taken from a hover next
            # to him) stayed selected; her approach ended planning for a
            # minute.  Standing at an API giver, its soft-interact NPC goes
            # first (MapPoiPlanningPolicy._soft_interact_pickup).
            from .map_poi_planning import soft_interact_giver_waiting
            if soft_interact_giver_waiting(state, guid):
                return False
            return not handled or selected_npc_shows_quest_symbol(state, guid)
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
        shop_open = (state.get("vendor_ui") or {}).get("open") is True
        self._propose_objectives(world, state, state_time, records, primary_quest_id,
                                 primary_objective_id, shop_open, result)
        result.extend(self.location_policy.propose_known_locations(
            world, runtime_map_scan_started, deferred=deferred_turnins))
        target = world.query.target()
        selected = self._propose_selected_friendly(world, goal, state, state_time, target, result)
        if selected is not None:
            return selected
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

