from __future__ import annotations

from wowbot.query_ports import NavigationQueryPorts, TravelCostPort
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
from .visual_search_planning import VisualSearchPlanningPolicy, VisualSearchPlanningResult
from .map_search_planning import WorldMapFallbackPolicy
from .decision_fingerprint import DecisionFingerprintGuard
from .destination_distance import world_arrived
from .travel_mode import TravelModePolicy



class Planner:
    """One planner ranks proposals from all domains; no direct input calls."""

    def __init__(self, registry, memory=None, quest_attempt_memory=None, *,
                 travel_cost: TravelCostPort | None = None,
                 navigation_queries: NavigationQueryPorts | None = None):
        self.registry = registry
        self.memory = memory
        self.travel_cost = travel_cost
        self.navigation_queries = navigation_queries or NavigationQueryPorts()
        from .quest_attempt_memory import QuestAttemptMemory
        self.quest_attempt_memory = quest_attempt_memory or QuestAttemptMemory()
        self.quest = QuestDomain(self.quest_attempt_memory, travel_cost=self.travel_cost,
                                 navigation_queries=self.navigation_queries)
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
        self._movement_visual_cooldowns: dict[tuple, float] = {}
        from .quest_agenda import QuestAgenda
        self.agenda = QuestAgenda(travel_cost=self.travel_cost)
        self.travel_mode = TravelModePolicy(departure_walk=self.navigation_queries.flight_departure_walk)

    def reset_session(self) -> None:
        """Drop every session-local decision cache after identity changes.

        Proposal cooldowns, failed locations and camera/map scan progress are
        evidence about one character in one world session.  Carrying any of
        them into the next session can suppress valid actions or resume a
        half-finished search against unrelated state.
        """
        self.quest_attempt_memory.reset()
        self.quest = QuestDomain(self.quest_attempt_memory, travel_cost=self.travel_cost,
                                 navigation_queries=self.navigation_queries)
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
        self._movement_visual_cooldowns.clear()
        self.agenda.reset()
        self.travel_mode = TravelModePolicy(departure_walk=self.navigation_queries.flight_departure_walk)

    def refresh_agenda(self, goal, world, now, *, advisor=None):
        # Look-ahead only, also during an active attempt. This never calls
        # candidates(), dispatches input or replaces the active skill.
        probes = self.__dict__.get("objective_probes")
        self.agenda.exhausted_objectives = probes.deferred(now) if probes is not None else frozenset()
        self.agenda.refresh(goal, world, now, advisor=advisor)

    @staticmethod
    def _movement_visual_scope(route: Proposal, state: dict) -> tuple:
        params = route.parameters
        # Sampling times / frame IDs are deliberately absent. Re-observing
        # the same cue is not a reason to cancel the same route every tick.
        return (route.skill,
                *(str(state.get(key)) for key in ("session_id", "character_guid", "map_id")),
                *(str(params.get(key)) for key in (
                    "purpose", "quest_id", "objective_id", "x", "y", "z", "instance_id",
                    "coordinate_space", "npc_id", "npc_ids", "target_guid")))

    def suppressed_movement_visual_tracks(self, route: Proposal, state: dict,
                                          now: float) -> frozenset[str]:
        self._movement_visual_cooldowns = {
            key: until for key, until in self._movement_visual_cooldowns.items() if now < until}
        scope = self._movement_visual_scope(route, state)
        return frozenset(track for (context, track) in self._movement_visual_cooldowns
                         if context == scope)

    def arm_movement_visual_handoff(self, handoff: dict, now: float, *,
                                   route: Proposal | None = None,
                                   world_state: dict | None = None) -> None:
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
        if route is not None:
            # This suppresses repeated VISUAL-only cancellation, not TARGET,
            # fresh GUID evidence, a different cue, or a changed quest/route.
            scope = self._movement_visual_scope(route, world_state or {})
            self._movement_visual_cooldowns[(scope, str(track_id))] = float(now) + 8.
            while len(self._movement_visual_cooldowns) > 64:
                self._movement_visual_cooldowns.pop(next(iter(self._movement_visual_cooldowns)))

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
        from .quest_playbooks import horizon_for
        playbook = horizon_for(proposal, world.state)
        objective_id = params.get("objective_id") or (playbook[0].objective_id if playbook else None)
        objective = next((item for record in world.quest_model.records.values()
                          for item in record.objectives if item.objective_id == objective_id), None)
        contract = self.registry.contracts[proposal.skill]
        steps = [{"order": 0, "phase": "EXECUTE", "capability": proposal.skill,
                  "status": "READY", "objective_id": objective_id,
                  "preconditions": list(contract.preconditions),
                  "expected_observation": contract.expected,
                  "fallback": contract.recovery, "confidence": proposal.confidence}]
        if playbook is not None:
            steps[0].update(playbook=playbook[0].book.mechanism, playbook_step=playbook[0].step.name,
                            missing_handlers=list(playbook[0].book.missing))
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
        future = (playbook[1] if playbook is not None else tuple(
            {"capability": capability, "expected_observation": expected}
            for capability, expected in chains.get(getattr(objective, "type", None), ())))
        for stage in future:
            capability, expected = stage["capability"], stage["expected_observation"]
            if capability == proposal.skill:
                continue
            steps.append({"order": len(steps), "phase": "FUTURE", "capability": capability,
                          "status": "BLOCKED_BY_PRIOR_STEP", "objective_id": objective_id,
                          "preconditions": ["prior_step_verified", "objective_still_active",
                                            *stage.get("preconditions", ())],
                          **({"playbook": playbook[0].book.mechanism, "playbook_step": stage["playbook_step"]}
                             if playbook is not None else {}),
                          **({key: stage[key] for key in ('node_id', 'depends_on') if key in stage}),
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
        from .server_mode import server_profile
        if server_profile(world.state):
            return []                      # no World3D/minimap/map CV inspection
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
            if any(r.get("quest_id") == qid for r in world.state.get("vehicle_requirements") or ()):
                continue  # other proven vehicle objectives still need this ride
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

    TRADE_SKILLS = frozenset({"BUY_VENDOR", "SELL_VENDOR", "REPAIR", "OPEN_BAGS", "QUEST_DIALOG"})

    def _vendor_owns_input(self, proposals: list[Proposal], world) -> list[Proposal]:
        """An open vendor with an unfinished buy/sell objective owns the input.

        Live 2026-10-11 15:51-15:52 (Stocking Up on Supplies): with the
        vendor open a distant-UNKNOWN SEEK (87) beat BUY_VENDOR (86), and the
        sell -> buy took 18 s of camera sweeps; BUY/SELL are also briefly
        unavailable while the vendor snapshot is older than 2 s.
        """
        if (world.query.vendor() or {}).get("open") is not True:
            return proposals
        model = getattr(world, "quest_model", None)
        trade_open = any(str(getattr(objective, "type", "") or "").upper() in {"BUY", "SELL"}
                         for objective in (model.ready() if model is not None else ()))
        if not trade_open:
            return proposals
        kept = [proposal for proposal in proposals
                if proposal.skill in self.TRADE_SKILLS | {"DEFEND", "ESCAPE"}]
        if any(proposal.skill in self.TRADE_SKILLS for proposal in kept):
            return kept
        return kept + [Proposal.make(
            "WAIT", "Nyitott vendor: friss vendor-adatra várakozás a vásárláshoz/eladáshoz",
            {"waiting_for": ["VENDOR_UI_DETAILS"]}, priority=85)]

    EMPTY_DIALOG_SECONDS = 6.

    @staticmethod
    def _item_subject_owns_input(proposals, world, objective):
        """Do not replace a found item subject with an unrelated zone sweep.

        This is only proposal filtering, like the vendor/modal boundary. It
        does not acquire identity, click, or create a second running skill.
        """
        state = world.state
        guid = (state.get("target") or {}).get("guid")
        item_id = (objective.target_object or {}).get("item_id")
        kept = []
        for proposal in proposals:
            params = proposal.parameters
            if proposal.skill in {"DEFEND", "ESCAPE", "COMBAT"} and state.get("is_in_combat"):
                kept.append(proposal)
                continue
            if params.get("guid") != guid or str(params.get("item_id")) != str(item_id):
                continue
            if (proposal.skill in {"USE_ON_TARGET", "ASSIST"}
                    or proposal.skill == "OPEN_BAGS" and params.get("purpose") == "QUEST_ITEM"
                    or proposal.skill == "VISUAL_APPROACH" and params.get("item_use_approach") is True
                    or proposal.skill == "MOVE" and params.get("purpose") == "APPROACH_ITEM_TARGET"
                    or proposal.skill == "WAIT" and params.get("purpose") == "QUEST_ITEM_READY"):
                kept.append(proposal)
        # A transient unavailable local tool must not turn into movement away
        # from the selected unit. Normal wait budgets and fresh evidence still
        # govern re-planning; no identity or input authority is invented.
        if not kept:
            kept.append(Proposal.make(
                "WAIT", "Kijelölt quest-item célpont: helyi használat / friss bizonyíték várakozik",
                {"guid": guid, "item_id": item_id, "objective_id": objective.objective_id,
                 "purpose": "QUEST_ITEM_READY"}, priority=85))
        return kept

    UNHELPFUL_DIALOG_SECONDS = 4.          # user 2026-10-26: "legyen 4s"

    def _close_unhelpful_dialog(self, world, state: dict) -> Proposal | None:
        """User 2026-10-26: an NPC window with gossip rows or quest rows the
        dialog logic takes nothing from (no quest of ours, no useful option,
        not a vendor we need) left the agent waiting in front of it.  After
        UNHELPFUL_DIALOG_SECONDS and a fresh full snapshot it is closed
        (Escape = Goodbye).  A vendor window belongs to the vendor flow."""
        now = number(state.get("monotonic_time"))
        if now is None or (state.get("vendor_ui") or {}).get("open") is True:
            self.__dict__["_unhelpful_dialog_since"] = None
            return None
        since = self.__dict__.get("_unhelpful_dialog_since")
        if since is None or now < since:
            self.__dict__["_unhelpful_dialog_since"] = since = now
        snapshot = number(state.get("state_sample_time"))
        if now - since < self.UNHELPFUL_DIALOG_SECONDS or snapshot is None or snapshot < since + 1.:
            return None
        proposal = Proposal.make(
            "CLOSE_DIALOG", "NPC-ablak, amiből semmi nem kell (nincs quest, hasznos opció vagy vendor): bezárás",
            {"waiting_for": [], "unhelpful_seconds": round(now - since, 1)}, priority=116)
        if not self.registry.available(proposal, world):
            return None
        self.__dict__["_unhelpful_dialog_since"] = None
        return proposal

    def _close_empty_dialog(self, world, state: dict) -> Proposal | None:
        """An NPC window that stays empty (no button, no quest row, no
        conversation option) after a full snapshot was seen with it open."""
        ui = state.get("quest_ui") or {}
        now = number(state.get("monotonic_time"))
        action = str(ui.get("action") or state.get("quest_ui_action") or "").upper()
        x = number(ui.get("x")) or number(state.get("quest_ui_x"))
        y = number(ui.get("y")) or number(state.get("quest_ui_y"))
        # Live 2026-10-19 14:47:53: a CONTINUE panel with no button point (x=y=0,
        # quest_id 0) at Henry Garrick offered nothing clickable; treating its
        # action as content kept the agent waiting 55 s in front of it.
        from .quest_ui_evidence import FAST_BUTTON_ACTIONS
        if action in FAST_BUTTON_ACTIONS and not (x and y and x > 0 and y > 0):
            action = ""
        if (now is None or action
                or ui.get("entries") or state.get("quest_ui_entries")
                or ui.get("gossip_option") or state.get("quest_ui_gossip_option")
                or ui.get("gossip_options")
                or (state.get("vendor_ui") or {}).get("open") is True):
            self.__dict__["_empty_dialog_since"] = None
            return None
        since = self.__dict__.get("_empty_dialog_since")
        if since is None:
            self.__dict__["_empty_dialog_since"] = since = now
        snapshot = number(state.get("state_sample_time"))
        if now - since < self.EMPTY_DIALOG_SECONDS or snapshot is None or snapshot < since + 1.:
            return None
        proposal = Proposal.make(
            "CLOSE_DIALOG", "Üres NPC-ablak (nincs gomb vagy quest-sor): bezárás ESC-vel",
            {"waiting_for": [], "empty_seconds": round(now - since, 1)}, priority=116)
        if not self.registry.available(proposal, world):
            return None
        # Live 2026-10-21 15:53:01-15:53:21: close, reopen, close ... at
        # Cataloger Jakes.  quest_objective_planning stops reopening an NPC
        # whose window was closed empty twice within two minutes.
        from wowbot.runtime.skill_identity import sample_fresh, soft_interact
        soft = soft_interact(state) if sample_fresh(state, "soft_targets", now) else None
        npc = str(ui.get("npc_guid") or (soft or {}).get("guid")
                  or (state.get("target") or {}).get("guid") or "")
        if npc:
            closes = world.__dict__.setdefault("empty_dialog_closes", {})
            recent = [at for at in closes.get(npc, ()) if 0 <= now-at <= 120.][-3:]
            if not recent or now-recent[-1] > 2.:      # one close per window
                recent.append(now)
            closes[npc] = recent
        # Do not carry this window's expired timer into the next opening.
        self.__dict__["_empty_dialog_since"] = None
        return proposal

    # Live 2026-10-20 16:52-16:54 (Murloc Mania): the server-position walk-up
    # and Tab ran, but INSPECT/SEEK and objective-region / search-cell MOVEs
    # kept preempting them (a WORLD_YARDS MOVE ranks 20 lower), so the agent
    # zig-zagged between the murlocs the server showed and screen searches.
    # While the server names the objective mob to go for, searching for it
    # on screen or on the map adds nothing.
    SERVER_TARGET_EVIDENCE = frozenset({"kill_objective_entry", "tab_nearest_ahead"})
    SEARCH_ONLY_SKILLS = frozenset({"SEEK_VISUAL_CUE", "INSPECT", "OPEN_MAP"})
    SEARCH_ONLY_PURPOSES = frozenset({"LOCATE_QUEST_OBJECTIVE_REGION", "SEARCH_LOCAL_OBJECTIVE_AREA",
                                      "APPROACH_MINIMAP_QUEST_DOT", "APPROACH_MINIMAP_OTHER_FLOOR_OBJECTIVE",
                                      "SEARCH_RESCUE_OBJECTIVE", "SEARCH_QUEST_ITEM_SUBJECT"})

    # Live 2026-10-21 10:34-10:35 (Explorers in Peril, Waking Shores): with
    # no server proposal the vision fallback ran SEEK/INSPECT for 45 s.  User:
    # "szerver módban ne legyen visual" -- screen searching never runs then;
    # walking the quest area brings the target into server range instead.
    # User 2026-10-21 16:10 ("sárga pötty a minimapon odamegyek? vizuális jel
    # fel-le? nem lettek ezek kikapcsolva?"): the minimap dot / floor-arrow
    # MOVEs, map scans and 3D-box approaches ran in server mode as well.
    # Everything derived from the screen is off while the server leads.
    VISION_SEARCH_SKILLS = frozenset({"SEEK_VISUAL_CUE", "INSPECT", "OPEN_MAP", "VISUAL_APPROACH",
                                      "REACQUIRE_TARGET", "CAMERA_CONTROL"})
    VISION_MOVE_PURPOSES = frozenset({"APPROACH_MINIMAP_QUEST_DOT", "APPROACH_MINIMAP_OTHER_FLOOR_OBJECTIVE",
                                      "SEARCH_LOCAL_OBJECTIVE_AREA"})

    @classmethod
    def vision_driven(cls, proposal: Proposal) -> bool:
        from .server_mode import pointer_target
        return (pointer_target(proposal) or proposal.skill in cls.VISION_SEARCH_SKILLS
                or (proposal.skill in {"MOVE", "REACH_LOCATION"}
                    and proposal.parameters.get("purpose") in cls.VISION_MOVE_PURPOSES))

    @classmethod
    def prefer_server_targets(cls, proposals: list[Proposal], *, server_mode: bool = False) -> list[Proposal]:
        # Server mode (user 2026-10-21): any server-driven proposal leads,
        # not only a kill target -- searching the screen or map then waits.
        from .server_mode import server_driven
        if server_mode:
            proposals = [proposal for proposal in proposals
                         if not cls.vision_driven(proposal)] or [Proposal.make(
                "WAIT", "Szerver mód: nincs szerveres teendő, képernyős keresés nélkül várok",
                {"waiting_for": ["SERVER_ENTITY"], "reason": "server_mode_no_server_option"})]
        lead = (any(server_driven(proposal) for proposal in proposals) if server_mode
                else any(cls.SERVER_TARGET_EVIDENCE & set(proposal.evidence or ()) for proposal in proposals))
        if not lead:
            return proposals
        kept = [proposal for proposal in proposals
                if proposal.skill not in cls.SEARCH_ONLY_SKILLS
                and not (proposal.skill in {"MOVE", "REACH_LOCATION"}
                         and proposal.parameters.get("purpose") in cls.SEARCH_ONLY_PURPOSES)]
        return kept or proposals

    def candidates(self, goal: Goal, world: WorldModel, now: float) -> list[Proposal]:
        from .death_recovery_planning import player_dead_or_ghost
        if player_dead_or_ghost(world.state):
            return self._candidates(goal, world, now)
        self.refresh_agenda(goal, world, now)
        from .server_mode import server_mode_selected
        proposals = self.prefer_server_targets(self._candidates(goal, world, now),
                                               server_mode=server_mode_selected(world.state))
        # P8.4: typed dead-ends are named once to the user (journal + status).
        from .needs_user import NeedsUserLedger
        self.__dict__.setdefault("needs_user", NeedsUserLedger()).observe(proposals, now)
        # Cover modal UI / map / safety early returns as well. This is an
        # explanation of the recommendation, not a second dispatch authority.
        self.agenda.note_recommendation(proposals, now)
        return proposals

    def _candidates(self, goal: Goal, world: WorldModel, now: float) -> list[Proposal]:
        state = world.state
        if goal.domain == "QUEST":
            self.quest.dialog_policy.transitions.observe(state)
        dialog_open = ((state.get("quest_ui") or {}).get("open") is True
                       or state.get("quest_ui_open") is True
                       or (state.get("gossip_ui") or {}).get("open") is True
                       or state.get("gossip_open") is True)
        if not dialog_open:
            self.__dict__["_empty_dialog_since"] = None
            self.__dict__["_unhelpful_dialog_since"] = None
        dialog_context = (state.get("session_id"), WorldModel.quest_signature(state))
        previous_context = self.__dict__.get("_empty_dialog_quest_context")
        if previous_context is not None and previous_context != dialog_context:
            world.__dict__.pop("empty_dialog_closes", None)
        self.__dict__["_empty_dialog_quest_context"] = dialog_context
        from .death_recovery_planning import DeathRecoveryPolicy, player_dead_or_ghost
        if player_dead_or_ghost(state):
            # Dead or a ghost: release / corpse run / resurrect only.
            policy = self.__dict__.setdefault("death_recovery", DeathRecoveryPolicy())
            proposals = policy.propose(state, now, hostile_units=self.navigation_queries.hostile_units,
                                       walk_cost=self.travel_cost)
            for proposal in proposals:
                policy.note_dispatched(proposal, now)
            return self.travel_mode.apply(proposals, goal, world, now)
        if state.get("is_in_combat"):
            from wowbot.runtime.supervisor import Supervisor
            combat = self.combat_policy.propose(world, goal, now, self.quest)
            admitted = [p for p in combat.proposals
                        if Supervisor.combat_admissible(p.skill, p.parameters)]
            # Do not fall through to map/dialog/quest-MOVE when identity is
            # unavailable or combat is on cooldown. The next observation can
            # reacquire the attacker without a start/cancel movement loop.
            proposals = admitted or [Proposal.make(
                "WAIT", "Harc: friss támadó/célazonosság bizonyítékára várakozás",
                {"waiting_for": ["COMBAT_TARGET_EVIDENCE"]}, priority=100)]
            return self._rank_candidates(self.filter_decision_loops(proposals, goal, state),
                                         goal, world, now,
                                         (world.latest.observation_id,) if world.latest else ())
        from .quest_tool_resolver import QuestToolResolver
        from .collection_coverage import quest_baseline_problem
        baseline_problem = quest_baseline_problem(state) if goal.domain == 'QUEST' else None
        if baseline_problem and not dialog_open:
            return [Proposal.make('WAIT', 'A questlista vagy az objective-lista még részleges; új baseline szükséges',
                                  {'reason': baseline_problem, 'waiting_for': ['COMPLETE_QUEST_BASELINE']})]
        local_item = (QuestToolResolver.selected_objective(state, world.quest_model.ready(), now=now)
                      if goal.domain == "QUEST" else None)
        if goal.domain == "QUEST" and (
                (state.get("quest_ui") or {}).get("open") is True
                or state.get("quest_ui_open") is True
                or (state.get("gossip_ui") or {}).get("open") is True
                or state.get("gossip_open") is True):
            # An open dialog owns the input boundary. A route/map proposal
            # may have been generated just before the addon reported the UI;
            # never let it outrank ACCEPT/selection or walk the player away.
            # Live 23:06:34: this early return hid Edress's open window from
            # the speech hold, so it never waited; it still records the talk.
            from .objective_speech_planning import ObjectiveSpeechHold
            self.quest.__dict__.setdefault("objective_speech", ObjectiveSpeechHold()).observe(state)
            from .objective_probes import ObjectiveProbeLadder
            probes = self.__dict__.setdefault("objective_probes", ObjectiveProbeLadder())
            dialogs = self.quest.dialog_policy.propose(
                state, goal, attempt_memory=self.quest.attempt_memory, probe=probes.active_probe(state))
            available = [proposal for proposal in dialogs
                         if self.registry.available(proposal, world)]
            if available:
                self.__dict__["_empty_dialog_since"] = None
                self.__dict__["_unhelpful_dialog_since"] = None
                return available
            close = self._close_empty_dialog(world, state) or self._close_unhelpful_dialog(world, state)
            return [close] if close is not None else [Proposal.make(
                "WAIT", "Nyitott NPC/quest ablak részleteire várakozás",
                {"waiting_for": ["QUEST_OR_GOSSIP_UI_DETAILS"]}, priority=115)]
        if goal.domain == "QUEST":
            from .vehicle_prerequisites import resume_proposals
            transition = self.quest.dialog_policy.transitions.propose(state)
            if transition is not None:
                # Hold owns only the no-input boundary; combat/death and open
                # UI above still lead. No MOVE/target swap/mount while a
                # selected duel or a verified local turn-in is transitioning.
                return [transition]
            from .server_npc_planning import ServerNpcInteractionPolicy
            resume = resume_proposals(
                state, self.quest.__dict__.setdefault("server_npcs", ServerNpcInteractionPolicy(travel_cost=self.travel_cost)),
                primary_quest_id=(world.runtime_context.get("primary_quest") or {}).get("quest_id"),
                travel_cost=self.travel_cost)
            if resume is not None:
                return self._rank_candidates(self.filter_decision_loops(resume, goal, state),
                                             goal, world, now, ())
        if (state.get("in_vehicle") is True and state.get("on_taxi") is not True
                and not state.get("is_in_combat")
                # Live 2026-10-26 11:00:48: a scripted ride (no vehicle UI, no
                # vehicle bar) completed its quest on boarding; Leave Vehicle
                # was pressed 3x in vain.  Only a seat the client shows a
                # vehicle UI for can be left.
                and (state.get("has_vehicle_ui") is True or bool(state.get("vehicle_controls")))):
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
        from .vehicle_abilities import stationary_objective_actions, stationary_vehicle_controls
        if stationary_vehicle_controls(state):
            vehicle = stationary_objective_actions(state)
            return self._rank_candidates(vehicle, goal, world, now, ()) or [Proposal.make(
                "WAIT", "Jármű quest-vezérlés: friss vagy használható, objective-hez igazolt gombra vár",
                {"purpose": "VEHICLE_QUEST_OBJECTIVE", "waiting_for": ["VERIFIED_VEHICLE_OBJECTIVE_ACTION"]},
                priority=120)]
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
        map_proposals = (None if actionable_turnin or local_item is not None else
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
        # REV4 survival: regenerate before a new pull (out of combat only;
        # the in-combat branch returned above). Applied to the whole set
        # below, after the domain proposals exist.
        from .survival_planning import ReadinessPolicy
        readiness = self.__dict__.setdefault("readiness", ReadinessPolicy())
        matching_objectives = list(combat.matching_objectives)
        capacity_block = goal.domain in {"HERB", "MINE", "FISH", "FARM"} and world.query.inventory().get("free_slots") == 0
        if capacity_block:
            proposals.extend(self.inventory.propose(world, goal))
        elif goal.domain == "QUEST":
            self.quest.allow_db_fallback = self.map_search_exhausted
            proposals.extend(self.quest.propose(
                world, goal, runtime_map_scan_started=self.last_map_scan_started))
            # P8.1: bounded live probes for unknown-source objectives at their
            # server POI; low priority, every known handler still leads.
            from .objective_probes import ObjectiveProbeLadder
            probes = self.__dict__.setdefault("objective_probes", ObjectiveProbeLadder())
            proposals.extend(probes.propose(world, state, now))
            proposals = probes.suppress_area_returns(proposals, state)
            # P8.4: an ARRIVE / AREA_TRIGGER objective's exact client trigger.
            from .arrival_targets import ArrivalTargetPolicy
            proposals.extend(self.__dict__.setdefault("arrival_targets", ArrivalTargetPolicy()).propose(world, state))
            from .container_planning import ContainerOpenPolicy
            proposals.extend(self.__dict__.setdefault("containers", ContainerOpenPolicy()).propose(state))
            from .emote_planning import EmotePolicy
            proposals.extend(self.__dict__.setdefault("emotes", EmotePolicy()).propose(state))
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
        proposals = readiness.apply(proposals, state, now, world.runtime_context.get("last_result"))
        committed_quest_routes = [
            proposal for proposal in proposals
            if proposal.skill == "MOVE"
            and proposal.parameters.get("purpose") in {
                "LOCATE_TURN_IN_REGION", "LOCATE_QUEST_OBJECTIVE_REGION",
                "LOCATE_API_QUEST_GIVER"}
            and proposal.parameters.get("require_navmesh") is True
            and self.blocked_until.get(proposal.key, 0) <= now
            and self.registry.available(proposal, world)
            and not world_arrived(world, proposal.parameters)]
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
        from .server_mode import server_profile
        search = (VisualSearchPlanningResult(tuple(search_input), self.camera_search_step,
                                             self.camera_search_next_at, self.camera_search_position)
                  if server_profile(world.state) else None) or self.visual_search_policy.propose(
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
        location_policy = getattr(self.quest, "location_policy", None)
        if goal.domain == "QUEST" and location_policy is not None:
            proposals = location_policy.drop_area_sweeps_while_dots(proposals, world.state)
            lock = getattr(getattr(location_policy, "object_interaction", None), "lock", None)
            if lock is not None and lock.active:
                # User 2026-10-14: a found quest object keeps the mouse; no
                # other hover / camera search takes it (combat releases it).
                proposals = [proposal for proposal in proposals if not lock.holds_mouse(proposal)]
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
            proposals = self._vendor_owns_input(proposals, world)
            if local_item is not None and (world.query.vendor() or {}).get("open") is not True:
                proposals = self._item_subject_owns_input(proposals, world, local_item)

        proposals = self._without_empty_dialog_reopens(proposals, world, now)
        proposals = self.travel_mode.apply(proposals, goal, world, now)
        # Exact same decision + target + strategy may not be repeated after a
        # non-retryable failure until relevant semantic evidence changes.
        # Frame/timestamp churn is deliberately absent from the evidence hash.
        proposals = self.filter_decision_loops(proposals, goal, state)
        if goal.domain == "QUEST":
            proposals = self.agenda.apply(proposals, world, now, registry=self.registry,
                                          blocked_until=self.blocked_until)
        return self._rank_candidates(proposals, goal, world, now, evidence)

    def _rank_candidates(self, proposals, goal, world, now, evidence):
        from .objective_choice import ObjectiveContext
        context = self.__dict__.setdefault("objective_context", ObjectiveContext())
        context.observe(world.state, now)
        from .quest_playbooks import scores_for
        ranking = self.proposal_ranker.rank(
            proposals, goal=goal, world=world, now=now,
            registry=self.registry, memory=self.memory,
            blocked_until=self.blocked_until, recent=self.recent,
            evidence=evidence, objective_context=context.snapshot(),
            playbook_guidance=(scores_for(proposals, world.state, self.quest_attempt_memory)
                               if goal.domain == "QUEST" else None))
        self.pattern_analysis = ranking.pattern_analysis
        self.last_scores = ranking.scores
        return list(ranking.proposals)

    @staticmethod
    def _without_empty_dialog_reopens(proposals, world, now):
        """Apply the same bounded negative UI evidence to every NPC path."""
        from .quest_objective_planning import vendor_dialog_suppressed
        closes = world.__dict__.get("empty_dialog_closes")
        if not closes:
            return proposals
        kept = []
        for proposal in proposals:
            params = proposal.parameters
            guid = params.get("soft_guid") or params.get("guid") or params.get("server_entity_guid")
            if (proposal.skill in {"INTERACT", "TALK", "MOVE", "REACH_OBJECT", "VISUAL_APPROACH", "TARGET"}
                    and vendor_dialog_suppressed(closes, guid, now)):
                continue
            kept.append(proposal)
        return kept
