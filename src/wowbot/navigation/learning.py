from __future__ import annotations

from dataclasses import dataclass
import math

from .memory import NavigationMemory


@dataclass(frozen=True, slots=True)
class StrategyScore:
    key: str
    score: float
    evidence: float
    confidence: float


class LearningPolicy:
    """Small statistical learner: memory influences costs; it never directly executes movement."""

    def __init__(self, memory: NavigationMemory, *, prior_success: float = 0.5) -> None:
        self.memory = memory
        self.prior_success = prior_success

    def score_route(self, route_id: str) -> StrategyScore:
        exp = self.memory.get_experience(route_id)
        if exp is None or exp.attempts == 0:
            return StrategyScore(route_id, self.prior_success, 0.0, 0.0)
        confidence = min(1.0, exp.attempts / 20.0)
        score = (exp.success_rate * confidence) + (self.prior_success * (1.0 - confidence))
        score = score * 0.7 + 0.3 * exp.reliability_score
        return StrategyScore(route_id, max(0.0, min(1.0, score)), exp.attempts, confidence)

    def route_cost_multiplier(self, route_id: str) -> float:
        score = self.score_route(route_id)
        return 1.0 + (1.0 - score.score) * 2.0

    def segment_cost_multiplier(self, segment_id: str) -> float:
        exp = self.memory.get_segment_experience(segment_id)
        if exp is None or exp.attempts == 0:
            return 1.0
        confidence = min(1.0, exp.attempts / 20.0)
        learned_success = exp.success_rate
        score = self.prior_success * (1.0 - confidence) + learned_success * confidence
        if exp.blocked_count:
            score *= max(0.25, 1.0 - min(0.75, exp.blocked_count * 0.08))
        return 1.0 + (1.0 - score) * 1.5
