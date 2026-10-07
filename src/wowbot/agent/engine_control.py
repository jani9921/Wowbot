"""AutonomousAgent goal/mode control, event recording, supervision and state invalidation.

Split out of engine.py (2026-10-05, module-size gate V4-083); the methods are
unchanged and still run on the one AutonomousAgent instance.
"""
from __future__ import annotations
from dataclasses import asdict
import time
import uuid
from .models import Goal, Mode, Observation, Outcome
from .engine_runtime_projection import movement_assessment_event, pending_autonomy_events
from .fast_movement_lane import advance_fast_movement
from .session_transition import handle_session_change
from wowbot.runtime import FailureReason
from wowbot.execution import DispatchLane


MOVEMENT_SKILLS = {"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"}


class EngineControlMixin:
    """Methods of AutonomousAgent (engine.py); moved verbatim."""

    def set_goal(self, text: str, now: float, parameters: dict | None = None):
        if self.memory and self.episode_id:
            self.memory.finish_episode(self.episode_id, self.world.state, now, "REPLACED",
                                       {"reason": "goal_replaced"})
            self.episode_id = None
        self.set_mode(Mode.MANUAL)
        self.goal = Goal.parse(text, now, parameters)
        self.goals.set_goal(self.goal, now)
        self.supervisor.clear_resume("goal_replaced")
        self._reset_quest_runtime()
        self.failures.clear()
        self.failure_manager.reset()
        self.planner.blocked_until.clear()
        # Same session and map: the player's own floor stays valid evidence.
        self.navigation.reset(keep_floor=True)
        self.visual_approach_skill.reset_diagnostics()
        self.search_skill.reset_diagnostics()
        self.camera.reset()
        self.autonomy.reset(now, "GOAL_REPLACED")
        self._movement_segment_baseline = None
        self.last_result = {}
        self.last_decision = {}
        self.current_plan = None
        self.recovery_for = None
        self.approach_counts.clear()
        self.freshness_gate.reset()
        self._stationary_position = None
        self._stationary_since = None
        self._last_movement_assessment = None
        self._recovery_resume = None
        self._recovery_resume_ready = False
        self.brain_scheduler.reset()
        self.passive_wait.reset("goal_replaced")
        if self.memory:
            self.memory.save_goal(self.goal)

    def restore_goal(self, goal, now: float):
        """Restore planning state passively; this never arms input."""
        self.set_mode(Mode.MANUAL)
        self.goal = goal
        self.goals.set_goal(goal, now, resume=True)
        self.supervisor.clear_resume("goal_restored")
        self._reset_quest_runtime()
        self.failures.clear()
        self.failure_manager.reset()
        self.current_plan = None
        self.episode_id = None

    def set_mode(self, mode: Mode):
        # Cancellation does not wait for the planner lock or a held key pulse.
        self.mode = Mode(mode)
        self.generation += 1
        self.passive_wait.reset(f"mode_{self.mode.value.lower()}")
        if self.mode != Mode.FULL_AI:
            self.supervisor.clear_resume("mode_changed")
            # Manual/STOP is an explicit user boundary. A prior autonomous
            # recovery may not silently resume its old reach after the user
            # has taken control or re-armed a different task.
            self._recovery_resume = None
            self._recovery_resume_ready = False
            self.executor.stop()
            self.navigation.cancel_movement()
            self.visual_approach_skill.reset_diagnostics()
            self.search_skill.reset_diagnostics()
            self.camera.reset()
            self.autonomy.reset(reason="MODE_CHANGED")
            self._movement_segment_baseline = None
            with self.lock:
                if self.pending:
                    attempt = self.pending
                    attempt.prediction.status = Outcome.CANCELLED
                    attempt.prediction.reason = "mode_changed"
                    # This is deliberately not _finish(): user/manual and
                    # supervisor cancellation must release input and close the
                    # one active skill without teaching the planner that an
                    # interrupted action was an ordinary skill failure.
                    self.active_skill.cancel(time.monotonic(), FailureReason.CANCELLED)
                    self._flush_active_skill_events()
                    self._record(time.monotonic(), "ACTION_CANCELLED", {
                        "action_id": attempt.action_id, "plan_id": attempt.plan_id,
                        "skill": attempt.proposal.skill, "reason": "mode_changed"})
                    self.active_skill.finalize()
        else:
            # A stationary position accumulated while the user was in MANUAL
            # is not stuck evidence.  The global watchdog is only meaningful
            # after this autonomous run has had an opportunity to command
            # movement, so every FULL_AI entry gets an independent baseline.
            self._stationary_position = None
            self._stationary_since = None
            self.freshness_gate.reset()
            if hasattr(self.executor, "arm"):
                self.executor.arm()

    def _record(self, now, kind, payload):
        self.structured_logger.log(now, kind, payload)
        if self.memory:
            self.memory.record(self.world.session_id, now, kind, payload)
        if kind in {"PLAN", "ACTION_INTENT", "ACTION_EXECUTED", "ACTION_CANCELLED", "VERIFICATION"} and self.world.session_id:
            identity = payload.get("plan_id") or payload.get("action_id") or payload.get("verification_id") or uuid.uuid4().hex
            trace = Observation.create({"session_id": self.world.session_id, "timestamp": now,
                "frame_id": f"agent-trace:{kind}:{identity}", "trace_type": kind, "trace": payload,
                "provenance": {"producer": "AutonomousAgent", "independence_group": f"agent-trace:{identity}"}},
                now, "AGENT_TRACE")
            if self.world.ingest(trace) and self.memory:
                self.memory.observe(trace)

    def _flush_active_skill_events(self) -> None:
        for event in self.active_skill.drain_events():
            self.events.publish(event)
        for event in self.events.consume():
            self._record(event.at, event.event_type, event.metadata)

    def _flush_autonomy_events(self):
        for sequence, durable_event_type, event in pending_autonomy_events(
                self.autonomy.lifecycle, self._autonomy_event_cursor):
            if self.world.session_id:
                runtime_observation = Observation.create({
                    "session_id": self.world.session_id,
                    "timestamp": event.get("at") or (self.world.latest.timestamp if self.world.latest else 0.),
                    "frame_id": f"agent-runtime:{sequence}:{durable_event_type}",
                    "event_type": durable_event_type,
                    "payload": event,
                    "provenance": {"producer": "AutonomousLoop",
                                   "independence_group": f"agent-runtime:{sequence}"},
                }, event.get("at") or (self.world.latest.received_at if self.world.latest else 0.),
                    "AGENT_RUNTIME")
                if self.world.ingest(runtime_observation) and self.memory:
                    self.memory.observe(runtime_observation)
            self._autonomy_event_cursor = max(self._autonomy_event_cursor, sequence)

    def _emit_movement_assessment_event(self, assessment, now: float) -> None:
        """Publish movement-state transitions without giving navigation an event bus.

        The movement controller supplies evidence-only assessments; this
        runtime boundary turns a *phase transition* into one traceable event.
        Repeated fast-loop observations of the same phase are deliberately
        coalesced here rather than flooding EventBus.
        """
        attempt = self.pending
        if attempt is None:
            return
        self._last_movement_assessment, event = movement_assessment_event(
            attempt, assessment, self._last_movement_assessment, now)
        if event is None:
            return
        (self.events.publish_critical(event) if event.event_type == "STUCK_DETECTED"
         else self.events.publish(event))
        self._flush_active_skill_events()

    def _apply_active_supervision(self, supervision, now: float) -> bool:
        """Apply inert supervision data while retaining Agent I/O authority."""
        if supervision.movement_assessment is not None:
            self._emit_movement_assessment_event(
                supervision.movement_assessment, now)
        if supervision.next_segment_baseline is not None:
            self._movement_segment_baseline = supervision.next_segment_baseline
        elif supervision.set_segment_baseline:
            self._movement_segment_baseline = self.world.state.copy()
        if supervision.stop_movement:
            stop_movement = getattr(self.executor, "stop_movement", None)
            if stop_movement:
                stop_movement()
            self.navigation.cancel_movement()
        if supervision.terminal_outcome is not None:
            self._finish(
                supervision.terminal_outcome,
                supervision.reason or "active_skill_supervision_failed",
                now, typed_reason=supervision.typed_reason)
            return supervision.return_after_terminal
        if supervision.yield_tick:
            return True
        commands = supervision.commands
        if not commands:
            return True
        try:
            lane = (DispatchLane.MOVEMENT
                    if supervision.movement_lane else DispatchLane.DISCRETE)
            self.command_dispatcher.dispatch(
                commands, lane, correlation_id=self.pending.action_id)
            if supervision.camera_action:
                gesture = next(command for command in commands
                               if command.kind == "CAMERA_PAN")
                self.camera.begin({
                    "camera_action": supervision.camera_action,
                    "x": gesture.x, "y": gesture.y,
                    "duration": gesture.duration,
                }, now)
            self.executed_observation = self.world.latest.observation_id
            if supervision.event_type:
                diagnostics = dict(supervision.diagnostics)
                diagnostics.setdefault(
                    "observation_id", self.world.latest.observation_id)
                if supervision.event_type == "MOVEMENT_CONTROL_UPDATE":
                    diagnostics.update({
                        "plan_id": self.pending.plan_id,
                        "observation_id": self.world.latest.observation_id,
                        "movement": self.navigation.movement_snapshot(),
                    })
                self._record(now, supervision.event_type, {
                    "action_id": self.pending.action_id,
                    "commands": [asdict(command) for command in commands],
                    **diagnostics,
                })
        except Exception as error:
            if supervision.dispatch_failure_terminal:
                self._finish(
                    Outcome.FAILURE,
                    FailureReason.EXECUTOR_FAILURE.value.lower(),
                    now, typed_reason=FailureReason.EXECUTOR_FAILURE)
                self._record(now, "EXECUTOR_FAILURE", {"error": str(error)})
            else:
                self.last_result = {
                    "outcome": "FAILURE", "reason": str(error),
                    "skill": self.pending.proposal.skill,
                }
                self._record(now, "EXECUTOR_FAILURE", self.last_result)
                self.set_mode(Mode.MANUAL)
        return True

    def fast_movement_control(self, payload: dict, now: float) -> dict:
        """Consume one compact FAST sample without running the slow brain loop.

        This is not a second movement controller.  It advances the exact same
        NavigationService and dispatches through the exact same authoritative
        CommandDispatcher used by ``tick()``.  World-model fusion, planning,
        skill completion and durable logging remain on the medium loop.
        """
        with self.lock:
            return advance_fast_movement(self, payload, now, MOVEMENT_SKILLS)

    def _handle_session_change(self, now: float) -> None:
        self.passive_wait.reset("session_changed")
        handle_session_change(self, now)

    def _apply_state_invalidations(self, now: float) -> None:
        """Apply DESIGN-077 transitions without granting policy input access."""
        current = self.state_invalidation.context(self.world.state)
        events = self.state_invalidation.detect(self._invalidation_context, current)
        self._invalidation_context = current
        callbacks = {
            "invalidate_objective": lambda reason: self.quest_runtime.invalidate_selection(
                f"state_invalidation:{reason.lower()}", now),
            "reset_navigation": lambda reason: self.navigation.reset(),
            "reset_camera": lambda reason: self.camera.reset(),
            "reset_commitment": lambda reason: self.autonomy.reset(
                now, f"STATE_INVALIDATION_{reason}"),
            "reset_map_search": lambda reason: self.planner.map_search_policy.reset_session(),
        }
        for event in events:
            decision = self.state_invalidation.decision(event)
            if decision.cancel_active and self.pending is not None:
                self.command_dispatcher.stop_movement()
                self._finish(
                    Outcome.CANCELLED, f"state_invalidated:{event.value.lower()}", now,
                    typed_reason=FailureReason.CANCELLED)
            self.state_invalidation.apply(event, self.world, callbacks)
            self._record(now, "STATE_INVALIDATED", {
                "event": event.value,
                "cancel_active": decision.cancel_active,
                "reset_navigation": decision.reset_navigation,
                "clear_visual_context": decision.clear_visual_context,
                "invalidate_objective": decision.invalidate_objective,
            })
