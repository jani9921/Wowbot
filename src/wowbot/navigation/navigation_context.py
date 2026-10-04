"""Typed, evidence-only navigation-context classification (V4-025)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class NavigationContext(StrEnum):
    OUTDOOR = "OUTDOOR"
    INDOOR = "INDOOR"
    CAVE = "CAVE"
    MULTI_FLOOR = "MULTI_FLOOR"
    TRANSITION = "TRANSITION"
    VEHICLE = "VEHICLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class NavigationContextAssessment:
    context: NavigationContext
    confidence: float
    evidence: tuple[str, ...]


class NavigationContextClassifier:
    """Classify the player's navigation context from available signals.

    Consumers (route expectation, map interpretation, arrival verification,
    stuck recovery) read ``.context`` to stop assuming every quest marker
    implies a straight-line path. This is evidence-only: it never asserts a
    context without a supporting signal, and defaults to ``UNKNOWN``.
    """

    def classify(self, state: Mapping[str, Any]) -> NavigationContextAssessment:
        if bool(state.get("in_vehicle") or state.get("vehicle_ui") or state.get("vehicle_camera")):
            return NavigationContextAssessment(NavigationContext.VEHICLE, 1.0, ("in_vehicle",))

        if bool(state.get("loading") or state.get("area_transition_active")):
            return NavigationContextAssessment(NavigationContext.TRANSITION, .9, ("area_transition_active",))

        floor_count = state.get("world_map_floor_count")
        if isinstance(floor_count, (int, float)) and floor_count > 1:
            return NavigationContextAssessment(
                NavigationContext.MULTI_FLOOR, .8, ("world_map_floor_count>1",))

        cave_signal = bool(state.get("cave_entrance_detected"))
        area_type = str(state.get("area_type") or "").strip().lower()
        if cave_signal or area_type == "cave":
            evidence = ("cave_entrance_detected",) if cave_signal else ("area_type_cave",)
            return NavigationContextAssessment(NavigationContext.CAVE, .75, evidence)

        indoors = state.get("is_indoors")
        if indoors is None:
            # The addon exports IsIndoors() inside ``movement`` (FAST lane).
            indoors = (state.get("movement") or {}).get("indoors")
        if indoors is True:
            return NavigationContextAssessment(NavigationContext.INDOOR, .85, ("addon_is_indoors_true",))
        if indoors is False:
            return NavigationContextAssessment(NavigationContext.OUTDOOR, .85, ("addon_is_indoors_false",))

        return NavigationContextAssessment(NavigationContext.UNKNOWN, 0.0, ())
