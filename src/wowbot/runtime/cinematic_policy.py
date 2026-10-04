"""Optional, rate-limited cinematic skip policy (V4-067).

Default behavior for a cinematic is to stop sending gameplay input and wait
for it to end -- see ``Supervisor``'s CRITICAL_RECOVERY gate on
``cinematic_playing``. A skip request is a distinct, opt-in action that this
policy bounds so the agent can never spam skip input while a cinematic is
already ending or while skipping is disabled.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CinematicSkipDecision:
    should_skip: bool
    reason: str


class CinematicSkipPolicy:
    """Bounded, explicitly-opt-in cinematic skip gate.

    ``enabled=False`` (the default) never proposes a skip -- the agent then
    only ever does the spec's default: wait. When enabled, at most
    ``max_attempts`` skip proposals are made per cinematic, each separated
    by at least ``min_interval_seconds``, and a proposal is only made while
    the cinematic is still known to be playing.
    """

    def __init__(self, *, enabled: bool = False,
                 min_interval_seconds: float = 3.0,
                 max_attempts: int = 1) -> None:
        self.enabled = enabled
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.max_attempts = max(0, int(max_attempts))
        self._attempts = 0
        self._last_attempt_at: float | None = None

    def reset(self) -> None:
        """Call when a new cinematic starts so attempt budget refills."""
        self._attempts = 0
        self._last_attempt_at = None

    def evaluate(self, *, cinematic_playing: bool, now: float) -> CinematicSkipDecision:
        if not self.enabled:
            return CinematicSkipDecision(False, "skip_policy_disabled")
        if not cinematic_playing:
            return CinematicSkipDecision(False, "no_cinematic_playing")
        if self._attempts >= self.max_attempts:
            return CinematicSkipDecision(False, "attempt_budget_exhausted")
        if (self._last_attempt_at is not None
                and now - self._last_attempt_at < self.min_interval_seconds):
            return CinematicSkipDecision(False, "min_interval_not_elapsed")
        self._attempts += 1
        self._last_attempt_at = now
        return CinematicSkipDecision(True, "skip_attempt_authorized")
