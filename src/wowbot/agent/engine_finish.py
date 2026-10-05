"""AutonomousAgent skill-attempt finalisation (outcome bookkeeping, recovery, events).

Split out of engine.py (2026-10-05, module-size gate V4-083); unchanged.
"""
from __future__ import annotations
from dataclasses import asdict
from .models import Outcome
from .memory_terminal import MemoryTerminalProcessor
from wowbot.runtime import FailureReason, RuntimeEvent


class EngineFinishMixin:
    """Methods of AutonomousAgent (engine.py); moved verbatim."""

    def _finish(self, outcome, reason, now, *, typed_reason: FailureReason | None = None):
        attempt = self.pending
        if attempt is None:
            return
        terminal_bookkeeping = self.execution_bookkeeper.record_terminal(
            attempt, outcome, reason, now, planner=self.planner,
            world=self.world, recovery_resume=self._recovery_resume)
        if terminal_bookkeeping.recovery_resume is not self._recovery_resume:
            self._recovery_resume = terminal_bookkeeping.recovery_resume
            self._recovery_resume_ready = False
        combat_context = ((self.active_skill.state.skill_context.get("combat") or {})
                          if self.active_skill.state else {})
        terminal = self.terminal_results.assess(
            attempt, outcome, reason, now,
            latest_observation_id=(self.world.latest.observation_id if self.world.latest else None),
            typed_reason=typed_reason, last_binding=combat_context.get("last_binding"),
            current_state=self.world.state)
        failure_type = terminal.failure_type
        normalized_failure_reason = terminal.failure_reason
        failure_decision = terminal.failure_decision
        loop_decision = terminal.loop_decision
        self.planner.record_terminal_decision(
            attempt.proposal, self.goal, self.world, failure_decision,
            success=outcome == Outcome.SUCCESS, now=now)
        self.last_result = terminal.result_projection
        if loop_decision is not None and loop_decision.level != "NONE":
            self.supervisor.notify_loop(loop_decision, now)
            event = RuntimeEvent(
                f"LOOP_{loop_decision.level}", now,
                {"signature": loop_decision.signature, "count": loop_decision.count,
                 "kind": loop_decision.kind,
                 "matching_signatures": list(loop_decision.matching_signatures),
                 "skill": attempt.proposal.skill},
                event_id=f"loop:{loop_decision.signature}:{loop_decision.count}",
                source="LOOP_GUARD", correlation_id=attempt.action_id,
            )
            (self.events.publish_critical(event) if loop_decision.level == "CONFIRMED"
             else self.events.publish(event))
            self._record(now, event.event_type, event.metadata)
        if loop_decision is not None and loop_decision.level == "CONFIRMED":
            self.planner.blocked_until[attempt.proposal.key] = now + self.retries.max_backoff_seconds
            self.autonomy.reset(now, "LOOP_CONFIRMED")
        params = attempt.proposal.parameters
        quest_terminal = self.quest_terminal.process(
            attempt, outcome, reason, self.world.state, self.goal, now)
        quest_credit = quest_terminal.credit
        if quest_credit is not None:
            self.last_result["quest_credit"] = {
                "confirmed": quest_credit.success, "evidence": list(quest_credit.evidence)}
        for event_type, event_payload in quest_terminal.events:
            self._record(now, event_type, event_payload)
        verification = terminal.verification
        self.world.verifications.append(verification)
        self._record(now, "VERIFICATION", asdict(verification))
        if self.memory:
            self.memory.record_episode_step(self.episode_id, now, "VERIFICATION", asdict(verification))
        navigation_terminal = self.navigation_terminal.process(
            attempt, outcome, reason, normalized_failure_reason,
            attempt.baseline, self.world.state,
            latest_observation_id=(self.world.latest.observation_id if self.world.latest else None),
            now=now)
        for event_type, event_payload in navigation_terminal.events:
            self._record(now, event_type, event_payload)
        if navigation_terminal.recovery_succeeded and self._recovery_resume is not None:
            self._recovery_resume_ready = True
        self.outcome_bookkeeper.apply(
            attempt, outcome, reason, now, goal=self.goal, world=self.world,
            planner=self.planner, failures=self.failures,
            failure_manager=self.failure_manager, loop_guard=self.loop_guard,
            retries=self.retries, failure_decision=failure_decision)
        if outcome == Outcome.FAILURE and terminal.prediction_error is not None:
            self.world.record_prediction_error(terminal.prediction_error)
            self._record(now, "PREDICTION_ERROR", asdict(terminal.prediction_error))
        if self.memory and outcome in {Outcome.SUCCESS, Outcome.FAILURE}:
            memory_terminal = MemoryTerminalProcessor.process(
                attempt, outcome, reason, self.world.state, self.goal, now, verification,
                memory=self.memory, contract=self.registry.contracts[attempt.proposal.skill],
                latest_observation_id=(self.world.latest.observation_id if self.world.latest else None),
                last_received=self.world.last_received, session_id=self.world.session_id)
            if memory_terminal.inspection_quality is not None:
                self.last_result["inspection_quality"] = memory_terminal.inspection_quality
            for event_type, event_payload in memory_terminal.events:
                self._record(now, event_type, event_payload)
        if outcome in {Outcome.SUCCESS, Outcome.FAILURE}:
            self.goals.outcome(
                attempt.proposal, outcome == Outcome.SUCCESS, reason, now,
                failure_decision=failure_decision)
        if (failure_decision is not None
                and failure_decision.replan_required):
            self.autonomy.reset(
                now, f"FAILURE_{failure_decision.escalation_stage.value}")
        self.autonomy.outcome(attempt.proposal, outcome == Outcome.SUCCESS, reason, self.world, now)
        self.active_skill.finish(terminal.skill_result, now)
        self._flush_active_skill_events()
        self.active_skill.finalize()
