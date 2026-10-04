"""Tiered no-credit escalation ladder (V4-070).

Complements ``QuestFailureMemory`` (generic bounded suppression) and
``QuestDomain.credit_gate``/``record_uncredited_target`` (single-target
credit-observation window) with the specific 1st/2nd/repeated ladder the
spec names. This maintains the two lists the spec calls out by name --
``failed_credit_candidates[]`` and ``failed_strategy_attempts[]`` -- per
(quest_id, objective_id), and returns which action tier applies next. It
never performs the re-check/confidence-reduction/escalation itself; callers
own that decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from .quest_strategy_history import QuestStrategyHistory


class CreditFailureAction(StrEnum):
    RECHECK_QUEST_STATE_AND_IDENTITY = "RECHECK_QUEST_STATE_AND_IDENTITY"
    REDUCE_CONFIDENCE_CHANGE_CANDIDATE = "REDUCE_CONFIDENCE_CHANGE_CANDIDATE"
    ESCALATE_TO_CLASSIFIER_OR_LOCATOR = "ESCALATE_TO_CLASSIFIER_OR_LOCATOR"
    BLOCKED_UNSUPPORTED = "BLOCKED_UNSUPPORTED"


@dataclass
class _ObjectiveFailureState:
    failed_credit_candidates: list[str] = field(default_factory=list)
    failed_strategy_attempts: list[str] = field(default_factory=list)


class CreditFailureEscalation:
    """Track repeated action-succeeded-but-no-credit outcomes.

    - 1st no-credit -> RECHECK_QUEST_STATE_AND_IDENTITY
    - 2nd similar no-credit -> REDUCE_CONFIDENCE_CHANGE_CANDIDATE
    - repeated (>= ``escalate_after``) -> ESCALATE_TO_CLASSIFIER_OR_LOCATOR
    - past ``block_after`` -> BLOCKED_UNSUPPORTED (do not repeat indefinitely)
    """

    def __init__(self, *, escalate_after: int = 3, block_after: int = 5,
                 history: QuestStrategyHistory | None = None) -> None:
        if escalate_after < 2:
            raise ValueError("escalate_after must allow at least a 1st/2nd distinction")
        if block_after < escalate_after:
            raise ValueError("block_after must be reachable only after escalation")
        self.escalate_after = int(escalate_after)
        self.block_after = int(block_after)
        self._state: dict[tuple[str, str], _ObjectiveFailureState] = {}
        self.history = history or QuestStrategyHistory()

    def _action_for_count(self, count: int) -> CreditFailureAction:
        if count >= self.block_after:
            return CreditFailureAction.BLOCKED_UNSUPPORTED
        if count >= self.escalate_after:
            return CreditFailureAction.ESCALATE_TO_CLASSIFIER_OR_LOCATOR
        if count >= 2:
            return CreditFailureAction.REDUCE_CONFIDENCE_CHANGE_CANDIDATE
        return CreditFailureAction.RECHECK_QUEST_STATE_AND_IDENTITY

    def record_no_credit(self, quest_id: object, objective_id: object, *,
                         candidate: str, strategy: str) -> CreditFailureAction:
        key = (str(quest_id), str(objective_id))
        state = self._state.setdefault(key, _ObjectiveFailureState())
        state.failed_credit_candidates.append(str(candidate))
        state.failed_strategy_attempts.append(str(strategy))
        self.history.penalize_no_credit(
            quest_id, objective_id, candidate=candidate, strategy=strategy)
        return self._action_for_count(
            self.history.no_credit_attempts(quest_id, objective_id))

    def current_action(self, quest_id: object, objective_id: object) -> CreditFailureAction:
        """Pure read of the current tier -- never mutates, never records a new failure."""
        return self._action_for_count(
            self.history.no_credit_attempts(quest_id, objective_id))

    def clear(self, quest_id: object, objective_id: object) -> None:
        """Call once real quest credit arrives -- the ladder resets."""
        self._state.pop((str(quest_id), str(objective_id)), None)
        self.history.clear_failures(quest_id, objective_id)

    def snapshot(self, quest_id: object, objective_id: object) -> dict[str, tuple[str, ...]]:
        state = self._state.get((str(quest_id), str(objective_id)))
        if state is None:
            return {"failed_credit_candidates": (), "failed_strategy_attempts": ()}
        return {
            "failed_credit_candidates": tuple(state.failed_credit_candidates),
            "failed_strategy_attempts": tuple(state.failed_strategy_attempts),
        }
