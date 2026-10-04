"""Evidence-based navigation progress; it never sends movement input.

The monitor keeps the V5 distinction between an absence of progress and a
confirmed stuck condition. Callers may supply any subset of independent
signals; unavailable sensors are excluded and weights are renormalised.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from enum import StrEnum
import math
from types import MappingProxyType
from typing import Mapping

from wowbot.vision.models import WorldPosition


@dataclass(frozen=True, slots=True)
class ProgressSample:
    position: WorldPosition
    timestamp: float


class ProgressPhase(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    MAKING_PROGRESS = "MAKING_PROGRESS"
    POSSIBLE_STUCK = "POSSIBLE_STUCK"
    HARD_STUCK = "HARD_STUCK"
    RECOVERED = "RECOVERED"


@dataclass(frozen=True, slots=True)
class ProgressScore:
    score: float | None
    phase: ProgressPhase
    at: float
    sources: tuple[str, ...]
    contributions: dict[str, float]
    direction_consistency: float | None = None
    oscillation_score: float = 0.0
    stuck_probability: float | None = None


@dataclass(frozen=True, slots=True)
class ProgressPolicy:
    weights: Mapping[str, float] = field(default_factory=lambda: {
        "optical_flow": .30,
        "minimap_displacement": .25,
        "target_distance": .20,
        "landmark_parallax": .15,
        "movement_state": .10,
    })
    possible_stuck_score: float = .18
    possible_stuck_seconds: float = 1.5
    hard_stuck_score: float = .10
    hard_stuck_seconds: float = 3.0
    recovered_score: float = .35
    recovered_seconds: float = .5

    def __post_init__(self) -> None:
        allowed = {
            "optical_flow", "minimap_displacement", "target_distance",
            "landmark_parallax", "movement_state",
        }
        normalized = {str(name): float(weight)
                      for name, weight in dict(self.weights).items()}
        if not normalized or any(name not in allowed for name in normalized):
            raise ValueError("Progress weights must use canonical evidence names")
        if any(not math.isfinite(value) or value < 0 for value in normalized.values()):
            raise ValueError("Progress weights must be finite and non-negative")
        if sum(normalized.values()) <= 0:
            raise ValueError("At least one progress weight must be positive")
        thresholds = (self.hard_stuck_score, self.possible_stuck_score,
                      self.recovered_score)
        if (any(not math.isfinite(value) or not 0 <= value <= 1
                for value in thresholds)
                or not self.hard_stuck_score <= self.possible_stuck_score
                < self.recovered_score):
            raise ValueError("Progress thresholds must be ordered in [0, 1]")
        durations = (self.possible_stuck_seconds, self.hard_stuck_seconds,
                     self.recovered_seconds)
        if any(not math.isfinite(value) or value < 0 for value in durations):
            raise ValueError("Progress durations must be finite and non-negative")
        object.__setattr__(self, "weights", MappingProxyType(normalized))


class ProgressMonitor:
    """Scores movement evidence and applies temporal hysteresis.

    The position window methods remain for the existing NavigationEngine. New
    callers should use :meth:`observe_signals`; its phase is evidence for the
    movement owner, never permission to issue recovery input independently.
    """

    def __init__(self, *, window: int = 6, min_distance: float = 0.01,
                 policy: ProgressPolicy | None = None) -> None:
        self._samples: deque[ProgressSample] = deque(maxlen=window)
        self.min_distance = min_distance
        self.policy = policy or ProgressPolicy()
        self._phase = ProgressPhase.UNAVAILABLE
        self._low_started_at: float | None = None
        self._hard_low_started_at: float | None = None
        self._recovered_started_at: float | None = None
        self._latest: ProgressScore | None = None
        self._bearing_history: deque[float] = deque(maxlen=20)
        self._command_history: deque[str] = deque(maxlen=20)

    def add(self, position: WorldPosition, timestamp: float) -> None:
        self._samples.append(ProgressSample(position, timestamp))

    def distance_moved(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        first, last = self._samples[0], self._samples[-1]
        return math.sqrt((last.position.x-first.position.x)**2 + (last.position.y-first.position.y)**2 + (last.position.z-first.position.z)**2)

    def making_progress(self) -> bool:
        return len(self._samples) < 2 or self.distance_moved() >= self.min_distance

    def observe_signals(self, at: float, **signals: float | int | None) -> ProgressScore:
        """Update score from normalized independent signals in ``[0, 1]``.

        ``None`` means unavailable. Unknown names are ignored so adapters
        cannot silently alter the canonical score by attaching arbitrary data.
        """
        weights = self.policy.weights
        # Heading alignment and animation are valuable diagnostics but not
        # physical displacement.  Treating either as progress would mask a
        # character that is perfectly facing the goal while pressed against a
        # wall, so they are kept outside the fused progress score.
        raw_bearing = signals.get("expected_vs_observed_bearing")
        usable = {}
        for name, value in signals.items():
            if name not in weights or weights[name] <= 0 or value is None:
                continue
            try:
                normalized = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(normalized):
                continue
            usable[name] = min(1.0, max(0.0, normalized))
        if not usable:
            # Missing evidence never inherits an old stuck classification.
            # Reset the temporal gates so recovery requires a new continuous
            # low-progress window after sensors become available again.
            self._phase = ProgressPhase.UNAVAILABLE
            self._low_started_at = None
            self._hard_low_started_at = None
            self._recovered_started_at = None
            result = ProgressScore(None, ProgressPhase.UNAVAILABLE, at, (), {},
                                   self._direction_consistency(), self._oscillation_score(), None)
            self._latest = result
            return result
        total_weight = sum(weights[name] for name in usable)
        contributions = {name: weights[name] / total_weight * value for name, value in usable.items()}
        score = sum(contributions.values())
        if raw_bearing is not None:
            try:
                self._bearing_history.append(min(1.0, max(0.0, float(raw_bearing))))
            except (TypeError, ValueError):
                pass
        direction = self._direction_consistency()
        oscillation = self._oscillation_score()
        # Oscillation is independent negative evidence. It is deliberately
        # bounded: an alternating turn pattern alone cannot prove a physical
        # block without the ordinary temporal no-progress gates.
        stuck_probability = min(1., max(0., 1. - score + .20 * oscillation
                                        + (.10 * (1. - direction) if direction is not None else 0.)))
        result = ProgressScore(round(score, 6), self._advance_phase(score, at), at,
                               tuple(sorted(usable)), contributions, direction, oscillation,
                               round(stuck_probability, 6))
        self._latest = result
        return result

    def record_command(self, command: str) -> None:
        """Record a controller decision as diagnostic evidence, never input.

        The movement owner calls this after it has selected a normal command.
        This monitor cannot schedule or alter that command.
        """
        normalized = str(command or "").upper()
        if normalized in {"TURNLEFT", "TURNRIGHT", "MOVEFORWARD", "MOVEBACKWARD", "STRAFELEFT", "STRAFERIGHT"}:
            self._command_history.append(normalized)

    def _direction_consistency(self) -> float | None:
        if not self._bearing_history:
            return None
        return round(sum(self._bearing_history) / len(self._bearing_history), 6)

    def _oscillation_score(self) -> float:
        history = list(self._command_history)
        if len(history) < 3:
            return 0.0
        opposite = {
            ("TURNLEFT", "TURNRIGHT"), ("TURNRIGHT", "TURNLEFT"),
            ("MOVEFORWARD", "MOVEBACKWARD"), ("MOVEBACKWARD", "MOVEFORWARD"),
            ("STRAFELEFT", "STRAFERIGHT"), ("STRAFERIGHT", "STRAFELEFT"),
        }
        changes = sum((left, right) in opposite for left, right in zip(history, history[1:]))
        return round(changes / max(1, len(history) - 1), 6)

    def _advance_phase(self, score: float, at: float) -> ProgressPhase:
        policy = self.policy
        if score > policy.recovered_score:
            self._low_started_at = None
            self._hard_low_started_at = None
            if self._recovered_started_at is None:
                self._recovered_started_at = at
            if at - self._recovered_started_at >= policy.recovered_seconds:
                self._phase = ProgressPhase.RECOVERED
            else:
                self._phase = ProgressPhase.MAKING_PROGRESS
            return self._phase
        self._recovered_started_at = None
        if score < policy.possible_stuck_score:
            if self._low_started_at is None:
                self._low_started_at = at
            if score < policy.hard_stuck_score:
                if self._hard_low_started_at is None:
                    self._hard_low_started_at = at
                if at - self._hard_low_started_at >= policy.hard_stuck_seconds:
                    self._phase = ProgressPhase.HARD_STUCK
                    return self._phase
            else:
                self._hard_low_started_at = None
            if at - self._low_started_at >= policy.possible_stuck_seconds:
                self._phase = ProgressPhase.POSSIBLE_STUCK
                return self._phase
        else:
            self._low_started_at = None
            self._hard_low_started_at = None
        self._phase = ProgressPhase.MAKING_PROGRESS
        return self._phase

    def snapshot(self) -> dict[str, object]:
        return {
            "phase": self._phase.value,
            "latest": asdict(self._latest) if self._latest else None,
            "low_started_at": self._low_started_at,
            "hard_low_started_at": self._hard_low_started_at,
            "recovered_started_at": self._recovered_started_at,
            "position_samples": len(self._samples),
            "direction_consistency": self._direction_consistency(),
            "oscillation_score": self._oscillation_score(),
        }

    def clear(self) -> None:
        self._samples.clear()
        self._phase = ProgressPhase.UNAVAILABLE
        self._low_started_at = None
        self._hard_low_started_at = None
        self._recovered_started_at = None
        self._latest = None
        self._bearing_history.clear()
        self._command_history.clear()
