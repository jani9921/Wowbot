"""Telemetry-assisted vs vision-only navigation mode (V4-023).

Both modes must expose the same canonical NavigationService API -- this
module is deliberately NOT a second navigation authority. It only decides
which evidence a caller should trust given what's currently available, and
guarantees the vision-only path is never treated as "cannot navigate"
merely because absolute XYZ telemetry is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class NavigationMode(StrEnum):
    TELEMETRY_ASSISTED = "TELEMETRY_ASSISTED"
    VISION_ONLY = "VISION_ONLY"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class NavigationModeEvidence:
    """What's actually available this tick -- never assumed, always supplied."""

    has_reliable_player_world_position: bool = False
    has_world_map_location_belief: bool = False
    has_minimap_direction: bool = False
    has_heading_change: bool = False
    has_scene_motion: bool = False
    has_landmarks: bool = False
    has_objective_marker_trend: bool = False
    has_local_entity_acquisition: bool = False
    has_arrival_or_quest_state_evidence: bool = False

    def any_vision_only_evidence(self) -> bool:
        return any((
            self.has_world_map_location_belief, self.has_minimap_direction,
            self.has_heading_change, self.has_scene_motion, self.has_landmarks,
            self.has_objective_marker_trend, self.has_local_entity_acquisition,
            self.has_arrival_or_quest_state_evidence,
        ))


def resolve_navigation_mode(evidence: NavigationModeEvidence) -> NavigationMode:
    """Pick the mode to trust this tick -- never UNSUPPORTED for missing XYZ alone."""
    if evidence.has_reliable_player_world_position:
        return NavigationMode.TELEMETRY_ASSISTED
    if evidence.any_vision_only_evidence():
        return NavigationMode.VISION_ONLY
    return NavigationMode.UNSUPPORTED
