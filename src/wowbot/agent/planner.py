from __future__ import annotations

from .models import Goal, Proposal, number
from .world import WorldModel
from .planning_types import point
from .planning_domains import ResourceDomain, InventoryDomain, DungeonDomain, PvPDomain
from .active_perception import ActivePerception
from .combat_planning import CombatPlanningPolicy
from .quest_planning import QuestDomain
from .proposal_ranking import ProposalRanker
from .quest_failure_memory import QuestFailureMemory
from .visual_inspection_planning import VisualInspectionPolicy
from .visual_search_planning import VisualSearchPlanningPolicy
from .map_search_planning import WorldMapFallbackPolicy
from .decision_fingerprint import DecisionFingerprintGuard



class Planner:
    """One planner ranks proposals from all domains; no direct input calls."""

    def __init__(self, registry, memory=None, quest_attempt_memory=None):
        self.registry = registry
        self.memory = memory
        from .quest_attempt_memory import QuestAttemptMemory
        self.quest_attempt_memory = quest_attempt_memory or QuestAttemptMemory()
        self.quest = QuestDomain(self.quest_attempt_memory)
        self.combat_policy = CombatPlanningPolicy(registry)
        self.visual_inspection_policy = VisualInspectionPolicy()
        self.visual_search_policy = VisualSearchPlanningPolicy()
        self.proposal_ranker = ProposalRanker()
        self.resources = ResourceDomain(memory)
        self.dungeon = DungeonDomain()
        self.pvp = PvPDomain()
        self.inventory = InventoryDomain()
        self.blocked_until: dict[str, float] = {}
        self.recent: dict[str, float] = {}
        self.map_search_policy = WorldMapFallbackPolicy()
        self.camera_search_step = 0
        self.camera_search_next_at = 0.
        self.camera_search_position = None
        self.world3d_probe_count = 0
        self._visual_search_context = None
        self.active_perception = ActivePerception(memory)
        self.pattern_analysis = {"mode": "NO_REFERENCE", "novelty": None, "matches": []}
        self.last_scores = {}
        self.decision_fingerprints = DecisionFingerprintGuard()
        self._movement_visual_handoff: dict | None = None

    def reset_session(self) -> None:
        """Drop every session-local decision cache after identity changes.

        Proposal cooldowns, failed locations and camera/map scan progress are
        evidence about one character in one world session.  Carrying any of
        them into the next session can suppress valid actions or resume a
        half-finished search against unrelated state.
        """
        self.quest_attempt_memory.reset()
        self.quest = QuestDomain(self.quest_attempt_memory)
        self.blocked_until.clear()
        self.recent.clear()
        self.map_search_policy.reset_session()
        self.camera_search_step = 0
        self.camera_search_next_at = 0.
        self.camera_search_position = None
        self.world3d_probe_count = 0
        self._visual_search_context = None
        self.active_perception = ActivePerception(self.memory)
        self.pattern_analysis = {"mode": "NO_REFERENCE", "novelty": None, "matches": []}
        self.last_scores.clear()
        self.decision_fingerprints.reset()
        self._movement_visual_handoff = None

    def arm_movement_visual_handoff(self, handoff: dict, now: float) -> None:
        """Allow one exact World3D track to interrupt quest navigation.

        The latch is deliberately short lived.  It bridges the movement
        supervision boundary to the next Planner pass without turning every
        background UNKNOWN observation into a route-changing event.
        """
        track_id = handoff.get("track_id")
        if track_id is None:
            return
        self._movement_visual_handoff = {
            **dict(handoff), "track_id": str(track_id),
            "armed_at": float(now), "expires_at": float(now) + 1.5,
        }

    def _active_movement_visual_handoff(self, now: float) -> dict | None:
        handoff = self._movement_visual_handoff
        if handoff is not None and now <= float(handoff.get("expires_at") or 0.):
            return handoff
        self._movement_visual_handoff = None
        return None

    def record_terminal_decision(self, proposal: Proposal, goal: Goal | None,
                                 world: WorldModel, failure_decision, *,
                                 success: bool, now: float) -> None:
        """Update the evidence-gated anti-loop ledger after verification."""
        if success:
            self.decision_fingerprints.clear(proposal, goal)
        elif failure_decision is not None and not failure_decision.retry_allowed:
            self.decision_fingerprints.record_nonretryable(
                proposal, goal, world.state,
                reason=failure_decision.record.reason, now=now)

    def filter_decision_loops(self, proposals: list[Proposal], goal: Goal,
                              state: dict) -> list[Proposal]:
        return [proposal for proposal in proposals
                if self.decision_fingerprints.permits(proposal, goal, state)]

    def plan_horizon(self, proposal: Proposal, world: WorldModel) -> tuple[dict, ...]:
        """Build an inspectable generic horizon; only step zero may execute now."""
        params = proposal.parameters
        objective_id = params.get("objective_id")
        objective = next((item for record in world.quest_model.records.values()
                          for item in record.objectives if item.objective_id == objective_id), None)
        contract = self.registry.contracts[proposal.skill]
        steps = [{"order": 0, "phase": "EXECUTE", "capability": proposal.skill,
                  "status": "READY", "objective_id": objective_id,
                  "preconditions": list(contract.preconditions),
                  "expected_observation": contract.expected,
                  "fallback": contract.recovery, "confidence": proposal.confidence}]
        chains = {
            "KILL": (("ACQUIRE_TARGET", "attackable_target"),
                     ("APPROACH_TARGET", "target_in_range"),
                     ("COMBAT", "target_damage_or_death"), ("LOOT", "loot_or_objective_progress")),
            "COLLECT": (("INSPECT", "source_or_object_identification"),
                        ("GATHER_OR_COMBAT", "item_source_progress"),
                        ("LOOT", "inventory_or_objective_progress")),
            "TALK_TO": (("TARGET", "target_identity"), ("TALK", "dialog_opened")),
            "INTERACT": (("INSPECT", "object_or_entity_identity"), ("INTERACT", "interaction_effect")),
            "USE_OBJECT": (("INSPECT", "object_identity"), ("OBJECT_USE", "quest_object_credit")),
            "BUY": (("TALK", "vendor_open"), ("BUY_VENDOR", "purchase_or_objective_progress")),
            "SELL": (("TALK", "vendor_open"), ("OPEN_BAGS", "inventory_ui_open"),
                     ("SELL_VENDOR", "sale_or_objective_progress")),
            "TRAVEL_TO": (("MOVE", "arrival_region"),),
            "RETURN": (("MOVE", "turn_in_region"), ("TALK", "dialog_opened"),
                       ("QUEST_DIALOG", "quest_turned_in")),
        }
        for capability, expected in chains.get(getattr(objective, "type", None), ()):
            if capability == proposal.skill:
                continue
            steps.append({"order": len(steps), "phase": "FUTURE", "capability": capability,
                          "status": "BLOCKED_BY_PRIOR_STEP", "objective_id": objective_id,
                          "preconditions": ["prior_step_verified", "objective_still_active"],
                          "expected_observation": expected,
                          "fallback": "COLLECT_EVIDENCE_AND_REPLAN",
                          "confidence": min(proposal.confidence, getattr(objective, "confidence", 1.))})
        if objective_id:
            steps.append({"order": len(steps), "phase": "VERIFY", "capability": "VERIFY_OBJECTIVE",
                          "status": "BLOCKED_BY_PRIOR_STEP", "objective_id": objective_id,
                          "preconditions": ["fresh_quest_state"],
                          "expected_observation": "objective_progress_or_completion",
                          "fallback": "COLLECT_EVIDENCE_AND_REPLAN", "confidence": proposal.confidence})
        return tuple(steps)

    @staticmethod
    def plan_constraints(proposal: Proposal) -> tuple[str, ...]:
        values = ["SESSION_UNCHANGED", "TELEMETRY_FRESH", "NO_HIGHER_PRIORITY_SAFETY_EVENT"]
        if proposal.parameters.get("objective_id"):
            values.append("OBJECTIVE_STILL_ACTIVE")
        if proposal.parameters.get("guid"):
            values.append("TARGET_IDENTITY_MATCH")
        return tuple(values)

    def inspections(self, world, now, source=None, goal=None):
        return self.visual_inspection_policy.propose(
            world, now, goal=goal, registry=self.registry,
            active_perception=self.active_perception,
            blocked_until=self.blocked_until, recent=self.recent,
            source=source, map_zoom_count=self.map_zoom_count,
            map_zoom_requested=self.map_zoom_requested)

    # Compatibility projection while callers migrate to map_search_policy.
    # The state has one owner; these properties do not duplicate it.
    @property
    def map_scan_started(self):
        return self.map_search_policy.state.scan_started

    @map_scan_started.setter
    def map_scan_started(self, value):
        self.map_search_policy.state.scan_started = value

    @property
    def map_probes(self):
        return self.map_search_policy.state.probes

    @map_probes.setter
    def map_probes(self, value):
        self.map_search_policy.state.probes = int(value)

    @property
    def map_zoom_count(self):
        return self.map_search_policy.state.zoom_count

    @map_zoom_count.setter
    def map_zoom_count(self, value):
        self.map_search_policy.state.zoom_count = int(value)

    @property
    def map_zoom_requested(self):
        return self.map_search_policy.state.zoom_requested

    @map_zoom_requested.setter
    def map_zoom_requested(self, value):
        self.map_search_policy.state.zoom_requested = bool(value)

    @property
    def map_search_exhausted(self):
        return self.map_search_policy.state.exhausted

    @map_search_exhausted.setter
    def map_search_exhausted(self, value):
        self.map_search_policy.state.exhausted = bool(value)

    @property
    def map_search_context(self):
        return self.map_search_policy.state.context

    @map_search_context.setter
    def map_search_context(self, value):
        self.map_search_policy.state.context = value
        # Legacy tests/tools use this field to seed an already-established
        # search context; preserve that meaning for the visual-search FSM too.
        self._visual_search_context = value

    @property
    def last_map_scan_started(self):
        return self.map_search_policy.state.last_scan_started

    @last_map_scan_started.setter
    def last_map_scan_started(self, value):
        self.map_search_policy.state.last_scan_started = value

    @property
    def used_location_fallbacks(self):
        return self.map_search_policy.state.used_location_fallbacks

    def map_inspection_status(self):
        return self.map_search_policy.status()

    # A quest script usually takes the player off the vehicle right after its
    # stage; give it that long before leaving by ourselves.
    VEHICLE_STAGE_EXIT_SECONDS = 40.
    VEHICLE_STAGE_EXIT_ON_FOOT_SECONDS = 8.
    ON_FOOT_ACTIONS = frozenset({"TALK", "INTERACT_OBJECT", "COLLECT", "GO_TO", "USE_ITEM_ON_TARGET",
                                 "ESCORT", "DEFEND"})

    def _vehicle_stage_exit_reason(self, world, now: float) -> str | None:
        """User 2026-10-04: some quests do not take the player off the vehicle.

        A stage completed while riding (e.g. 8/8 cadavers) and no further
        objective of that quest progressed since: after a grace period for a
        scripted dismount, leave the vehicle.  The grace is short when the
        local LLM read every remaining objective as on-foot work.
        """
        model = getattr(world, "_model", None) or world
        stamps = model.__dict__.get("quest_stage_completed_at") or {}
        riding = model.__dict__.get("quest_stage_completed_in_vehicle") or {}
        clock = number(getattr(model, "last_received", None))
        if clock is None:
            return None
        for quest in world.state.get("active_quests") or ():
            if not isinstance(quest, dict) or quest.get("is_complete") is True:
                continue
            qid = str(quest.get("quest_id"))
            completed_at = number(stamps.get(qid))
            if completed_at is None or riding.get(qid) is not True:
                continue
            record = world.quest_model.records.get(quest.get("quest_id"))
            open_objectives = [obj for obj in (record.objectives if record else ())
                               if obj.completion_state != "COMPLETE"]
            if not open_objectives:
                continue
            hints = [getattr(obj, "semantic_hint", None) or {} for obj in open_objectives]
            on_foot = all(hint.get("action") in self.ON_FOOT_ACTIONS for hint in hints)
            grace = self.VEHICLE_STAGE_EXIT_ON_FOOT_SECONDS if on_foot else self.VEHICLE_STAGE_EXIT_SECONDS
            if clock-completed_at >= grace:
                return ("A járműves szakasz kész, a script nem szállított le: kiszállás "
                        + ("(a hátralévő feladat gyalogos)" if on_foot else f"({grace:.0f} s után)"))
        return None

    def candidates(self, goal: Goal, world: WorldModel, now: float) -> list[Proposal]:
        state = world.state
        from .death_recovery_planning import DeathRecoveryPolicy, player_dead_or_ghost
        if player_dead_or_ghost(state):
            # Dead or a ghost: release / corpse run / resurrect only.
            policy = self.__dict__.setdefault("death_recovery", DeathRecoveryPolicy())
            proposals = policy.propose(state, now)
            for proposal in proposals:
                policy.note_dispatched(proposal, now)
            return proposals
        if (state.get("in_vehicle") is True and state.get("on_taxi") is not True
                and not state.get("is_in_combat")):
            # User 2026-10-04: sometimes the agent must leave the vehicle
            # itself.  A quest whose ride objective is done and which is now
            # complete is turned in on foot.
            from .quest_model import ride_objective_done
            if any(isinstance(quest, dict) and quest.get("is_complete") is True
                   and ride_objective_done(quest) for quest in state.get("active_quests") or ()):
                return [Proposal.make(
                    "EXIT_VEHICLE", "A jármű questje kész: kiszállás a járműből",
                    {"binding": "VEHICLEEXIT"}, priority=106,
                    evidence=(world.latest.observation_id,) if world.latest else ())]
            exit_reason = self._vehicle_stage_exit_reason(world, now)
            if exit_reason:
                return [Proposal.make(
                    "EXIT_VEHICLE", exit_reason, {"binding": "VEHICLEEXIT"}, priority=106,
                    evidence=(world.latest.observation_id,) if world.latest else ())]
        if (state.get("in_vehicle") is True or state.get("on_taxi") is True)                 and not state.get("is_in_combat") and not state.get("vehicle_controls"):
            # Live 2026-10-04 (Scout-o-Matic 5000): a used vehicle NPC seats
            # and flies the player on a scripted path; addon 0.9.47 exports
            # it.  Any movement/search input would fight the ride.  A vehicle
            # with its own ability bar (the Giant Boar) is driven instead.
            return [Proposal.make(
                "WAIT", "Járműben / taxin utazás: a szkriptelt út végéig várakozás",
                {"waiting_for": ["VEHICLE_OR_TAXI_EXIT"]},
                evidence=(world.latest.observation_id,) if world.latest else ())]
        actionable_turnin = (goal.domain == "QUEST"
                             and self.quest.location_policy.has_actionable_turnin_world_location(state))
        # A completed quest with an addon-converted WORLD_YARDS endpoint no
        # longer needs preliminary marker hunting.  The former early return
        # here was the reason generic INSPECT consumed almost a minute before
        # the first turn-in MOVE was even proposed.
        if actionable_turnin and state.get("world_map_open"):
            # Live 2026-10-03 23:50: a map opened while the turn-in point
            # flickered out of the state stayed open once it came back --
            # this branch skipped the map policy that closes it, and the
            # turn-in SEEK is unavailable over an open map: WAIT for 8 min.
            close = Proposal.make(
                "CLOSE_MAP", "Leadási hely ismert: a nyitott World Map bezárása a 3D kereséshez",
                {"purpose": "RESTORE_WORLD3D_FOR_TURN_IN"}, priority=115,
                evidence=(world.latest.observation_id,) if world.latest else ())
            if self.registry.available(close, world):
                return [close]
        map_proposals = (None if actionable_turnin else
                         self.map_search_policy.pre_domain_proposals(
                             goal, world, now, registry=self.registry, quest=self.quest,
                             inspections=self.inspections))
        if map_proposals is not None:
            return map_proposals
        search_context = self.map_search_context
        # Local camera probing is part of visual search rather than map/TDB
        # lifecycle, but resets with the same quest/map context boundary.
        if search_context != getattr(self, "_visual_search_context", None):
            self._visual_search_context = search_context
            self.camera_search_step = 0
            self.camera_search_next_at = 0.
            self.camera_search_position = None
            self.world3d_probe_count = 0
        evidence = (world.latest.observation_id,) if world.latest else ()
        proposals = []
        vendor = world.query.vendor()
        repair_cost = number(vendor.get("repair_all_cost"))
        if (vendor.get("open") and vendor.get("can_repair") and repair_cost and repair_cost > 0
                and number(vendor.get("repair_x")) is not None
                and number(vendor.get("repair_y")) is not None):
            proposals.append(Proposal.make(
                "REPAIR", "Nyitott vendor és sérült felszerelés: repair all",
                {"x": vendor["repair_x"], "y": vendor["repair_y"],
                 "repair_all_cost": repair_cost, "npc_name": vendor.get("npc_name")},
                priority=70))
        combat = self.combat_policy.propose(world, goal, now, self.quest)
        proposals.extend(combat.proposals)
        target = combat.target
        matching_objectives = list(combat.matching_objectives)
        capacity_block = goal.domain in {"HERB", "MINE", "FISH", "FARM"} and world.query.inventory().get("free_slots") == 0
        if capacity_block:
            proposals.extend(self.inventory.propose(world, goal))
        elif goal.domain == "QUEST":
            self.quest.allow_db_fallback = self.map_search_exhausted
            proposals.extend(self.quest.propose(
                world, goal, runtime_map_scan_started=self.last_map_scan_started))
            failure_memory = world.runtime_context.get("quest_failure_memory") or []
            proposals = [proposal for proposal in proposals if QuestFailureMemory.permits_snapshot(
                failure_memory, proposal.parameters, proposal.skill, now)]
            commitment = world.runtime_context.get("commitment") or {}
            # A live addon-confirmed identity outranks offline location
            # hypotheses. A failed click must reacquire the same GUID rather
            # than silently switching to another TDB quest starter.
            if commitment.get("target_guid") and not state.get("target"):
                proposals = [p for p in proposals
                             if p.parameters.get("source") != "TDB_REFERENCE"]
            self.map_search_policy.add_quest_fallbacks(
                proposals, goal, world, now, blocked_until=self.blocked_until)
        elif goal.domain in {"HERB", "MINE", "FISH", "FARM"}:
            proposals.extend(self.resources.propose(world, goal))
        elif goal.domain in {"MOVE", "EXPLORE"}:
            destination = point(goal.parameters.get("destination"))
            if destination:
                proposals.append(Proposal.make("MOVE", "Felhasználói célhoz tartozó hely", destination, priority=50))
        elif goal.domain == "DUNGEON":
            proposals.extend(self.dungeon.propose(world, goal))
        elif goal.domain == "PVP":
            proposals.extend(self.pvp.propose(world, goal))
        proposals.extend(self.inspections(world, now, goal=goal))
        committed_quest_routes = [
            proposal for proposal in proposals
            if proposal.skill == "MOVE"
            and proposal.parameters.get("purpose") in {
                "LOCATE_TURN_IN_REGION", "LOCATE_QUEST_OBJECTIVE_REGION"}
            and proposal.parameters.get("require_navmesh") is True]
        movement_visual_handoff = self._active_movement_visual_handoff(now)
        if committed_quest_routes and movement_visual_handoff is None:
            # Background uncertainty is not an interrupt.  Hold the exact
            # quest location subgoal until arrival/failure; inspect/search
            # resumes afterwards to resolve the actual local entity/object.
            proposals = [proposal for proposal in proposals
                         if proposal.skill not in {"INSPECT", "SEEK_VISUAL_CUE", "OPEN_MAP"}]
        search_input = proposals
        if committed_quest_routes and movement_visual_handoff is not None:
            # The route has just yielded its input lease for this exact visual
            # cue. Do not let its mere presence suppress construction of the
            # distant SEEK proposal; add the retained route back afterwards.
            search_input = [proposal for proposal in proposals
                            if proposal not in committed_quest_routes]
        search = self.visual_search_policy.propose(
            search_input, world=world, goal=goal, now=now, target=target,
            matching_objectives=matching_objectives,
            active_perception=self.active_perception,
            blocked_until=self.blocked_until,
            world3d_probe_count=self.world3d_probe_count,
            camera_search_step=self.camera_search_step,
            camera_search_next_at=self.camera_search_next_at,
            camera_search_position=self.camera_search_position,
            quest_areas=getattr(getattr(self.quest, "location_policy", None), "quest_areas", None))
        proposals = list(search.proposals)
        if committed_quest_routes and movement_visual_handoff is not None:
            proposals.extend(committed_quest_routes)
        self.camera_search_step = search.camera_search_step
        self.camera_search_next_at = search.camera_search_next_at
        self.camera_search_position = search.camera_search_position

        if committed_quest_routes and movement_visual_handoff is not None:
            # MOVE was stopped at a verified ownership boundary because its
            # passive World3D stream found one stable, goal-relevant UNKNOWN
            # track.  Admit only that exact track (never the surrounding
            # background proposals), and rank its bounded IDENTIFY/INSPECT
            # handoff above the retained route.  If it is rejected/lost, the
            # unchanged quest route is proposed again on the next cycle.
            track_id = str(movement_visual_handoff["track_id"])
            retained: list[Proposal] = []
            for candidate in proposals:
                candidate_track = candidate.parameters.get("track_id")
                if candidate.skill in {"INSPECT", "SEEK_VISUAL_CUE"}:
                    if candidate_track is None or str(candidate_track) != track_id:
                        continue
                    candidate = Proposal.make(
                        candidate.skill,
                        "Quest MOVE közben észlelt releváns vizuális cue célzott vizsgálata",
                        {**candidate.parameters,
                         "movement_visual_handoff": dict(movement_visual_handoff)},
                        confidence=candidate.confidence,
                        priority=max(120., candidate.priority),
                        evidence=candidate.evidence)
                elif candidate.skill == "OPEN_MAP":
                    continue
                retained.append(candidate)
            proposals = retained

        if goal.domain == "QUEST":
            proposals = self.quest.apply_collect_strategy(proposals, world)

        mount = goal.parameters.get("mount_binding")
        if mount and not state.get("is_mounted") and not state.get("is_in_combat") and not state.get("is_casting"):
            long_move = next((p for p in proposals if p.skill == "MOVE" and (world.distance(p.parameters) or 0) > .04), None)
            usable = any(a.get("action") == mount and a.get("is_usable") is True and a.get("cooldown_remaining") == 0 for a in state.get("actionbar", []))
            if long_move and usable:
                proposals.append(Proposal.make("MOUNT", "Hosszabb út, felhasználó által kijelölt mount-képességgel", {"binding": mount}, priority=long_move.priority+3))
        if mount and state.get("is_mounted") and not state.get("is_casting") and not state.get("is_in_combat"):
            on_foot = [p for p in proposals if p.skill in {
                "ACQUIRE_TARGET", "COMBAT", "ASSIST", "INTERACT", "TALK", "OBJECT_USE", "LOOT",
                "USE_ON_TARGET", "FOLLOW_INSTRUCTION", "GATHER", "HERB", "MINE", "FISH", "REPAIR",
                "BUY_VENDOR", "OPEN_BAGS", "SELL_VENDOR",
            }]
            if on_foot:
                highest = max(p.priority for p in on_foot)
                proposals.append(Proposal.make(
                    "DISMOUNT", "Megerősített, gyalogos interakció előtt a kijelölt mount-binding kikapcsolása",
                    {"binding": mount, "for_skill": max(on_foot, key=lambda p: p.priority).skill},
                    priority=highest+1))
        # Exact same decision + target + strategy may not be repeated after a
        # non-retryable failure until relevant semantic evidence changes.
        # Frame/timestamp churn is deliberately absent from the evidence hash.
        proposals = self.filter_decision_loops(proposals, goal, state)
        ranking = self.proposal_ranker.rank(
            proposals, goal=goal, world=world, now=now,
            registry=self.registry, memory=self.memory,
            blocked_until=self.blocked_until, recent=self.recent,
            evidence=evidence)
        self.pattern_analysis = ranking.pattern_analysis
        self.last_scores = ranking.scores
        return list(ranking.proposals)
