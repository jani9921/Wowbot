"""Named M0 Movement Skill phase contract (V4-032).

``MovementSkillRunner`` (movement.py) correctly delegates all pathing to
the single ``NavigationService`` (no second pathing system, per spec) via
one ``step()`` call rather than its own named phase enum -- ``ProgressPhase``
(navigation/progress.py) is a *different* state machine (progress-quality
classification: UNAVAILABLE/MAKING_PROGRESS/POSSIBLE_STUCK/HARD_STUCK/
RECOVERED), not this skill's lifecycle. This module adds the spec's
missing named phases (INIT/RESOLVE_DESTINATION/PLAN/MOVE/MONITOR_PROGRESS/
LOCAL_CORRECTION/ARRIVAL_VERIFY/RECOVER_STUCK) as an observational contract
layer, without renaming anything MovementSkillRunner or NavigationService
already own.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MovementPhase(StrEnum):
    INIT = "INIT"
    RESOLVE_DESTINATION = "RESOLVE_DESTINATION"
    PLAN = "PLAN"
    MOVE = "MOVE"
    MONITOR_PROGRESS = "MONITOR_PROGRESS"
    LOCAL_CORRECTION = "LOCAL_CORRECTION"
    ARRIVAL_VERIFY = "ARRIVAL_VERIFY"
    RECOVER_STUCK = "RECOVER_STUCK"


@dataclass(frozen=True, slots=True)
class MovementPhaseObservation:
    """Generic, NavigationService-independent signals for one movement attempt.

    These names are deliberately abstract rather than tied to any one
    internal field, so this module stays a pure contract layer and never
    creates an import-coupling risk back into ``navigation/service.py``.
    """

    attempt_just_started: bool = False
    has_destination: bool = False
    has_plan: bool = False
    is_moving: bool = False
    is_stuck: bool = False
    is_recovering_from_stuck: bool = False
    needs_local_correction: bool = False
    arrival_claimed: bool = False
    arrival_verified: bool = False


def classify_movement_phase(observation: MovementPhaseObservation) -> MovementPhase:
    """Map a movement attempt's current signals onto the spec's 8 named phases."""
    if observation.attempt_just_started:
        return MovementPhase.INIT
    if observation.arrival_verified or observation.arrival_claimed:
        return MovementPhase.ARRIVAL_VERIFY
    if observation.is_stuck or observation.is_recovering_from_stuck:
        return MovementPhase.RECOVER_STUCK
    if observation.needs_local_correction:
        return MovementPhase.LOCAL_CORRECTION
    if not observation.has_destination:
        return MovementPhase.RESOLVE_DESTINATION
    if not observation.has_plan:
        return MovementPhase.PLAN
    if observation.is_moving:
        return MovementPhase.MONITOR_PROGRESS
    return MovementPhase.MOVE
