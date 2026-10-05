from __future__ import annotations
from dataclasses import asdict, replace
import threading
import time
from .models import Attempt, Goal, Mode, Observation, Outcome, Plan, Proposal
from .planner import Planner
from .skills import SkillRegistry
from .world import WorldModel
from wowbot.navigation.service import NavigationService
from wowbot.skills import (CombatRuntimeRunner, CombatSkill, InteractionRuntimeRunner, InteractSkill,
                           DefendWaitSkill, LootRuntimeRunner, LootSkill, SearchSkill,
                           FieldTurnInSkill, MovementSkillRunner, ObjectUseSkill, QuestDialogSkill,
                           TargetSkill, VisualApproachSkill, VisualRuntimeRunner)
from wowbot.verification import QuestProgressVerifier
from .camera_controller import CameraController
from .autonomy_loop import AutonomousLoop
from .goal_manager import GoalManager
from .quest_runtime import QuestExecutionRuntime
from .runtime_scheduler import BrainScheduler
from .status_projection import AgentStatusProjection
from .observation_ingestion import ObservationIngestion
from .terminal_result import TerminalResultProcessor
from .quest_terminal import QuestTerminalProcessor
from .navigation_terminal import NavigationTerminalProcessor
from .recovery_planning import RecoveryPlanner
from .planning_orchestration import PlanningOrchestrator
from .execution_bookkeeping import ExecutionBookkeeper
from .outcome_bookkeeping import AttemptOutcomeBookkeeper
from .engine_runtime_projection import (
    active_skill_snapshot, movement_visual_interrupt, visual_control_observation_id,
)
from .active_skill_supervision import ActiveSkillSupervisor
from .action_launch import ActionLaunchCoordinator
from .navigation_planning import NavigationProposalAdapter
from .passive_wait import PassiveWaitBudget
from wowbot.runtime import (
    ActiveSkillRuntime, EventBus, FailureManager, FailureReason, HealthMonitor, Intent,
    LoopGuard, M0SkillDispatcher, RetryPolicy, Supervisor, SupervisorDirectiveKind,
    TimeoutPolicy, FreshnessGate, FreshnessDecisionKind, StructuredLogger, PerformanceMonitor,
    measure_runtime_tick, world_entity_id, VerificationEngine,
)
from wowbot.runtime import SkillExecutor, StateInvalidationPolicy
from wowbot.skills import InstructedSpellSkill, QuestItemSkill, QuestToolSkill
from wowbot.execution import CommandDispatcher
from .engine_control import EngineControlMixin, MOVEMENT_SKILLS
from .engine_finish import EngineFinishMixin


def _addon_exports_death(state: dict) -> bool:
    """Addon 0.9.45+ exports the death popup/corpse (on the slow lane)."""
    try:
        version = tuple(int(part) for part in str(state.get("addon_version") or "").split("-")[0].split("."))
    except ValueError:
        return False
    return version >= (0, 9, 45)


