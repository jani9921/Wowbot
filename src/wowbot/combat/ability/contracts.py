"""Ability data contracts; no sensor, planner or executor dependencies."""
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum


class AbilityTag(StrEnum):
    OFFENSIVE = "OFFENSIVE"
    DEFENSIVE = "DEFENSIVE"
    INTERRUPT = "INTERRUPT"
    MOVEMENT = "MOVEMENT"
    UTILITY = "UTILITY"
    AOE = "AOE"
    HEAL = "HEAL"
    RESOURCE = "RESOURCE"
    EXECUTE = "EXECUTE"


@dataclass(frozen=True, slots=True)
class AbilityDefinition:
    ability_id: object
    name: str | None
    binding: str | None
    min_range: float | None = None
    max_range: float | None = None
    cast_time_ms: int | None = None
    channel_time_ms: int | None = None
    gcd_ms: int | None = None
    cooldown_ms: int | None = None
    resource_cost: float = 0.0
    requires_target: bool = True
    requires_facing: bool = True
    requires_los: bool = True
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AbilityRuntimeState:
    ready_belief: float
    cooldown_remaining_estimate: float | None
    resource_available_belief: float
    in_range_belief: float
    facing_belief: float
    los_belief: float
    usable_confidence: float
    last_attempt_at: float | None = None
    last_result: str | None = None


@dataclass(frozen=True, slots=True)
class AbilityRule:
    rule_id: str
    ability_id: object
    priority: float
    preconditions: tuple[object, ...] = ()
    forbidden_conditions: tuple[object, ...] = ()
    expected_postconditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AbilityCandidate:
    ability_id: object
    rule_id: str
    binding: str | None
    eligible: bool
    score: float
    rejection_reasons: tuple[str, ...]
    definition: AbilityDefinition
    runtime_state: AbilityRuntimeState
    rule: AbilityRule


