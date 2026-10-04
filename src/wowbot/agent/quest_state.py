"""Canonical, evidence-derived M3 quest lifecycle state."""
from __future__ import annotations

from enum import StrEnum
from typing import Iterable, Mapping


class QuestState(StrEnum):
    UNKNOWN = "UNKNOWN"
    AVAILABLE = "AVAILABLE"
    ACCEPTING = "ACCEPTING"
    ACTIVE = "ACTIVE"
    OBJECTIVES_COMPLETE = "OBJECTIVES_COMPLETE"
    READY_TO_TURN_IN = "READY_TO_TURN_IN"
    TURNING_IN = "TURNING_IN"
    COMPLETED = "COMPLETED"
    FAILED_TEMPORARY = "FAILED_TEMPORARY"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    # Historical transport states are retained separately from success.
    TURNED_IN = "TURNED_IN"
    ABANDONED = "ABANDONED"
    ABSENT = "ABSENT"


class ObjectiveState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"


def derive_quest_state(raw: Mapping, objectives: Iterable[object]) -> QuestState:
    """Normalize only explicit addon/UI facts; never infer a quest chain."""
    declared = str(raw.get("state") or raw.get("quest_state") or "").upper()
    if declared in QuestState.__members__:
        return QuestState[declared]
    if raw.get("is_failed_terminal") is True:
        return QuestState.FAILED_TERMINAL
    if raw.get("is_failed") is True or raw.get("is_failed_temporary") is True:
        return QuestState.FAILED_TEMPORARY
    if raw.get("is_complete") is True or raw.get("is_turned_in") is True:
        return QuestState.COMPLETED
    if raw.get("is_turning_in") is True:
        return QuestState.TURNING_IN
    if raw.get("is_ready_to_turn_in") is True:
        return QuestState.READY_TO_TURN_IN
    objective_rows = tuple(objectives)
    if objective_rows and all(getattr(item, "completion_state", "UNKNOWN") == "COMPLETE"
                              for item in objective_rows):
        return QuestState.OBJECTIVES_COMPLETE
    if raw.get("is_accepting") is True:
        return QuestState.ACCEPTING
    if raw.get("is_available") is True:
        return QuestState.AVAILABLE
    return QuestState.ACTIVE


def derive_objective_state(raw: Mapping, completion_state: str) -> ObjectiveState:
    """Normalize explicit objective state without inventing graph readiness."""
    declared = str(raw.get("status") or raw.get("objective_state") or "").upper()
    if declared in ObjectiveState.__members__:
        return ObjectiveState[declared]
    if raw.get("is_failed_terminal") is True:
        return ObjectiveState.FAILED_TERMINAL
    if raw.get("is_failed") is True or raw.get("is_failed_retryable") is True:
        return ObjectiveState.FAILED_RETRYABLE
    if completion_state == "COMPLETE":
        return ObjectiveState.COMPLETE
    if completion_state == "IN_PROGRESS":
        return ObjectiveState.ACTIVE
    return ObjectiveState.PENDING
