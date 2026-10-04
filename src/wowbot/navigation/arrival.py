from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from wowbot.vision.models import WorldPosition
from .models import ArrivalCondition


class ArrivalStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    CANDIDATE = "CANDIDATE"
    ARRIVED = "ARRIVED"


@dataclass(frozen=True, slots=True)
class ArrivalAssessment:
    status: ArrivalStatus
    confidence: float
    evidence: tuple[str, ...]
    distance: float | None
    enter_tolerance: float | None
    exit_tolerance: float | None

    @property
    def arrived(self) -> bool:
        return self.status is ArrivalStatus.ARRIVED


class ArrivalVerifier:
    """Evidence-fused arrival gate with Schmitt-trigger hysteresis.

    Distance is authoritative only when its coordinate contract is explicitly
    marked reliable.  The remaining inputs are independent corroborating
    signals; absence of all signals remains UNKNOWN rather than becoming a
    false negative or a guessed arrival.
    """

    enter_confidence = .85
    retain_confidence = .60
    exit_multiplier = 1.25

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._arrived = False
        self._last = ArrivalAssessment(ArrivalStatus.UNKNOWN, 0., (), None, None, None)

    @staticmethod
    def _signal(value: object, weight: float) -> float:
        if isinstance(value, bool):
            return weight if value else 0.
        if isinstance(value, (int, float)) and math.isfinite(value):
            return weight * min(1., max(0., float(value)))
        return 0.

    @staticmethod
    def _noisy_or(values: list[float]) -> float:
        missing = 1.
        for value in values:
            missing *= 1. - min(1., max(0., value))
        return 1. - missing

    def observe(self, *, distance: float | None, tolerance: float | None,
                facts: dict[str, object] | None = None) -> ArrivalAssessment:
        facts = facts or {}
        reliable_distance = (
            facts.get("absolute_distance_reliable") is True
            and isinstance(distance, (int, float))
            and isinstance(tolerance, (int, float))
            and not isinstance(distance, bool)
            and not isinstance(tolerance, bool)
            and math.isfinite(distance)
            and math.isfinite(tolerance)
            and float(distance) >= 0.
            and float(tolerance) >= 0.
        )
        enter = float(tolerance) if reliable_distance else None
        exit_at = enter * self.exit_multiplier if enter is not None else None
        evidence: list[str] = []
        scores: list[float] = []

        if reliable_distance and float(distance) <= enter:
            evidence.append("reliable_absolute_distance")
            scores.append(.95)

        semantic_signals = (
            ("minimap_convergence", .45),
            ("interaction_ready", .95),
            ("bbox_growth", .35),
            ("quest_area_state_change", .90),
            ("map_transition", .90),
        )
        for name, weight in semantic_signals:
            score = self._signal(facts.get(name), weight)
            if score > 0.:
                evidence.append(name)
                scores.append(score)

        confidence = self._noisy_or(scores)
        strong_semantic = any(
            self._signal(facts.get(name), weight) >= self.enter_confidence
            for name, weight in semantic_signals
        )

        if self._arrived:
            crossed_exit = (
                reliable_distance and exit_at is not None
                and float(distance) > exit_at
            )
            if crossed_exit and not strong_semantic:
                self._arrived = False
            elif (reliable_distance and float(distance) <= exit_at) or confidence >= self.retain_confidence:
                # Once confirmed, retain arrival inside the wider exit envelope.
                self._arrived = True
                confidence = max(self.retain_confidence, confidence)
                if reliable_distance and float(distance) <= exit_at and "arrival_hysteresis" not in evidence:
                    evidence.append("arrival_hysteresis")
            else:
                # Missing evidence is not proof that a previous arrival
                # remains valid; a new intent must not inherit a sticky fact.
                self._arrived = False
        elif confidence >= self.enter_confidence:
            self._arrived = True

        status = (ArrivalStatus.ARRIVED if self._arrived else
                  ArrivalStatus.CANDIDATE if confidence > 0. else
                  ArrivalStatus.UNKNOWN)
        self._last = ArrivalAssessment(
            status, round(confidence, 4), tuple(evidence),
            float(distance) if isinstance(distance, (int, float)) else None,
            enter, exit_at,
        )
        return self._last

    def snapshot(self) -> dict[str, object]:
        return {
            "status": self._last.status.value,
            "confidence": self._last.confidence,
            "evidence": list(self._last.evidence),
            "distance": self._last.distance,
            "enter_tolerance": self._last.enter_tolerance,
            "exit_tolerance": self._last.exit_tolerance,
        }

    def verify(self, current: WorldPosition, condition: ArrivalCondition, *,
               observed_facts: dict[str, object] | None = None) -> bool:
        """Compatibility adapter for the legacy navigation engine."""
        facts = observed_facts or {}
        if condition.condition_type in {"POINT", "AREA"}:
            destination = facts.get("destination")
            distance = self._distance(current, destination)
            assessment = self.observe(
                distance=distance if isinstance(destination, WorldPosition) else None,
                tolerance=condition.tolerance,
                facts={**facts, "absolute_distance_reliable": isinstance(destination, WorldPosition)},
            )
            return assessment.arrived
        if condition.condition_type in {"INTERACTION", "ENGAGEMENT", "GATHERING_RANGE"}:
            return self.observe(
                distance=None, tolerance=None,
                facts={**facts, "interaction_ready": facts.get("in_range", False)},
            ).arrived
        if condition.condition_type == "ZONE":
            return facts.get("zone") == condition.metadata.get("zone")
        return False

    @staticmethod
    def _distance(a, b) -> float:
        if not isinstance(b, WorldPosition):
            return float("inf")
        return ((a.x-b.x)**2 + (a.y-b.y)**2 + (a.z-b.z)**2) ** 0.5
