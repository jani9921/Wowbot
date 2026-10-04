"""Typed, evidence-only classification of an already supported stuck state."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class StuckKind(StrEnum):
    DROP_OR_CLIFF = "DROP_OR_CLIFF"
    STATIC_BLOCK = "STATIC_BLOCK"
    CORNER = "CORNER"
    OSCILLATION = "OSCILLATION"
    NO_PROGRESS = "NO_PROGRESS"
    WRONG_HEADING = "WRONG_HEADING"
    DYNAMIC_BLOCK = "DYNAMIC_BLOCK"
    TARGET_UNREACHABLE = "TARGET_UNREACHABLE"
    PATH_LOOP = "PATH_LOOP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class StuckAssessment:
    kind: StuckKind
    confidence: float
    evidence: tuple[str, ...]
    supported: bool


class StuckClassifier:
    """Classify recovery context only after the controller's own hard gate."""

    def classify(self, state: dict[str, Any], progress: dict[str, Any] | None) -> StuckAssessment:
        latest = (progress or {}).get("latest") or {}
        phase = str(latest.get("phase") or (progress or {}).get("phase") or "")
        if phase != "HARD_STUCK":
            return StuckAssessment(StuckKind.UNKNOWN, 0., (), False)
        evidence = tuple(str(item) for item in latest.get("sources") or ())
        traversability = state.get("local_traversability") or {}
        centre = next((item for item in traversability.get("sectors") or ()
                       if isinstance(item, dict) and item.get("sector") == "CENTER"), {})
        drop_confidence = float(
            centre.get("danger_confidence")
            or centre.get("drop_confidence") or 0.)
        if centre.get("state") == "DANGEROUS" and drop_confidence >= .72:
            return StuckAssessment(
                StuckKind.DROP_OR_CLIFF,
                drop_confidence,
                evidence + tuple(str(x) for x in (centre.get("evidence") or ())),
                True,
            )
        if (centre.get("state") == "BLOCKED" and centre.get("obstacle_lifecycle") == "CONFIRMED"
                and float(centre.get("obstacle_confidence") or 0.) >= .65):
            dynamic = float(centre.get("dynamic_probability") or 0.)
            kind = StuckKind.DYNAMIC_BLOCK if dynamic >= .55 else StuckKind.STATIC_BLOCK
            confidence = dynamic if kind is StuckKind.DYNAMIC_BLOCK else float(centre.get("obstacle_confidence") or 0.)
            return StuckAssessment(
                kind,
                max(.65, confidence),
                evidence + tuple(str(x) for x in (centre.get("evidence") or ())),
                True,
            )
        oscillation = float(latest.get("oscillation_score") or 0.)
        if oscillation >= .45:
            return StuckAssessment(StuckKind.OSCILLATION, min(1., .5 + oscillation / 2), evidence, True)
        direction = latest.get("direction_consistency")
        if isinstance(direction, (int, float)) and direction < .40:
            return StuckAssessment(StuckKind.WRONG_HEADING, .7, evidence, True)
        return StuckAssessment(StuckKind.NO_PROGRESS, .55, evidence, True)
