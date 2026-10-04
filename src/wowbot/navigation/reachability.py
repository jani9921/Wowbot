"""Per-entity approach confidence; a navigation bias, not a fact store."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class ReachabilityRecord:
    entity_id: str
    confidence: float = .7
    recent_failures: int = 0
    failure_types: tuple[str, ...] = ()
    last_success_at: float | None = None
    cooldown_until: float = 0.


class ReachabilityModel:
    def __init__(self) -> None:
        self._records: dict[str, ReachabilityRecord] = {}

    def reset(self) -> None:
        self._records.clear()

    def permits(self, entity_id: str, now: float) -> bool:
        record = self._records.get(str(entity_id))
        return record is None or now >= record.cooldown_until

    def report_failure(self, entity_id: str, reason: str, now: float) -> ReachabilityRecord:
        key = str(entity_id)
        record = self._records.setdefault(key, ReachabilityRecord(key))
        record.recent_failures += 1
        record.confidence = max(0., record.confidence - .18)
        record.failure_types = tuple((*record.failure_types, str(reason))[-6:])
        if record.recent_failures >= 3:
            record.cooldown_until = max(record.cooldown_until, float(now) + 20.)
        return record

    def report_success(self, entity_id: str, now: float) -> ReachabilityRecord:
        key = str(entity_id)
        record = self._records.setdefault(key, ReachabilityRecord(key))
        record.confidence = min(1., record.confidence + .2)
        record.recent_failures = 0
        record.failure_types = ()
        record.cooldown_until = 0.
        record.last_success_at = float(now)
        return record

    def snapshot(self) -> list[dict]:
        return [asdict(item) for item in sorted(self._records.values(), key=lambda row: row.entity_id)]