class AutonomousAgent(EngineFinishMixin, EngineControlMixin):
    """Single closed loop shared by questing, resources, exploration and movement."""
    DEATH_EXPORT_GRACE_SECONDS = 10.

    def __init__(self, executor, bindings=None, memory=None, reasoner=None, entity_memory=None,
                 navmesh=None):
        self.executor, self.memory, self.reasoner = executor, memory, reasoner
        self.command_dispatcher = CommandDispatcher(executor)
        self.world = WorldModel(memory.sensor_weight if memory else None,
                                memory.save_world_relation if memory else None,
                                memory.save_event_record if memory else None,
                                entity_memory)
        self.registry = SkillRegistry(bindings)
        from .quest_attempt_memory import QuestAttemptMemory
        self.quest_attempt_memory = QuestAttemptMemory(); self.planner = Planner(self.registry, memory, self.quest_attempt_memory)
        self.navigation = NavigationService(bindings, navmesh=navmesh)
        self.movement_skill_runner = MovementSkillRunner(self.navigation)
        self.navigation_terminal = NavigationTerminalProcessor(self.navigation)
        self.target_skill = TargetSkill()
        self.interact_skill = InteractSkill()
        self.combat_skill = CombatSkill(bindings)
        self.defend_wait_skill = DefendWaitSkill()
        self.combat_runtime = CombatRuntimeRunner(self.navigation, self.combat_skill)
        self.loot_skill = LootSkill()
        self.loot_runtime = LootRuntimeRunner(self.navigation, self.loot_skill)
        self.object_use_skill = ObjectUseSkill()
        self.quest_dialog_skill = QuestDialogSkill()
        self.field_turnin_skill = FieldTurnInSkill(self.quest_dialog_skill)
        self.quest_tool_skill = QuestToolSkill(bindings)
        self.quest_item_skill = QuestItemSkill(bindings)
        self.instructed_spell_skill = InstructedSpellSkill(bindings)
        self.m0_skills = M0SkillDispatcher(target=self.target_skill, interact=self.interact_skill,
                                            combat=self.combat_skill, defend_wait=self.defend_wait_skill,
                                            loot=self.loot_skill,
                                            object_use=self.object_use_skill,
                                            quest_dialog=self.quest_dialog_skill,
                                            field_turnin=self.field_turnin_skill,
                                            quest_tool=self.quest_tool_skill,
                                            quest_item=self.quest_item_skill,
                                            instructed_spell=self.instructed_spell_skill)
        self.verification_engine = VerificationEngine()
        self.quest_progress_verifier = QuestProgressVerifier()
        self.visual_approach_skill = VisualApproachSkill(bindings)
        self.interaction_runtime = InteractionRuntimeRunner(
            self.navigation, self.interact_skill, self.visual_approach_skill)
        self.search_skill = SearchSkill(bindings)
        self.visual_runtime = VisualRuntimeRunner(
            self.search_skill, self.visual_approach_skill)
        self.active_skill_supervisor = ActiveSkillSupervisor(
            m0_skills=self.m0_skills,
            verification_engine=self.verification_engine,
            interaction_runtime=self.interaction_runtime,
            combat_runtime=self.combat_runtime,
            loot_runtime=self.loot_runtime,
            registry=self.registry,
            movement_runtime=self.movement_skill_runner,
            visual_runtime=self.visual_runtime)
        self.skill_executor = SkillExecutor(
            registry=self.registry, navigation=self.navigation,
            target_skill=self.target_skill, interact_skill=self.interact_skill,
            m0_skills=self.m0_skills, search_skill=self.search_skill,
            visual_approach_skill=self.visual_approach_skill)
        self.action_launcher = ActionLaunchCoordinator(
            self.skill_executor, self.m0_skills, self.verification_engine)
        self.camera = CameraController()
        self.autonomy = AutonomousLoop()
        self._movement_segment_baseline = None
        self.goal: Goal | None = None
        self.mode = Mode.MANUAL
        # One canonical running-action authority. `pending` below is a
        # compatibility projection only while the old engine call sites are
        # migrated; it stores no independent state.
        self.active_skill = ActiveSkillRuntime()
        self.events = EventBus()
        self.health_monitor = HealthMonitor()
        self.performance_monitor = PerformanceMonitor()
        self.observation_ingestion = ObservationIngestion()
        self.structured_logger = StructuredLogger()
        self.freshness_gate = FreshnessGate()
        self.state_invalidation = StateInvalidationPolicy()
        self._invalidation_context: dict | None = None
        self.supervisor = Supervisor()
        self.timeouts = TimeoutPolicy()
        self.retries = RetryPolicy()
        self.failure_manager = FailureManager(self.retries, self.timeouts)
        self.loop_guard = LoopGuard()
        self.terminal_results = TerminalResultProcessor(self.failure_manager, self.loop_guard)
        self.last_decision: dict = {}
        self.last_result: dict = {}
        self.failures: dict[str, int] = {}
        self.lock = threading.RLock()
        self.executed_observation = None
        self.generation = 0
        self.last_plan_signature = None
        self.current_plan: Plan | None = None
        self.recovery_for = None
        self.action_budget = None
        self.approach_counts = {}
        self.recovery_planner = RecoveryPlanner()
        self.navigation_proposals = NavigationProposalAdapter(
            self.navigation, self.registry, self.planner.map_search_policy)
        self._last_supervisor_tick: float | None = None
        self.episode_id = None
        self.goals = GoalManager(memory)
        self.planning_orchestrator = PlanningOrchestrator(
            self.planner, self.goals, self.registry, self.supervisor,
            self.autonomy, self.reasoner,
            navigation_adapter=self.navigation_proposals,
            recovery_planner=self.recovery_planner)
        self.execution_bookkeeper = ExecutionBookkeeper()
        self.outcome_bookkeeper = AttemptOutcomeBookkeeper()
        self.quest_runtime = QuestExecutionRuntime(self.quest_attempt_memory)
        self.quest_terminal = QuestTerminalProcessor(
            self.quest_progress_verifier, self.quest_runtime, self.planner.quest)
        self.brain_scheduler = BrainScheduler()
        self.passive_wait = PassiveWaitBudget()
        self._sensor_health_cache = (-1e9, [])
        self._memory_metrics_cache = (-1e9, {})
        self._autonomy_event_cursor = 0
        self._last_movement_assessment: tuple[str, str] | None = None
        self._fast_control_updates = 0
        self._fast_control_dispatches = 0
        self._fast_control_terminal = None
        # The failed REACH intent is retained as high-level context only. It
        # contains no held input state and is revalidated before one post-
        # recovery resume attempt is offered to the normal planner boundary.
        self._recovery_resume: Proposal | None = None
        self._recovery_resume_ready = False

    def _reset_quest_runtime(self) -> None:
        self.quest_attempt_memory.reset_execution_failures(); self.quest_runtime = QuestExecutionRuntime(self.quest_attempt_memory)
        self.quest_terminal = QuestTerminalProcessor(self.quest_progress_verifier, self.quest_runtime, self.planner.quest)
    @property
    def pending(self) -> Attempt | None:
        """Compatibility read view of the canonical ActiveSkillRuntime."""
        return self.active_skill.attempt

    @property
    def navigator(self):
        """Temporary diagnostic/test projection; NavigationService owns it."""
        return self.navigation.route_knowledge

    @property
    def movement(self):
        """Temporary diagnostic/test projection; NavigationService owns it."""
        return self.navigation.movement_controller

    @property
    def _stationary_position(self):
        """Compatibility projection; RecoveryPlanner owns watchdog state."""
        return self.recovery_planner.stationary_position

    @_stationary_position.setter
    def _stationary_position(self, value) -> None:
        self.recovery_planner.stationary_position = value

    @property
    def _stationary_since(self):
        """Compatibility projection; RecoveryPlanner owns watchdog state."""
        return self.recovery_planner.stationary_since

    @_stationary_since.setter
    def _stationary_since(self, value) -> None:
        self.recovery_planner.stationary_since = value

    @property
    def vision_seek(self):
        """Read-only diagnostics projection; active search state is canonical."""
        return self.search_skill

    @property
    def visual_approach(self):
        """Read-only diagnostics projection; active approach state is canonical."""
        return self.visual_approach_skill

    @pending.setter
    def pending(self, attempt: Attempt | None) -> None:
        if attempt is None:
            # Normal terminal completion calls ActiveSkillRuntime.finish()
            # directly so it can preserve a typed terminal result.  This
            # branch is for explicit cancellation/reset only.
            if self.active_skill.exists:
                self.active_skill.cancel(time.monotonic())
            self.active_skill.finalize()
            return
        if self.active_skill.exists:
            raise RuntimeError("A second active skill cannot replace the running skill")
        proposal = attempt.proposal
        self.active_skill.start(
            intent=Intent(proposal.skill, proposal.parameters,
                          world_entity_id(proposal.parameters.get("guid")),
                          str(proposal.parameters.get("objective_id") or "") or None),
            attempt=attempt, now=attempt.started_at, before_snapshot=attempt.baseline,
            skill_context={"plan_id": attempt.plan_id, "action_id": attempt.action_id,
                           "world_snapshot_version": self.world.revision},
        )

    @measure_runtime_tick
    def tick(self, payload: dict | None, now: float, supplemental: tuple[Observation, ...] = ()) -> dict:
        with self.lock:
            if self.memory:
                self.memory.flush_world_relations(force=False)
            generation = self.generation
            primary = self.observation_ingestion.primary(payload, now)
            if self.observation_ingestion.session_changed(self.world.session_id, primary):
                self._handle_session_change(now)
            ingestion = self.observation_ingestion.ingest(self.world, primary, supplemental)
            if self.memory and ingestion.durable:
                self.memory.observe_many(ingestion.durable)
            self._apply_state_invalidations(now)
            self.camera.observe(self.world.state.get("camera_state") or {}, now)
            freshness = self.freshness_gate.evaluate(
                fresh=self.world.fresh(now), detail_stale=self.world.detail_snapshot_stale(now),
                pending_skill=(self.pending.proposal.skill if self.pending else None),
                full_ai=self.mode == Mode.FULL_AI,
                player_present=self.world.state.get("player_present", True) is not False,
                latest_received=(self.world.last_received if self.world.latest else None), now=now)
            if freshness.kind is FreshnessDecisionKind.WAIT_CAMERA_DETAIL:
                stop_movement = getattr(self.executor, "stop_movement", None)
                if stop_movement:
                    stop_movement()
                self.last_decision = {"skill": "WAIT",
                    "reason": "awaiting_fresh_telemetry_after_camera", "receive_gap": freshness.receive_gap,
                    "pending_skill": self.pending.proposal.skill,
                    "detail_snapshot_stale": True}
                return self.status(now)
            if freshness.kind is FreshnessDecisionKind.WAIT_CAMERA_TELEMETRY:
                    # The bounded view-rotation pulse has already released its key/button.
                    # Preserve its verification/commitment while the paged
                    # addon snapshot catches up, but emit no further input.
                    stop_movement = getattr(self.executor, "stop_movement", None)
                    if stop_movement:
                        stop_movement()
                    self.last_decision = {"skill": "WAIT",
                        "reason": "awaiting_fresh_telemetry_after_camera",
                        "receive_gap": freshness.receive_gap,
                        "pending_skill": self.pending.proposal.skill}
                    return self.status(now)
            if freshness.kind is FreshnessDecisionKind.STALE_TELEMETRY:
                if self.mode == Mode.FULL_AI and freshness.suspension_started:
                    self.executor.stop()
                self.last_decision = {
                    "skill": "WAIT",
                    "reason": ("telemetry_outage_manual_demote"
                               if freshness.demote_to_manual
                               else "telemetry_suspended_waiting_for_stable_recovery"),
                    "receive_gap": freshness.receive_gap,
                    "input_authority": "REVOKED",
                }
                if freshness.demote_to_manual:
                    self.set_mode(Mode.MANUAL)
                return self.status(now)
            if freshness.resume_input_authority and self.mode == Mode.FULL_AI:
                # STALE handling deliberately disarms the executor.  Restore
                # authority only after the freshness gate has seen its stable
                # recovery sequence; the executor still checks selected-PID
                # foreground immediately before every command.
                arm = getattr(self.executor, "arm", None)
                if arm:
                    arm()
                if (self.last_decision or {}).get("reason") ==                         "telemetry_suspended_waiting_for_stable_recovery":
                    # The resumed skill may not replan for a while; do not
                    # keep reporting the suspension as the current decision.
                    self.last_decision = {
                        "skill": self.pending.proposal.skill if self.pending else "WAIT",
                        "reason": "telemetry_recovered_input_authority_restored"}
            if self.goal is not None and self.memory and not self.episode_id:
                self.episode_id = self.memory.start_episode(self.goal, self.world.session_id,
                                                            self.world.state, now)
            if self.world.latest:
                for feature in self.navigation.observe_topology(self.world.state,
                                                               self.world.latest.observation_id, now):
                    self._record(now, "TOPOLOGY_STATUS_CHANGED", feature)
            if self.goal is None or self.mode in {Mode.MANUAL, Mode.STOPPED}:
                return self.status(now)
            self.goals.sync_world(self.world.quest_model, now)
            self.quest_runtime.observe(self.goal, self.world.quest_model, self.world.state, now,
                                       locator=self.planner.quest.objective_locator)
            if self.goal.status == "COMPLETED":
                self.set_mode(Mode.MANUAL)
                return self.status(now)
            directive = self.supervisor.evaluate(self.world.state, self.active_skill.state, now)
            self._last_supervisor_tick = now
            dead_block = (directive.kind is SupervisorDirectiveKind.BLOCK
                          and directive.reason is FailureReason.PLAYER_DEAD)
            if not dead_block:
                self.__dict__.pop("_death_seen_at", None)
            death_seen_at = (self.__dict__.setdefault("_death_seen_at", now)
                             if dead_block else None)
            # The death popup/corpse export rides the slow (~2 s) STATE lane:
            # live 14:14:13 the first FULL_AI tick after a start saw the
            # ghost before it and demoted to MANUAL.  Wait briefly for it.
            death_recovery = dead_block and (
                isinstance(self.world.state.get("death_recovery"), dict)
                or (_addon_exports_death(self.world.state)
                    and now - float(death_seen_at) < self.DEATH_EXPORT_GRACE_SECONDS))
            death_step_running = bool(
                death_recovery and self.pending is not None
                and (self.pending.proposal.skill == "DEATH_RECOVERY"
                     or self.pending.proposal.parameters.get("purpose") == "CORPSE_RUN"))
            if directive.event:
                self.events.publish(directive.event)
                self._flush_active_skill_events()
            if directive.cancel_active and self.pending and not death_step_running:
                if directive.suspend_active and self.active_skill.state is not None:
                    suspended_event = self.supervisor.suspend(
                        self.active_skill.state, now, directive.reason)
                    if suspended_event:
                        self.events.publish(suspended_event)
                        self._flush_active_skill_events()
                # Preemption is an ownership boundary: release the physical
                # movement lease and the NavigationService controller before
                # finalizing the interrupted skill or admitting combat.
                self.command_dispatcher.stop_movement()
                self.navigation.cancel_movement()
                self._finish(Outcome.CANCELLED, directive.reason.value.lower(), now)
            if death_recovery and not death_step_running:
                # User 2026-10-03: release spirit, run back, resurrect.  The
                # addon (0.9.45) exports the popup button and corpse position;
                # the planner proposes only death-recovery steps meanwhile.
                self.last_decision = {"skill": "WAIT", "reason": "death_recovery",
                                      "supervisor": "death_recovery"}
            if directive.kind is SupervisorDirectiveKind.BLOCK and not death_recovery:
                self.executor.stop()
                checkpoint = self.supervisor.mark_safety_pause(
                    directive.reason, now,
                    goal_id=self.goal.goal_id if self.goal is not None else None)
                self._record(now, "SAFETY_PAUSED", {
                    "reason": checkpoint.reason.value,
                    "goal_id": checkpoint.goal_id,
                    "required_condition": checkpoint.required_condition,
                })
                self.last_decision = {"skill": "WAIT", "reason": directive.reason.value,
                                      "supervisor": "blocking_interrupt",
                                      "recovery_required": checkpoint.required_condition}
                self.set_mode(Mode.MANUAL)
                return self.status(now)
            if self.pending:
                active_skill = self.pending.proposal.skill
                if active_skill not in MOVEMENT_SKILLS | {
                        "SEEK_VISUAL_CUE", "VISUAL_APPROACH"}:
                    self.autonomy.on_verifying(now)
                    self.active_skill.set_phase("VERIFY", now)
                    self.active_skill.begin_verification(now)
                visual_interrupt = (
                    movement_visual_interrupt(self.pending, self.world.state)
                    if active_skill in MOVEMENT_SKILLS else None)
                if (visual_interrupt and
                        visual_interrupt.get("kind") == "QUEST_ROUTE_VISUAL_CUE"):
                    self.planner.arm_movement_visual_handoff(visual_interrupt, now)
                supervision = self.active_skill_supervisor.step(
                    self.pending, self.active_skill.state, self.world,
                    world_observation_id=self.world.latest.observation_id,
                    visual_observation_id=visual_control_observation_id(self.world),
                    now=now, segment_baseline=self._movement_segment_baseline,
                    reference_reach_interrupt=visual_interrupt)
                if self._apply_active_supervision(supervision, now):
                    return self.status(now)
            if self.action_budget == 0:
                self.set_mode(Mode.MANUAL)
                self.last_decision = {"skill": "WAIT", "reason": "bounded_live_test_completed"}
                return self.status(now)
            if self.goals.completion_condition_verified(self.world, now):
                self.goals.complete("goal_completion_condition_verified", now)
                self.set_mode(Mode.MANUAL)
                self._record(now, "GOAL_COMPLETED", asdict(self.goal))
                if self.memory:
                    self.memory.save_goal(self.goal)
                    self.memory.finish_episode(self.episode_id, self.world.state, now, "SUCCESS",
                                               {"goal_id": self.goal.goal_id,
                                                "completed_steps": self.goal.completed_steps,
                                                "failures": self.goal.failures})
                    self.episode_id = None
                return self.status(now)
            should_plan, brain_trigger = self.brain_scheduler.should_plan(
                self.world.state, self.goal, now)
            if not should_plan:
                return self.status(now)
            self.world.set_runtime_context(
                goal=self.goal, commitment=self.autonomy.commitment,
                active_skill=active_skill_snapshot(self.active_skill), last_result=self.last_result,
                primary_quest=self.quest_runtime.snapshot(now),
                quest_failure_memory=self.quest_runtime.failure_memory.snapshot(now))
            planning_world = self.world.planning_snapshot(now)
            planning_cycle = self.planning_orchestrator.choose(
                self.goal, self.world, planning_world, now,
                recovery_resume=self._recovery_resume,
                recovery_resume_ready=self._recovery_resume_ready)
            proposal, proposals = planning_cycle.proposal, list(planning_cycle.proposals)
            self._recovery_resume = planning_cycle.recovery_resume
            self._recovery_resume_ready = planning_cycle.recovery_resume_ready
            for event_type, event_payload in planning_cycle.events:
                self._record(now, event_type, event_payload)
            reasoning_observation = planning_cycle.reasoning_observation
            if (reasoning_observation and self.world.ingest(reasoning_observation)
                    and self.memory):
                self.memory.observe(reasoning_observation)
            if (proposal.skill in {"APPROACH_TARGET", "VISUAL_APPROACH"}
                    # 24 -> 10 on 2026-09-13: live-observed a VISUAL_APPROACH
                    # loop against one guid running ~50 attempts over ~2
                    # minutes (all "visual_track_lost") before this was the
                    # only thing that finally stopped it. autonomy_loop.py
                    # now blocks VISUAL_APPROACH from re-matching after 10s
                    # of continuous failure on the same commitment, so this
                    # remains only the coarser, cross-commitment backstop --
                    # tightened so its own worst case is tens of seconds, not
                    # minutes, if that inner mechanism doesn't catch it.
                    and self.approach_counts.get(proposal.parameters.get("guid"), 0) >= 10):
                self.set_mode(Mode.MANUAL)
                self.last_decision = {"skill": "WAIT", "reason": "target_approach_budget_exhausted"}
                return self.status(now)
            planning_resolution = self.planning_orchestrator.resolve(
                planning_cycle, goal=self.goal, world=self.world,
                planning_world=planning_world, mode=self.mode,
                replan_revision=self.autonomy.replan_revision, now=now,
                observation_id=self.world.latest.observation_id,
                current_plan=self.current_plan,
                last_signature=self.last_plan_signature,
                last_result=self.last_result, navigation=self.navigation,
                failures=self.failures,
                current_recovery_for=self.recovery_for)
            proposal = planning_resolution.proposal
            if proposal.skill == "WAIT":
                wait = self.passive_wait.observe(
                    proposal,
                    observation_id=self.world.latest.observation_id,
                    now=now)
                proposal = wait.proposal
                if wait.first_expiration:
                    # Differently-worded passive WAIT decisions for this
                    # uninterrupted subgoal share one wall-clock budget. On
                    # expiry release stale commitment ownership and retry the
                    # best already-vetted non-WAIT proposal once through the
                    # ordinary navigation/recovery adapters. No input bypasses
                    # SkillExecutor and no new domain action is invented here.
                    self._record(now, "PASSIVE_WAIT_BUDGET_EXHAUSTED", {
                        "elapsed": wait.elapsed,
                        "budget_seconds": self.passive_wait.seconds,
                        "fresh_observations": wait.fresh_observations,
                        "reason": proposal.reason,
                        "waiting_for": proposal.parameters.get("waiting_for"),
                        "candidate_skills": [item.skill for item in proposals],
                    })
                    self.autonomy.reset(now, "PASSIVE_WAIT_BUDGET_EXHAUSTED")
                    self.last_plan_signature = None
                    retry = next((item for item in proposals
                                  if item.skill != "WAIT"
                                  and self.registry.available(item, self.world)), None)
                    if retry is not None:
                        forced = self.autonomy.choose(
                            proposals, retry, self.goal, self.world, now)
                        forced_cycle = replace(planning_cycle, proposal=forced)
                        planning_resolution = self.planning_orchestrator.resolve(
                            forced_cycle, goal=self.goal, world=self.world,
                            planning_world=planning_world, mode=self.mode,
                            replan_revision=self.autonomy.replan_revision, now=now,
                            observation_id=self.world.latest.observation_id,
                            current_plan=self.current_plan,
                            last_signature=self.last_plan_signature,
                            last_result=self.last_result,
                            navigation=self.navigation,
                            failures=self.failures,
                            current_recovery_for=self.recovery_for)
                        proposal = planning_resolution.proposal
                        self._record(now, "PASSIVE_WAIT_FORCED_REPLAN", {
                            "selected_skill": forced.skill,
                            "resolved_skill": proposal.skill,
                            "selected_reason": forced.reason,
                        })
                        if proposal.skill == "WAIT":
                            proposal = self.passive_wait.observe(
                                proposal,
                                observation_id=self.world.latest.observation_id,
                                now=now).proposal
            self.recovery_for = planning_resolution.recovery_for
            # WAIT decoration and the bounded forced replan may change the
            # selected proposal after resolve() built its preview. Rebuild
            # from the final proposal so PLAN, GUI and execution agree.
            plan_update = self.planning_orchestrator.build_plan(
                self.goal, proposal, proposals, mode=self.mode,
                replan_revision=self.autonomy.replan_revision, now=now,
                observation_id=self.world.latest.observation_id,
                planning_world=planning_world,
                current_plan=self.current_plan,
                last_signature=self.last_plan_signature)
            self.current_plan, self.last_plan_signature = (
                plan_update.plan, plan_update.signature)
            if plan_update.changed:
                self._record(now, "PLAN", asdict(self.current_plan))
            self.last_decision = {**asdict(proposal), "parameters": proposal.parameters,
                                  "goal_id": self.goal.goal_id,
                                  "plan_id": self.current_plan.plan_id,
                                  "subgoal_id": self.current_plan.subgoal_id,
                                  "brain_trigger": brain_trigger}
            if self.mode != Mode.FULL_AI or proposal.skill == "WAIT" or self.executed_observation == self.world.latest.observation_id:
                return self.status(now)
            try:
                prepared = self.action_launcher.prepare(
                    proposal, self.world, self.world.latest.observation_id, now)
                commands = prepared.commands
                if prepared.set_segment_baseline:
                    self._movement_segment_baseline = self.world.state.copy()
                if prepared.camera_parameters is not None:
                    from .camera_controller import camera_gesture
                    self.camera.begin(camera_gesture(prepared.camera_parameters), now)
                # SEEK_VISUAL_CUE may deliberately wait for the next fresh
                # tracker frame before issuing movement. It still owns a
                # persistent attempt; otherwise commitment remains without a
                # running skill and the planner falls back into INSPECT loops.
                # Live-observed 2026-09-14: MOVEMENT_SKILLS/VISUAL_APPROACH
                # need the exact same exemption. command() legitimately
                # returns no commands the instant start()'s own internal
                # observe() call already lands on a terminal phase (e.g.
                # ReachMovementController reaching ARRIVED because the
                # destination was already within stop_distance, or
                # VisualApproachController mid-OCCLUDED-scan) -- but start()'s
                # return value is discarded, so that terminal result was never
                # reported. Returning early here left self.pending at None,
                # so the very next tick just called start() fresh again with
                # the same outcome: MOVE (or VISUAL_APPROACH) displayed
                # unchanged, zero displacement, for as long as 64s live before
                # the user hit the F12 kill switch. Falling through instead
                # creates the Attempt below with empty commands (already
                # handled at "if not commands: pass"), so the *next* tick's
                # already-pending branch runs observe() again and actually
                # reports the terminal outcome through _finish().
                if not self.action_launcher.may_install(proposal, commands):
                    return self.status(now)
                if self.generation != generation or self.mode != Mode.FULL_AI:
                    return self.status(now)
                launch = self.action_launcher.install(
                    proposal, tuple(commands), active_skill=self.active_skill,
                    world=self.world, goal=self.goal,
                    current_plan=self.current_plan, timeouts=self.timeouts,
                    memory=self.memory,
                    visual_observation_id=visual_control_observation_id(self.world),
                    now=now)
                attempt, commands = launch.attempt, launch.commands
                self.passive_wait.reset("non_wait_skill_started")
                action_id, prediction = attempt.action_id, attempt.prediction
                if launch.immediate_terminal is not None:
                    terminal = launch.immediate_terminal
                    self._finish(terminal.outcome, terminal.reason, now,
                                 typed_reason=terminal.typed_reason)
                    return self.status(now)
                self.autonomy.on_execute(proposal, now)
                resume_event = self.supervisor.consume_resume(
                    str(proposal.parameters.get("_resume_token") or ""), now)
                if resume_event:
                    self.events.publish(resume_event)
                self._record(now, "ACTION_INTENT", attempt.to_dict())
                if self.memory:
                    self.memory.record_episode_step(self.episode_id, now, "ACTION_INTENT", attempt.to_dict())
                action_loop = None
                for command in commands:
                    decision = self.loop_guard.observe_action(command.binding, now)
                    if (decision.level == "CONFIRMED"
                            or decision.level == "SUSPECTED"
                            and (action_loop is None or action_loop.level == "NONE")):
                        action_loop = decision
                if action_loop is not None and action_loop.level != "NONE":
                    self.supervisor.notify_loop(action_loop, now)
                    self.planner.blocked_until[proposal.key] = now + (
                        self.retries.max_backoff_seconds
                        if action_loop.level == "CONFIRMED" else .5)
                    self._record(now, f"LOOP_{action_loop.level}", {
                        "signature": action_loop.signature,
                        "count": action_loop.count,
                        "kind": action_loop.kind,
                        "skill": proposal.skill,
                    })
                    # The loop was recognized before physical dispatch. The
                    # Agent owns cancellation/finalization; LoopGuard and
                    # Supervisor still never touch the input backend.
                    self._finish(Outcome.CANCELLED,
                                 f"movement_loop_{action_loop.level.lower()}", now,
                                 typed_reason=FailureReason.INTERRUPTED)
                    return self.status(now)
                if not commands:
                    pass
                else:
                    self.command_dispatcher.dispatch(
                        commands, launch.dispatch_lane,
                        correlation_id=attempt.action_id)
                self._record(now, "ACTION_EXECUTED", attempt.to_dict())
                self.execution_bookkeeper.record(
                    proposal, now, planner=self.planner,
                    approach_counts=self.approach_counts)
                if self.action_budget is not None:
                    self.action_budget -= 1
                self.executed_observation = self.world.latest.observation_id
                if self.generation != generation or self.mode != Mode.FULL_AI:
                    prediction.status = Outcome.CANCELLED
                    self._record(now, "ACTION_CANCELLED", {"action_id": action_id})
                    return self.status(now)
                if self.pending is None:
                    self.pending = attempt
                self._flush_active_skill_events()
                self.world.predictions.append(prediction)
            except Exception as error:
                self.last_result = {"outcome": "FAILURE", "reason": str(error), "skill": proposal.skill}
                self._record(now, "EXECUTOR_FAILURE", self.last_result)
                self.set_mode(Mode.MANUAL)
            return self.status(now)

    def status(self, now):
        return AgentStatusProjection.build(self, now)
