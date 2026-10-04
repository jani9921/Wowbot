"""Bounded lifecycle for planner WAIT decisions.

This guard owns no input and chooses no domain action.  It only prevents a
sequence of differently-worded passive WAIT proposals from silently resetting
the same subgoal's wall-clock budget.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Proposal


PASSIVE_WAIT_BUDGET_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class PassiveWaitDecision:
    proposal: Proposal
    elapsed: float
    deadline: float
    expired: bool
    first_expiration: bool
    fresh_observations: int


class PassiveWaitBudget:
    """One continuous budget shared by all passive WAIT reasons."""

    def __init__(self, seconds: float = PASSIVE_WAIT_BUDGET_SECONDS) -> None:
        self.seconds = float(seconds)
        self.reset("initial")

    def reset(self, reason: str) -> None:
        self.started_at: float | None = None
        self.last_observation_id: str | None = None
        self.fresh_observations = 0
        self.expiration_reported = False
        self.reset_reason = reason

    def observe(self, proposal: Proposal, *, observation_id: str | None,
                now: float) -> PassiveWaitDecision:
        if proposal.skill != "WAIT":
            raise ValueError("PassiveWaitBudget accepts planner WAIT only")
        if self.started_at is None or now < self.started_at:
            self.started_at = now
            self.last_observation_id = None
            self.fresh_observations = 0
            self.expiration_reported = False
        if observation_id and observation_id != self.last_observation_id:
            self.last_observation_id = observation_id
            self.fresh_observations += 1
        elapsed = max(0., now-self.started_at)
        deadline = self.started_at+self.seconds
        expired = elapsed >= self.seconds
        first_expiration = expired and not self.expiration_reported
        if expired:
            self.expiration_reported = True
        parameters = dict(proposal.parameters)
        parameters.setdefault("waiting_for", ["NEW_GOAL_RELEVANT_EVIDENCE"])
        parameters.update({
            "passive_wait_started_at": self.started_at,
            "passive_wait_deadline": deadline,
            "passive_wait_elapsed": round(elapsed, 3),
            "passive_wait_budget_seconds": self.seconds,
            "passive_wait_fresh_observations": self.fresh_observations,
            "passive_wait_expired": expired,
            "next_action": ("FORCED_REPLAN" if expired
                            else parameters.get("next_action", "REPLAN_ON_EVIDENCE_OR_DEADLINE")),
        })
        decorated = Proposal.make(
            proposal.skill, proposal.reason, parameters,
            proposal.confidence, proposal.priority, proposal.evidence)
        return PassiveWaitDecision(
            decorated, elapsed, deadline, expired, first_expiration,
            self.fresh_observations)

    def snapshot(self, now: float) -> dict:
        elapsed = (max(0., now-self.started_at)
                   if self.started_at is not None else 0.)
        return {
            "active": self.started_at is not None,
            "started_at": self.started_at,
            "elapsed": round(elapsed, 3),
            "budget_seconds": self.seconds,
            "expired": self.started_at is not None and elapsed >= self.seconds,
            "fresh_observations": self.fresh_observations,
            "reset_reason": self.reset_reason,
        }
