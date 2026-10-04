"""Collect-objective source strategy belief tracker (V4-051).

"Collection source is not known merely from the word 'collect'" -- this
tracks a per-(quest_id, objective_id) confidence belief across
GROUND_OBJECT/MOB_LOOT/DIRECT_INTERACT/QUEST_ITEM_MECHANIC/SCRIPTED/UNKNOWN
and strengthens or weakens it from observed outcomes, matching the spec's
own worked example: kill succeeds but objective does not progress -> corpse
lootable -> loot -> objective increases -> strengthen MOB_LOOT. If loot
succeeds but the objective does not increase, the belief weakens instead
so the caller re-evaluates the source.
"""
from __future__ import annotations

from enum import StrEnum
from .quest_strategy_history import QuestStrategyHistory


class CollectStrategy(StrEnum):
    GROUND_OBJECT = "GROUND_OBJECT"
    MOB_LOOT = "MOB_LOOT"
    DIRECT_INTERACT = "DIRECT_INTERACT"
    QUEST_ITEM_MECHANIC = "QUEST_ITEM_MECHANIC"
    SCRIPTED = "SCRIPTED"
    UNKNOWN = "UNKNOWN"


class CollectStrategyTracker:
    """Per-objective collect-source strategy belief, strengthened/weakened by outcome."""

    def __init__(self, *, strengthen_step: float = 0.25, weaken_step: float = 0.2,
                 history: QuestStrategyHistory | None = None) -> None:
        self.strengthen_step = float(strengthen_step)
        self.weaken_step = float(weaken_step)
        self.history = history or QuestStrategyHistory(
            reward_step=strengthen_step, penalty_step=weaken_step)

    def record_outcome(self, quest_id: object, objective_id: object, *,
                       strategy: CollectStrategy, objective_progressed: bool) -> CollectStrategy:
        """Update belief from one observed action outcome; return the current best guess."""
        if objective_progressed:
            self.history.reward_credit(
                quest_id, objective_id, strategy=strategy.value)
        else:
            self.history.penalize_no_credit(
                quest_id, objective_id, strategy=strategy.value)
        return self.best_guess(quest_id, objective_id)

    def best_guess(self, quest_id: object, objective_id: object) -> CollectStrategy:
        best_strategy, best_confidence = CollectStrategy.UNKNOWN, 0.0
        for strategy in CollectStrategy:
            confidence = self.confidence_of(quest_id, objective_id, strategy)
            if confidence > best_confidence:
                best_strategy, best_confidence = strategy, confidence
        return best_strategy

    def confidence_of(self, quest_id: object, objective_id: object, strategy: CollectStrategy) -> float:
        return self.history.strategy_confidence(
            quest_id, objective_id, strategy.value)

    def clear(self, quest_id: object, objective_id: object) -> None:
        self.history.clear_strategies(
            quest_id, objective_id, (strategy.value for strategy in CollectStrategy))

    def guidance(self, quest_id: object, objective_id: object,
                 skill: str) -> tuple[CollectStrategy, float, float]:
        """Return evidence-scaled guidance for an existing proposal only."""
        strategy = self.best_guess(quest_id, objective_id)
        confidence = self.confidence_of(quest_id, objective_id, strategy)
        weights = {
            CollectStrategy.GROUND_OBJECT: {
                "OBJECT_USE": 6., "GATHER": 4., "INTERACT": 2.},
            CollectStrategy.MOB_LOOT: {
                "LOOT": 6., "COMBAT": 3., "ACQUIRE_TARGET": 2.},
            CollectStrategy.DIRECT_INTERACT: {
                "INTERACT": 6., "TALK": 4., "OBJECT_USE": 3.},
            CollectStrategy.QUEST_ITEM_MECHANIC: {
                "USE_ON_TARGET": 6., "EXTRA_ACTION": 5., "OBJECT_USE": 2.},
            CollectStrategy.SCRIPTED: {
                "FOLLOW_INSTRUCTION": 6., "WAIT": 1.},
        }
        adjustment = weights.get(strategy, {}).get(str(skill), 0.) * confidence
        return strategy, confidence, adjustment
