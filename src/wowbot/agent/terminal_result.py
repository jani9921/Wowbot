"""Canonical terminal assessment for one active-skill attempt."""
from __future__ import annotations

from dataclasses import dataclass
import uuid

from .goal_manager import classify_failure, classify_prediction_error
from .models import Attempt, Outcome, PredictionError, VerificationRecord
from wowbot.runtime.contracts import (FailureReason, SkillResult, SkillStatus,
                                      failure_reason_from_legacy)


@dataclass(frozen=True)
class TerminalAssessment:
    failure_type: str | None
    failure_reason: FailureReason | None
    failure_decision: object | None
    loop_decision: object | None
    result_projection: dict
    verification: VerificationRecord
    skill_result: SkillResult
    prediction_error: PredictionError | None


class TerminalResultProcessor:
    """Build typed terminal records; owns no active-skill or input authority."""

    def __init__(self, failure_manager, loop_guard) -> None:
        self.failure_manager = failure_manager
        self.loop_guard = loop_guard

    def assess(self, attempt: Attempt, outcome: Outcome, reason: str, now: float,
               *, latest_observation_id: str | None,
               typed_reason: FailureReason | None = None,
               last_binding: str | None = None,
               current_state: dict | None = None) -> TerminalAssessment:
        attempt.prediction.status, attempt.prediction.reason = outcome, reason
        failure_type = classify_failure(attempt.proposal.skill, reason) if outcome != Outcome.SUCCESS else None
        failure_reason = ((typed_reason or failure_reason_from_legacy(reason))
                          if outcome != Outcome.SUCCESS else None)
        failure_decision = None
        loop_decision = None
        if outcome == Outcome.FAILURE:
            failure_decision = self.failure_manager.record_failure(
                correlation_id=attempt.proposal.key, skill=attempt.proposal.skill,
                reason=failure_reason, at=now,
                entity_id=str(attempt.proposal.parameters.get("guid") or "") or None,
                details={"action_id": attempt.action_id, "plan_id": attempt.plan_id,
                         "legacy_reason": reason})
            loop_decision = self.loop_guard.record_attempt_failure(
                attempt, failure_reason, now, current_state=current_state)

        result = {
            "outcome": str(outcome), "reason": reason, "skill": attempt.proposal.skill,
            "failure_type": failure_type, "action_id": attempt.action_id,
            "key": attempt.proposal.key, "last_binding": last_binding,
        }
        # Preserve only the small routing identity needed by bounded recovery
        # policies.  The complete parameters remain on the durable Attempt;
        # copying them into every result would recreate the former status-JSON
        # growth problem.
        for field in ("purpose", "transition_kind", "navigation_context"):
            if attempt.proposal.parameters.get(field) is not None:
                result[field] = attempt.proposal.parameters[field]
        if failure_decision is not None:
            result["failure_budget"] = {
                "attempt": failure_decision.record.attempt_number,
                "budget": failure_decision.budget,
                "retry_allowed": failure_decision.retry_allowed,
                "replan_required": failure_decision.replan_required,
                "backoff_seconds": failure_decision.backoff_seconds,
                "reason": failure_decision.record.reason.value,
                "escalation_stage": failure_decision.escalation_stage.value,
                "recovery_action": failure_decision.recovery_action,
                "domain_recovery_required": failure_decision.domain_recovery_required,
                "goal_alternative_required": failure_decision.goal_alternative_required,
                "goal_failed": failure_decision.goal_failed,
            }
        if loop_decision is not None:
            result["loop_guard"] = {
                "level": loop_decision.level, "count": loop_decision.count,
                "signature": loop_decision.signature, "kind": loop_decision.kind,
                "matching_signatures": list(loop_decision.matching_signatures),
            }

        verification = VerificationRecord(
            verification_id=uuid.uuid4().hex, action_id=attempt.action_id,
            skill=attempt.proposal.skill, plan_id=attempt.plan_id,
            prediction_id=attempt.prediction.prediction_id,
            expected=attempt.prediction.expected, outcome=str(outcome), reason=reason,
            observed_at=now, baseline_observation_id=attempt.observation_id,
            observed_observation_id=latest_observation_id,
            evidence=tuple(filter(None, (attempt.observation_id, latest_observation_id))),
        )
        status = ({Outcome.SUCCESS: SkillStatus.SUCCESS,
                   Outcome.FAILURE: SkillStatus.FAILURE,
                   Outcome.CANCELLED: SkillStatus.CANCELLED}.get(outcome, SkillStatus.BLOCKED))
        final_reason = None if status is SkillStatus.SUCCESS else failure_reason
        skill_result = SkillResult(
            status=status, reason=final_reason,
            retryable=status is SkillStatus.FAILURE,
            replan_required=status is not SkillStatus.SUCCESS,
            metadata={"legacy_reason": reason, "action_id": attempt.action_id},
        )
        prediction_error = None
        if outcome == Outcome.FAILURE:
            prediction_error = PredictionError(
                error_id=uuid.uuid4().hex,
                prediction_id=attempt.prediction.prediction_id,
                action_id=attempt.action_id, expected=attempt.prediction.expected,
                reason=reason, created_at=attempt.prediction.created_at,
                observed_at=now, baseline_observation_id=attempt.observation_id,
                observed_observation_id=latest_observation_id,
                failure_type=failure_type, observed=reason,
                error_type=classify_prediction_error(reason),
                magnitude=(max(0., now-attempt.prediction.deadline)
                           if now > attempt.prediction.deadline else 1.),
                confidence=attempt.prediction.confidence,
            )
        return TerminalAssessment(
            failure_type, failure_reason, failure_decision, loop_decision,
            result, verification, skill_result, prediction_error,
        )
