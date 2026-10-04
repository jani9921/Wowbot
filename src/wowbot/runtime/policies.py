"""Central deterministic retry and timeout policy for canonical skills."""
from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import FailureReason


@dataclass(frozen=True)
class TimeoutPolicy:
    """Map skill types to a domain and resolve one bounded deadline.

    Contract timeout remains the authoritative configured baseline while the
    migration is in progress. Context can only tighten a malformed value; it
    cannot invent a longer retry loop.
    """
    domains: dict[str, str] = field(default_factory=lambda: {
        "MOVE": "movement", "FOLLOW": "movement", "REACH_OBJECT": "movement",
        "REACH_LOCATION": "movement", "INTERACT": "interaction", "TALK": "interaction",
        "COMBAT": "combat", "DEFEND": "combat", "LOOT": "loot",
        "SEEK_VISUAL_CUE": "search", "REACQUIRE_TARGET": "search",
        "INSPECT": "ui_wait", "QUEST_DIALOG": "ui_wait", "FIELD_TURN_IN": "ui_wait",
        "OPEN_MAP": "map_wait", "CLOSE_MAP": "map_wait",
    })

    def domain_for(self, skill: str) -> str:
        return self.domains.get(skill, "general")

    def resolve(self, skill: str, configured_seconds: float, context: dict | None = None) -> float:
        value = max(.05, float(configured_seconds))
        # Input loss/load is supervisor-owned. Do not silently extend a skill
        # while its evidence surface is unavailable.
        if context and (context.get("loading") or context.get("input_blocked")):
            return min(value, 1.)
        return value


@dataclass(frozen=True)
class RetryPolicy:
    max_backoff_seconds: float = 120.
    base_backoff_seconds: float = 4.
    exponent_cap: int = 5
    max_attempts: int = 3
    per_reason_limits: dict[FailureReason, int] = field(default_factory=dict)
    non_backoff_reasons: frozenset[FailureReason] = frozenset({
        FailureReason.CANCELLED, FailureReason.PLAYER_DEAD, FailureReason.INTERRUPTED,
    })

    def backoff(self, failures: int, reason: FailureReason | None) -> float:
        if reason in self.non_backoff_reasons:
            return 0.
        return min(self.max_backoff_seconds,
                   self.base_backoff_seconds * 2 ** min(max(0, failures), self.exponent_cap))

    def next_backoff(self, failures: int, reason: FailureReason | None) -> float:
        """Spec-named alias for `backoff()` -- identical computation."""
        return self.backoff(failures, reason)

    def can_retry(self, attempt_number: int, reason: FailureReason | None, *,
                  retryable: bool = True) -> bool:
        """Pure attempt-budget check (DESIGN-075): no stored state, no side
        effects -- the caller owns attempt counting (see `FailureManager`,
        the live per-domain budget authority this does not replace).

        `per_reason_limits` overrides `max_attempts` for a specific reason;
        an unlisted or `None` reason falls back to `max_attempts`.
        """
        if not retryable or self.reset_if(reason):
            return False
        limit = self.max_attempts if reason is None else self.per_reason_limits.get(reason, self.max_attempts)
        return attempt_number <= max(0, int(limit))

    def reset_if(self, reason: FailureReason | None) -> bool:
        """Whether `reason` should never be retried within this chain (the
        same set `backoff()` already treats as non-backoff-eligible)."""
        return reason in self.non_backoff_reasons
