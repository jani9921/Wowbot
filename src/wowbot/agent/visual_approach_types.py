"""Value types of the visual approach servo (phase, measurement, assessment).

Split out of visual_approach.py (2026-10-05); unchanged and re-exported there.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VisualApproachPhase(StrEnum):
    IDLE = "IDLE"
    CENTERING = "CENTERING"
    ADVANCING = "ADVANCING"
    OCCLUDED = "OCCLUDED"
    INTERACTION_READY = "INTERACTION_READY"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class VisualServoMeasurement:
    """Timestamped fusion input consumed by the persistent movement skill.

    Vision remains measurement-only. Identity comes from the committed intent;
    telemetry fields may be stale between addon snapshots and are therefore
    carried with their own sample timestamp instead of being counted again on
    every visual frame.
    """
    observation_id: str
    at: float
    track_id: str | None
    x: float | None
    y: float | None
    bbox_height: float | None
    bbox_scale_delta: float | None
    center_error: float | None
    confidence: float
    source: str
    lifecycle: str
    predicted: bool
    camera_motion_x: float | None
    camera_motion_y: float | None
    player_x: float | None
    player_y: float | None
    player_heading: float | None
    player_speed: float | None
    player_moving: bool | None
    telemetry_sample_time: float | None
    obstacle_evidence: float
    visual_sample_time: float


# Public compatibility name used by earlier diagnostics/imports.
VisualApproachSample = VisualServoMeasurement


@dataclass(frozen=True, slots=True)
class VisualApproachAssessment:
    phase: VisualApproachPhase
    terminal: bool
    success: bool
    reason: str
