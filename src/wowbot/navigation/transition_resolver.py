"""Typed, evidence-only entrance/cave/multi-floor transition resolution (V4-026)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class TransitionKind(StrEnum):
    ENTER_BUILDING = "ENTER_BUILDING"
    FIND_CAVE_ENTRANCE = "FIND_CAVE_ENTRANCE"
    CHANGE_FLOOR = "CHANGE_FLOOR"
    USE_PORTAL = "USE_PORTAL"
    USE_TRANSPORT = "USE_TRANSPORT"
    UNKNOWN_TRANSITION = "UNKNOWN_TRANSITION"


@dataclass(frozen=True, slots=True)
class TransitionAssessment:
    kind: TransitionKind
    confidence: float
    evidence: tuple[str, ...]
    supported: bool


class TransitionResolver:
    """Resolve a stuck-at-the-boundary situation into a transition proposal.

    Never proposes a transition from a single frame of evidence: entry
    requires either repeated local route blockage, or a low map distance
    paired with an absent 3D target. This is what prevents "repeatedly
    walk into a wall" per the spec -- the caller is expected to run a
    bounded local entrance search when ``kind`` stays UNKNOWN_TRANSITION,
    then escalate to re-localization.
    """

    def resolve(self, signals: Mapping[str, Any]) -> TransitionAssessment:
        blocked_repeat = bool(signals.get("repeated_local_route_blockage"))
        map_close_3d_absent = (
            bool(signals.get("map_distance_low")) and not bool(signals.get("target_visible_3d")))

        if not (blocked_repeat or map_close_3d_absent):
            return TransitionAssessment(TransitionKind.UNKNOWN_TRANSITION, 0.0, (), False)

        evidence: list[str] = []
        if blocked_repeat:
            evidence.append("repeated_local_route_blockage")
        if map_close_3d_absent:
            evidence.append("map_distance_low_target_absent")
        if bool(signals.get("local_map_context_differs")):
            evidence.append("local_map_context_differs")

        if bool(signals.get("floor_interior_map_appears")) or bool(signals.get("target_above_or_below")):
            evidence.append("floor_signal")
            return TransitionAssessment(TransitionKind.CHANGE_FLOOR, .75, tuple(evidence), True)
        if bool(signals.get("cave_entrance_cue")):
            evidence.append("cave_entrance_cue")
            return TransitionAssessment(TransitionKind.FIND_CAVE_ENTRANCE, .75, tuple(evidence), True)
        if bool(signals.get("portal_cue")):
            evidence.append("portal_cue")
            return TransitionAssessment(TransitionKind.USE_PORTAL, .75, tuple(evidence), True)
        if bool(signals.get("transport_cue")):
            evidence.append("transport_cue")
            return TransitionAssessment(TransitionKind.USE_TRANSPORT, .7, tuple(evidence), True)
        if bool(signals.get("entrance_icon_cue")) or "local_map_context_differs" in evidence:
            evidence.append("entrance_signal")
            return TransitionAssessment(TransitionKind.ENTER_BUILDING, .7, tuple(evidence), True)

        return TransitionAssessment(TransitionKind.UNKNOWN_TRANSITION, .5, tuple(evidence), True)
