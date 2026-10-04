"""Bounded, evidence-cleared failure memory for generic quest execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from wowbot.runtime import world_entity_id


@dataclass(frozen=True)
class QuestFailureRecord:
    quest_id: str
    objective_id: str
    target_ref: str
    skill: str
    reason: str
    recorded_at: float
    suppress_until: float


class QuestFailureMemory:
    """Prevent immediate retries without declaring a quest/object impossible."""

    def __init__(self, cooldown_seconds: float = 15.0):
        self.cooldown_seconds = float(cooldown_seconds)
        self._records: dict[tuple[str, str, str, str], QuestFailureRecord] = {}

    @staticmethod
    def _key(quest_id, objective_id, target_ref, skill) -> tuple[str, str, str, str]:
        entity = world_entity_id(target_ref)
        return str(quest_id or ""), str(objective_id or ""), str(entity or ""), str(skill or "")

    def record(self, *, quest_id, objective_id, target_ref, skill: str, reason: str, now: float) -> QuestFailureRecord | None:
        if quest_id is None and objective_id is None:
            return None
        key = self._key(quest_id, objective_id, target_ref, skill)
        record = QuestFailureRecord(*key, str(reason), float(now), float(now) + self.cooldown_seconds)
        self._records[key] = record
        return record

    def clear(self, *, quest_id=None, objective_id=None, target_ref=None, skill=None) -> int:
        wanted = self._key(quest_id, objective_id, target_ref, skill)
        keys = [key for key in self._records if all(
            not expected or expected == actual for expected, actual in zip(wanted, key))]
        for key in keys:
            del self._records[key]
        return len(keys)

    def permits(self, *, quest_id, objective_id, target_ref, skill: str, now: float) -> bool:
        key = self._key(quest_id, objective_id, target_ref, skill)
        record = self._records.get(key)
        if record is None:
            return True
        if now >= record.suppress_until:
            del self._records[key]
            return True
        return False

    def snapshot(self, now: float | None = None) -> list[dict]:
        if now is not None:
            for key, record in list(self._records.items()):
                if now >= record.suppress_until:
                    del self._records[key]
        return [asdict(record) for record in sorted(
            self._records.values(), key=lambda item: (item.suppress_until, item.quest_id, item.objective_id))]

    @staticmethod
    def permits_snapshot(snapshot: list[dict] | None, parameters: dict, skill: str, now: float) -> bool:
        quest_id = str(parameters.get("quest_id") or "")
        objective_id = str(parameters.get("objective_id") or "")
        target_ref = str(world_entity_id(parameters.get("guid")) or "")
        for record in snapshot or ():
            if (str(record.get("quest_id") or "") == quest_id
                    and str(record.get("objective_id") or "") == objective_id
                    and str(record.get("target_ref") or "") == target_ref
                    and str(record.get("skill") or "") == str(skill)
                    and float(record.get("suppress_until") or 0.) > now):
                return False
        return True
