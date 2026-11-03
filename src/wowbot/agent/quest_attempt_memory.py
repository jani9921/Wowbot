"""Single quest-attempt memory owner for execution and credit strategy evidence."""
from __future__ import annotations

from .quest_failure_memory import QuestFailureMemory
from .quest_strategy_history import QuestStrategyHistory


class QuestAttemptMemory:
    """Own bounded quest attempt evidence; never current quest truth or authority."""

    def __init__(self, *, cooldown_seconds: float = 15., max_records: int = 4096) -> None:
        self.failure_memory = QuestFailureMemory(cooldown_seconds)
        self.strategy_history = QuestStrategyHistory(max_records=max_records)
        self._playbook_trials: dict[str, dict] = {}
        self._gossip_trials: dict[str, dict] = {}

    def record_gossip_trial(self, row: dict) -> bool:
        action = str(row.get('action_id') or '')
        if not action or action in self._gossip_trials:
            return False
        self._gossip_trials[action] = dict(row)
        while len(self._gossip_trials) > 256:
            self._gossip_trials.pop(next(iter(self._gossip_trials)))
        return True

    def tried_gossip_options(self, scope: str | None) -> set[str]:
        return {row['option_id'] for row in self._gossip_trials.values()
                if scope and row['scope'] == scope and row['outcome'] == 'FAILURE'
                and not row['quest_credit']}

    def record_playbook_trial(self, row: dict) -> bool:
        """One small terminal record per action, sharing this attempt owner."""
        action = str(row.get("action_id") or "")
        if not action or action in self._playbook_trials:
            return False
        from copy import deepcopy
        self._playbook_trials[action] = deepcopy(row)
        while len(self._playbook_trials) > 256:
            self._playbook_trials.pop(next(iter(self._playbook_trials)))
        return True

    def playbook_snapshot(self, limit: int = 256) -> list[dict]:
        from copy import deepcopy
        return deepcopy(list(self._playbook_trials.values())[-max(0, min(256, limit)):]) if limit > 0 else []

    def playbook_summary(self) -> dict:
        """Small ranking projection; don't copy full terminal records per tick."""
        result = {}
        for row in self._playbook_trials.values():
            episode = result.setdefault(row["episode_id"], {"failed": {}, "verified": {}})
            if row["outcome"] == "FAILURE":
                failed = episode["failed"]
                failed[row["option"]] = failed.get(row["option"], 0) + 1
            elif row["action_verified"]:
                episode["verified"].setdefault(row["target_ref"], set()).add(row["step"])
            # P8.2: the episode's newest terminal; a failure there names the
            # recovery edge, a later success or credit closes it.
            episode["last_failure"] = ({key: row.get(key) for key in ("option", "step", "reason", "at")}
                                       if row["outcome"] == "FAILURE" and not row.get("quest_credit") else None)
        return result

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
        self._playbook_trials.clear()
        self._gossip_trials.clear()

