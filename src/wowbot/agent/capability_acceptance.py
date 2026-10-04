"""Per-capability acceptance metrics (DESIGN-093).

`AcceptanceAccumulator` (`acceptance.py`) is a live/soak *session*-level
pass/fail gate and stays exactly as-is. This module adds the spec's
separate, missing "capability metrics" surface -- record_case()/
record_success()/record_failure()/report_rate()/group_by_failure() -- for
tracking success rate and failure-reason breakdown per named capability
(e.g. a skill or objective type), independent of any one soak session.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CapabilityStats:
    cases: int = 0
    successes: int = 0
    failures: int = 0
    failure_reasons: dict[str, int] = field(default_factory=dict)


class CapabilityAcceptanceTracker:
    """Bounded, in-memory per-capability case/success/failure counters."""

    def __init__(self) -> None:
        self._stats: dict[str, CapabilityStats] = {}

    def _stats_for(self, capability: str) -> CapabilityStats:
        return self._stats.setdefault(str(capability), CapabilityStats())

    def record_case(self, capability: str) -> None:
        self._stats_for(capability).cases += 1

    def record_success(self, capability: str) -> None:
        self._stats_for(capability).successes += 1

    def record_failure(self, capability: str, reason: str) -> None:
        stats = self._stats_for(capability)
        stats.failures += 1
        stats.failure_reasons[str(reason)] = stats.failure_reasons.get(str(reason), 0) + 1

    def report_rate(self, capability: str) -> float | None:
        """Success rate (successes / cases); `None` when no case was recorded."""
        stats = self._stats.get(str(capability))
        if stats is None or stats.cases == 0:
            return None
        return stats.successes / stats.cases

    def group_by_failure(self, capability: str) -> dict[str, int]:
        """Failure count per reason for `capability`; empty when none recorded."""
        stats = self._stats.get(str(capability))
        return dict(stats.failure_reasons) if stats else {}

    def snapshot(self) -> dict[str, dict]:
        return {name: {"cases": stats.cases, "successes": stats.successes,
                       "failures": stats.failures, "success_rate": self.report_rate(name),
                       "failure_reasons": dict(stats.failure_reasons)}
                for name, stats in self._stats.items()}
