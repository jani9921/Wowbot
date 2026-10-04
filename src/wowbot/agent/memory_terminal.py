"""Persistent learning effects for verified terminal skill results."""
from __future__ import annotations

from dataclasses import dataclass

from .inspection_terminal import InspectionTerminalProcessor
from .models import Attempt, Goal, Outcome, VerificationRecord


@dataclass(frozen=True)
class MemoryTerminalAssessment:
    inspection_quality: dict | None
    events: tuple[tuple[str, dict], ...]


class MemoryTerminalProcessor:
    """Record procedural/resource evidence without planning a follow-up action."""

    @staticmethod
    def process(attempt: Attempt, outcome: Outcome, reason: str, state: dict,
                goal: Goal, now: float, verification: VerificationRecord,
                *, memory, contract, latest_observation_id: str | None,
                last_received: float, session_id: str | None) -> MemoryTerminalAssessment:
        memory.record_action_timing(
            attempt.proposal.skill, now, str(outcome), now-attempt.started_at,
            memory.learning_context(state, goal.domain),
            {"action_id": attempt.action_id,
             "prediction_id": attempt.prediction.prediction_id,
             "verification_id": verification.verification_id})
        legacy_context = f"{state.get('game_build')}:{state.get('map_id')}:{goal.domain}"
        memory.learn(legacy_context, attempt.proposal.skill, outcome == Outcome.SUCCESS)
        context = memory.learning_context(state, goal.domain)
        memory.learn_procedure(
            context, attempt.proposal.skill, outcome == Outcome.SUCCESS,
            cost=contract.cost + max(0., now-attempt.started_at), at=now,
            reason=reason, provenance={"goal_id": goal.goal_id,
                "plan_id": attempt.plan_id, "action_id": attempt.action_id,
                "prediction_id": attempt.prediction.prediction_id,
                "verification_id": verification.verification_id,
                "observation_ids": list(verification.evidence)})
        inspection_quality = None
        events: tuple[tuple[str, dict], ...] = ()
        if attempt.proposal.skill == "INSPECT":
            inspection = InspectionTerminalProcessor.process(
                attempt, outcome, reason, state,
                latest_observation_id=latest_observation_id,
                last_received=last_received, session_id=session_id,
                memory=memory, now=now, verification=verification)
            inspection_quality, events = inspection.quality, inspection.events
        if attempt.proposal.skill in {"GATHER", "HERB", "MINE"}:
            params = attempt.proposal.parameters
            memory.record_resource_site(
                state, params.get("resource_type") or attempt.proposal.skill,
                {"map_id": params.get("map_id"), "x": params.get("world_x"),
                 "y": params.get("world_y")}, outcome == Outcome.SUCCESS, now,
                {"action_id": attempt.action_id,
                 "verification_id": verification.verification_id,
                 "node_id": params.get("node_id"),
                 "observation_ids": list(verification.evidence)})
        memory.save_goal(goal)
        return MemoryTerminalAssessment(inspection_quality, events)
