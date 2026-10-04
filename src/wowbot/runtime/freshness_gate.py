"""Pure freshness/detail gate for the canonical runtime loop.

The gate neither stops input nor changes mode.  It classifies whether the
engine may continue, must wait for a camera verification observation, or must
enter its existing fail-safe stale-telemetry handling.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FreshnessDecisionKind(StrEnum):
    CONTINUE = "CONTINUE"
    WAIT_CAMERA_DETAIL = "WAIT_CAMERA_DETAIL"
    WAIT_CAMERA_TELEMETRY = "WAIT_CAMERA_TELEMETRY"
    STALE_TELEMETRY = "STALE_TELEMETRY"


@dataclass(frozen=True)
class FreshnessDecision:
    kind: FreshnessDecisionKind
    receive_gap: float | None = None
    demote_to_manual: bool = False
    resume_input_authority: bool = False
    suspension_started: bool = False


class FreshnessGate:
    _CAMERA_SKILLS = frozenset({"CAMERA_CONTROL", "REACQUIRE_TARGET"})

    def __init__(self, transient_unfresh_seconds: float = .6,
                 manual_demote_seconds: float = 90.,
                 recovery_confirmations: int = 2) -> None:
        self.transient_unfresh_seconds = float(transient_unfresh_seconds)
        self.manual_demote_seconds = max(
            self.transient_unfresh_seconds, float(manual_demote_seconds))
        self.recovery_confirmations = max(1, int(recovery_confirmations))
        self._unfresh_since: float | None = None
        self._recovery_samples = 0

    def reset(self) -> None:
        self._unfresh_since = None
        self._recovery_samples = 0

    def evaluate(self, *, fresh: bool, detail_stale: bool, pending_skill: str | None,
                 full_ai: bool, player_present: bool, latest_received: float | None,
                 now: float) -> FreshnessDecision:
        gap = max(0., float(now) - float(latest_received)) if latest_received is not None else float("inf")
        camera_pending = pending_skill in self._CAMERA_SKILLS
        if fresh:
            # A single decoded packet after a long gap is not enough to hand
            # input authority back to an active skill.  Require a tiny stable
            # run, while keeping all keys released, so a flapping/torn strip
            # cannot repeatedly resume and stop movement.
            recovered = full_ai and self._unfresh_since is not None
            if recovered:
                self._recovery_samples += 1
                if self._recovery_samples < self.recovery_confirmations:
                    return FreshnessDecision(
                        FreshnessDecisionKind.STALE_TELEMETRY, gap, False)
            self._unfresh_since = None
            self._recovery_samples = 0
            if detail_stale and camera_pending and full_ai:
                return FreshnessDecision(FreshnessDecisionKind.WAIT_CAMERA_DETAIL, gap)
            return FreshnessDecision(
                FreshnessDecisionKind.CONTINUE, gap,
                resume_input_authority=bool(recovered))
        if camera_pending and full_ai and gap <= 6. and player_present:
            return FreshnessDecision(FreshnessDecisionKind.WAIT_CAMERA_TELEMETRY, gap)
        if not full_ai:
            self._unfresh_since = None
            self._recovery_samples = 0
            return FreshnessDecision(FreshnessDecisionKind.STALE_TELEMETRY, gap, False)
        suspension_started = self._unfresh_since is None
        if suspension_started:
            self._unfresh_since = float(now)
        self._recovery_samples = 0
        demote = False
        if full_ai:
            # Missing telemetry revokes *input*, not the user's selected
            # autonomous mode.  The engine stops every held key for every
            # STALE decision.  Keep the committed skill suspended through
            # the 30--60 second strip stalls observed live and demote only
            # after a genuinely persistent outage.
            demote = float(now) - self._unfresh_since >= self.manual_demote_seconds
        return FreshnessDecision(
            FreshnessDecisionKind.STALE_TELEMETRY, gap, demote,
            suspension_started=suspension_started)
