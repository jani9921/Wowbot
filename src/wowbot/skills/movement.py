"""One observation step for an already active canonical movement skill."""
from __future__ import annotations

from dataclasses import dataclass

from .movement_phase_contract import MovementPhase, MovementPhaseObservation, classify_movement_phase


@dataclass(frozen=True)
class MovementStep:
    assessment: object
    commands: tuple
    next_segment_baseline: dict | None
    phase: MovementPhase = MovementPhase.MOVE


class MovementSkillRunner:
    """Advance NavigationService without dispatching input or ending a skill."""

    def __init__(self, navigation) -> None:
        self.navigation = navigation

    def step(self, attempt, world_state: dict, observation_id: str, now: float,
             segment_baseline: dict | None) -> MovementStep:
        assessment = self.navigation.observe(world_state, observation_id, now, commanded=True)
        if (attempt.proposal.skill == "MOVE"
                and assessment.reason == "reach_progress_observed"
                and segment_baseline):
            self.navigation.observe_verified_move(
                segment_baseline, world_state, attempt.proposal.parameters)
        next_baseline = segment_baseline
        if observation_id != self.navigation.last_command_observation_id:
            next_baseline = world_state.copy()
        commands = () if assessment.terminal else tuple(
            self.navigation.command(world_state, observation_id, now))
        phase = self._classify(assessment, segment_baseline)
        return MovementStep(assessment, commands, next_baseline, phase)

    @staticmethod
    def _classify(assessment: object, segment_baseline: dict | None) -> MovementPhase:
        """Map this step's assessment onto the spec's 8 named phases (V4-032).

        Defensive ``getattr`` reads: ``assessment`` may be a lightweight
        test double exposing only ``terminal``/``reason``, not the full
        ``MovementAssessment`` contract, so this must never raise on a
        missing attribute -- it only annotates, it must never change the
        step's actual outcome.
        """
        terminal = bool(getattr(assessment, "terminal", False))
        success = bool(getattr(assessment, "success", False))
        legacy_phase = getattr(assessment, "phase", None)
        legacy_name = getattr(legacy_phase, "name", "")
        observation = MovementPhaseObservation(
            attempt_just_started=segment_baseline is None,
            has_destination=True,
            has_plan=True,
            is_moving=legacy_name == "MOVING",
            is_stuck=legacy_name in {"CANDIDATE_STUCK", "SUPPORTED_STUCK"},
            arrival_claimed=terminal and success,
            arrival_verified=terminal and success,
        )
        return classify_movement_phase(observation)
