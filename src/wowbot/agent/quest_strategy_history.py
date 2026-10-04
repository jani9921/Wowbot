"""Bounded quest-local candidate/strategy adaptation (DESIGN-050).

This is session evidence, not global ML and not an input/planning authority.
Specialized quest policies may project their compatibility views from this
one ledger instead of maintaining competing confidence stores.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class StrategyAttempt:
    quest_id: str
    objective_id: str
    candidate: str
    strategy: str
    attempts: int = 0
    action_successes: int = 0
    quest_credits: int = 0
    no_credit_attempts: int = 0
    confidence: float = 0.0


class QuestStrategyHistory:
    """One bounded store keyed by (quest, objective, candidate, strategy)."""

    def __init__(self, *, reward_step: float = .25, penalty_step: float = .2,
                 max_records: int = 4096) -> None:
        self.reward_step = float(reward_step)
        self.penalty_step = float(penalty_step)
        self.max_records = max(1, int(max_records))
        self._records: dict[tuple[str, str, str, str], StrategyAttempt] = {}

    @staticmethod
    def _key(quest_id, objective_id, candidate, strategy) -> tuple[str, str, str, str]:
        return tuple(str(value or "") for value in
                     (quest_id, objective_id, candidate, strategy))

    def record_attempt(self, quest_id, objective_id, *, candidate: str = "",
                       strategy: str, action_success: bool,
                       quest_credit: bool) -> StrategyAttempt:
        key = self._key(quest_id, objective_id, candidate, strategy)
        record = self._records.get(key)
        if record is None:
            if len(self._records) >= self.max_records:
                self._records.pop(next(iter(self._records)))
            record = self._records[key] = StrategyAttempt(*key)
        record.attempts += 1
        record.action_successes += int(bool(action_success))
        record.quest_credits += int(bool(quest_credit))
        if quest_credit:
            record.confidence = min(1.0, record.confidence + self.reward_step)
        elif action_success:
            record.no_credit_attempts += 1
            record.confidence = max(0.0, record.confidence - self.penalty_step)
        return record

    def penalize_no_credit(self, quest_id, objective_id, *, candidate: str = "",
                            strategy: str) -> StrategyAttempt:
        return self.record_attempt(quest_id, objective_id, candidate=candidate,
                                   strategy=strategy, action_success=True,
                                   quest_credit=False)

    def reward_credit(self, quest_id, objective_id, *, candidate: str = "",
                      strategy: str) -> StrategyAttempt:
        return self.record_attempt(quest_id, objective_id, candidate=candidate,
                                   strategy=strategy, action_success=True,
                                   quest_credit=True)

    def failed_candidates(self, quest_id, objective_id) -> tuple[str, ...]:
        qid, oid = str(quest_id or ""), str(objective_id or "")
        rows = [record for record in self._records.values()
                if record.quest_id == qid and record.objective_id == oid
                and record.candidate and record.no_credit_attempts]
        rows.sort(key=lambda item: (-item.no_credit_attempts, item.candidate))
        return tuple(item.candidate for item in rows)

    def no_credit_attempts(self, quest_id, objective_id) -> int:
        qid, oid = str(quest_id or ""), str(objective_id or "")
        return sum(record.no_credit_attempts for record in self._records.values()
                   if record.quest_id == qid and record.objective_id == oid)

    def strategy_confidence(self, quest_id, objective_id, strategy: str) -> float:
        qid, oid, wanted = str(quest_id or ""), str(objective_id or ""), str(strategy or "")
        rows = [record for record in self._records.values()
                if record.quest_id == qid and record.objective_id == oid
                and record.strategy == wanted]
        return max((record.confidence for record in rows), default=0.0)

    def clear_failures(self, quest_id, objective_id) -> None:
        qid, oid = str(quest_id or ""), str(objective_id or "")
        for record in self._records.values():
            if record.quest_id == qid and record.objective_id == oid:
                record.no_credit_attempts = 0

    def clear_strategies(self, quest_id, objective_id, strategies) -> None:
        qid, oid = str(quest_id or ""), str(objective_id or "")
        wanted = {str(value) for value in strategies}
        for key, record in list(self._records.items()):
            if (record.quest_id == qid and record.objective_id == oid
                    and record.strategy in wanted):
                del self._records[key]

    def snapshot(self) -> tuple[dict, ...]:
        return tuple(asdict(record) for record in self._records.values())

    def reset(self) -> None:
        self._records.clear()
