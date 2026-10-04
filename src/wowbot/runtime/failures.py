"""Bounded failure accounting for one canonical skill correlation chain."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .contracts import FailureReason, failure_reason_from_legacy
from .policies import RetryPolicy, TimeoutPolicy


@dataclass(frozen=True, slots=True)
class FailureRecord:
    failure_id: str
    at: float
    domain: str
    reason: FailureReason
    retryable: bool
    correlation_id: str
    attempt_number: int
    entity_id: str | None = None
    recovery_attempted: bool = False
    recovery_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class FailureEscalationStage(StrEnum):
    SKILL_RETRY = "SKILL_RETRY"
    DOMAIN_RECOVERY = "DOMAIN_RECOVERY"
    PLANNER_REPLAN = "PLANNER_REPLAN"
    GOAL_ALTERNATIVE = "GOAL_ALTERNATIVE"
    GOAL_FAILED = "GOAL_FAILED"


@dataclass(frozen=True, slots=True)
class FailureDecision:
    record: FailureRecord
    retry_allowed: bool
    replan_required: bool
    backoff_seconds: float
    budget: int
    escalation_stage: FailureEscalationStage = FailureEscalationStage.SKILL_RETRY
    recovery_action: str = "SKILL_RETRY"
    domain_recovery_required: bool = False
    goal_alternative_required: bool = False
    goal_failed: bool = False


class FailureManager:
    """Normalizes bounded retries without performing recovery or input.

    Its key is a correlation/intent signature supplied by the active-skill
    owner. It never uses a visual label as an identity and never declares an
    action successful; verified success simply clears this one failure chain.
    """

    _BUDGETS = {"movement": 3, "interaction": 3, "combat": 2,
                "loot": 2, "search": 3, "ui_wait": 3, "quest": 2,
                "general": 2}
    _TERMINAL = frozenset({FailureReason.PLAYER_DEAD, FailureReason.CANCELLED,
                           FailureReason.EXECUTOR_FAILURE, FailureReason.INTERNAL_ERROR})
    _MAX_CHAINS = 2048
    _MAX_RECORDS_PER_CHAIN = 16
    _RECOVERY_BY_REASON = {
        FailureReason.NO_PROGRESS: "STUCK_RESOLVER",
        FailureReason.STUCK: "STUCK_RESOLVER",
        FailureReason.PATH_BLOCKED: "LOCAL_NAVIGATION_RECOVERY",
        FailureReason.NO_ROUTE: "GLOBAL_ROUTE_RECOVERY",
        FailureReason.ARRIVAL_NOT_CONFIRMED: "NAVIGATION_REVERIFY",
        FailureReason.OUT_OF_RANGE: "REAPPROACH_TARGET",
        FailureReason.FACING_FAILED: "REFACE_TARGET",
        FailureReason.FACING_WRONG_WAY: "REFACE_TARGET",
        FailureReason.LINE_OF_SIGHT: "LOS_REPOSITION",
        FailureReason.TARGET_LOST: "TARGET_REACQUISITION",
        FailureReason.TARGET_MOVED: "TARGET_REACQUISITION",
        FailureReason.IDENTITY_UNCERTAIN: "ACTIVE_PERCEPTION_RECOVERY",
        FailureReason.NO_RESPONSE: "INTERACTION_RECOVERY",
        FailureReason.WRONG_UI: "INTERACTION_RECOVERY",
        FailureReason.UI_UNKNOWN: "INTERACTION_RECOVERY",
        FailureReason.PLAYER_DEAD: "DEATH_RECOVERY",
        FailureReason.TELEMETRY_STALE: "SENSOR_RECOVERY",
        FailureReason.STALE_OBSERVATION: "SENSOR_RECOVERY",
        FailureReason.QUEST_STATE_UNKNOWN: "QUEST_RECOVERY",
        FailureReason.OBJECTIVE_NOT_PROGRESSING: "QUEST_RECOVERY",
        FailureReason.EXECUTOR_FAILURE: "SAFE_STOP",
        FailureReason.INPUT_FAILURE: "SAFE_STOP",
        FailureReason.INTERNAL_ERROR: "SAFE_STOP",
    }

    def __init__(self, retries: RetryPolicy | None = None,
                 timeouts: TimeoutPolicy | None = None) -> None:
        self.retries = retries or RetryPolicy()
        self.timeouts = timeouts or TimeoutPolicy()
        self._chains: dict[str, list[FailureRecord]] = {}
        self._attempt_counts: dict[str, int] = {}
        self._recent: list[FailureRecord] = []

    @staticmethod
    def normalize(reason: FailureReason | object) -> FailureReason:
        return reason if isinstance(reason, FailureReason) else failure_reason_from_legacy(reason)

    @classmethod
    def recovery_for(cls, reason: FailureReason | object) -> str:
        normalized = cls.normalize(reason)
        return cls._RECOVERY_BY_REASON.get(normalized, "DOMAIN_RECOVERY")

    def record_failure(self, *, correlation_id: str, skill: str,
                       reason: FailureReason | object, at: float, entity_id: str | None = None,
                       retryable: bool = True, details: dict[str, Any] | None = None) -> FailureDecision:
        key = str(correlation_id or skill)
        reason = self.normalize(reason)
        if key not in self._chains and len(self._chains) >= self._MAX_CHAINS:
            oldest = next(iter(self._chains))
            self._chains.pop(oldest, None)
            self._attempt_counts.pop(oldest, None)
        prior = self._chains.setdefault(key, [])
        domain = self.timeouts.domain_for(skill)
        budget = self._BUDGETS.get(domain, self._BUDGETS["general"])
        attempt_number = self._attempt_counts.get(key, 0) + 1
        self._attempt_counts[key] = attempt_number
        retry_allowed = retryable and reason not in self._TERMINAL and attempt_number <= budget
        record = FailureRecord(uuid4().hex, at, domain, reason, retryable, key,
                               attempt_number, entity_id, details=dict(details or {}))
        prior.append(record)
        del prior[:-self._MAX_RECORDS_PER_CHAIN]
        self._recent.append(record)
        self._recent[:] = self._recent[-256:]
        stage = self._stage(attempt_number, budget, retry_allowed)
        return FailureDecision(
            record, retry_allowed,
            stage in {FailureEscalationStage.PLANNER_REPLAN,
                      FailureEscalationStage.GOAL_ALTERNATIVE,
                      FailureEscalationStage.GOAL_FAILED},
            self.retries.backoff(attempt_number, reason) if retry_allowed else 0.,
            budget, stage, self.recovery_for(reason),
            stage is FailureEscalationStage.DOMAIN_RECOVERY,
            stage is FailureEscalationStage.GOAL_ALTERNATIVE,
            stage is FailureEscalationStage.GOAL_FAILED)

    @staticmethod
    def _stage(attempt_number: int, budget: int,
               retry_allowed: bool) -> FailureEscalationStage:
        if retry_allowed:
            return FailureEscalationStage.SKILL_RETRY
        exhausted_by = max(1, attempt_number - budget)
        if exhausted_by == 1:
            return FailureEscalationStage.DOMAIN_RECOVERY
        if exhausted_by == 2:
            return FailureEscalationStage.PLANNER_REPLAN
        if exhausted_by == 3:
            return FailureEscalationStage.GOAL_ALTERNATIVE
        return FailureEscalationStage.GOAL_FAILED

    def record_success(self, correlation_id: str) -> None:
        key = str(correlation_id)
        self._chains.pop(key, None)
        self._attempt_counts.pop(key, None)

    def reset(self) -> None:
        self._chains.clear()
        self._attempt_counts.clear()
        self._recent.clear()

    def recent(self, *, correlation_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        values = self._recent if correlation_id is None else self._chains.get(str(correlation_id), [])
        return [asdict(item) for item in values[-max(0, int(limit)):]]

    def snapshot(self) -> dict[str, Any]:
        return {"active_chains": dict(self._attempt_counts),
                "recent": self.recent(limit=20), "budgets": dict(self._BUDGETS)}
