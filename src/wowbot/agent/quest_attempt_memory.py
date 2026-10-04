"""Single quest-attempt memory owner for execution and credit strategy evidence."""
from __future__ import annotations

from .quest_failure_memory import QuestFailureMemory
from .quest_strategy_history import QuestStrategyHistory


class QuestAttemptMemory:
    """Own bounded quest attempt evidence; never current quest truth or authority."""

    def __init__(self, *, cooldown_seconds: float = 15., max_records: int = 4096) -> None:
        self.failure_memory = QuestFailureMemory(cooldown_seconds)
        self.strategy_history = QuestStrategyHistory(max_records=max_records)

    def record_execution_failure(self, *, quest_id, objective_id, target_ref,
                                 skill: str, reason: str, now: float):
        return self.failure_memory.record(
            quest_id=quest_id, objective_id=objective_id, target_ref=target_ref,
            skill=skill, reason=reason, now=now)

    def record_execution_success(self, *, quest_id, objective_id,
                                 target_ref, skill: str) -> int:
        return self.failure_memory.clear(
            quest_id=quest_id, objective_id=objective_id,
            target_ref=target_ref, skill=skill)

    def record_strategy(self, quest_id, objective_id, *, candidate: str = "",
                        strategy: str, action_success: bool, quest_credit: bool):
        return self.strategy_history.record_attempt(
            quest_id, objective_id, candidate=candidate, strategy=strategy,
            action_success=action_success, quest_credit=quest_credit)

    def query(self, quest_id, objective_id, *, now: float | None = None) -> dict:
        qid, oid = str(quest_id or ""), str(objective_id or "")
        failures = [row for row in self.failure_memory.snapshot(now)
                    if row["quest_id"] == qid and row["objective_id"] == oid]
        strategies = [row for row in self.strategy_history.snapshot()
                      if row["quest_id"] == qid and row["objective_id"] == oid]
        return {"quest_id": qid, "objective_id": oid,
                "failures": failures, "strategies": strategies}

    def expire(self, now: float) -> int:
        before = len(self.failure_memory.snapshot())
        after = len(self.failure_memory.snapshot(now))
        return before-after

    def consolidate(self) -> dict:
        # Both underlying stores are already key-deduplicated and bounded.
        return {"failure_records": len(self.failure_memory.snapshot()),
                "strategy_records": len(self.strategy_history.snapshot())}

    def reliability(self, quest_id, objective_id, strategy: str) -> float:
        return self.strategy_history.strategy_confidence(
            quest_id, objective_id, strategy)

    def reset_execution_failures(self) -> None:
        self.failure_memory.clear()

    def reset(self) -> None:
        self.failure_memory.clear()
        self.strategy_history.reset()

