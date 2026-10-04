"""Shared deterministic contracts for the canonical M0/M1 runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .entity_identity import WorldEntityId


class SkillStatus(StrEnum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class FailureReason(StrEnum):
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TARGET_LOST = "TARGET_LOST"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    IDENTITY_UNCERTAIN = "IDENTITY_UNCERTAIN"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    UI_UNKNOWN = "UI_UNKNOWN"
    NO_ROUTE = "NO_ROUTE"
    NO_PROGRESS = "NO_PROGRESS"
    STUCK = "STUCK"
    PATH_BLOCKED = "PATH_BLOCKED"
    ARRIVAL_NOT_CONFIRMED = "ARRIVAL_NOT_CONFIRMED"
    TARGET_MOVED = "TARGET_MOVED"
    WRONG_MAP_CONTEXT = "WRONG_MAP_CONTEXT"
    TRANSITION_REQUIRED = "TRANSITION_REQUIRED"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    FACING_FAILED = "FACING_FAILED"
    NOT_INTERACTABLE = "NOT_INTERACTABLE"
    NO_RESPONSE = "NO_RESPONSE"
    WRONG_UI = "WRONG_UI"
    EXPECTED_STATE_NOT_REACHED = "EXPECTED_STATE_NOT_REACHED"
    INTERRUPTED = "INTERRUPTED"
    INVALID_TARGET = "INVALID_TARGET"
    TARGET_DEAD = "TARGET_DEAD"
    FACING_WRONG_WAY = "FACING_WRONG_WAY"
    LINE_OF_SIGHT = "LINE_OF_SIGHT"
    SPELL_NOT_READY = "SPELL_NOT_READY"
    NOT_ENOUGH_RESOURCE = "NOT_ENOUGH_RESOURCE"
    CAST_INTERRUPTED = "CAST_INTERRUPTED"
    PLAYER_DEAD = "PLAYER_DEAD"
    COMBAT_TIMEOUT = "COMBAT_TIMEOUT"
    CORPSE_NOT_FOUND = "CORPSE_NOT_FOUND"
    NOT_LOOTABLE = "NOT_LOOTABLE"
    LOOT_UI_NOT_OPENED = "LOOT_UI_NOT_OPENED"
    EXPECTED_ITEM_NOT_RECEIVED = "EXPECTED_ITEM_NOT_RECEIVED"
    OBJECTIVE_UNKNOWN = "OBJECTIVE_UNKNOWN"
    OBJECTIVE_NOT_PROGRESSING = "OBJECTIVE_NOT_PROGRESSING"
    QUEST_STATE_UNKNOWN = "QUEST_STATE_UNKNOWN"
    TURN_IN_NOT_FOUND = "TURN_IN_NOT_FOUND"
    WRONG_QUEST_UI = "WRONG_QUEST_UI"
    UNSUPPORTED_MECHANIC = "UNSUPPORTED_MECHANIC"
    QUEST_CREDIT_NOT_RECEIVED = "QUEST_CREDIT_NOT_RECEIVED"
    TELEMETRY_STALE = "TELEMETRY_STALE"
    INPUT_FAILURE = "INPUT_FAILURE"
    EXECUTOR_FAILURE = "EXECUTOR_FAILURE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    CINEMATIC_PLAYING = "CINEMATIC_PLAYING"


@dataclass(frozen=True)
class Intent:
    skill_type: str
    parameters: dict[str, Any] = field(default_factory=dict)
    target_ref: WorldEntityId | None = None
    objective_ref: str | None = None


@dataclass(frozen=True)
class RuntimeEvent:
    event_type: str
    at: float
    metadata: dict[str, Any] = field(default_factory=dict)
    # Optional because existing adapters can still publish a local runtime
    # event without inventing an identity. Producers that need idempotence
    # (skill lifecycle, sensor bridges, supervisor interrupts) supply it.
    event_id: str | None = None
    source: str = "RUNTIME"
    correlation_id: str | None = None


@dataclass(frozen=True)
class SkillResult:
    status: SkillStatus
    reason: FailureReason | None = None
    retryable: bool = False
    replan_required: bool = False
    commands: tuple[Any, ...] = ()
    events: tuple[RuntimeEvent, ...] = ()
    evidence: tuple[Any, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    confidence: float
    reason: FailureReason | None
    evidence: tuple[Any, ...] = ()
    retry_recommended: bool = False


class NavigationStatus(StrEnum):
    RUNNING = "RUNNING"
    ARRIVED = "ARRIVED"
    STUCK = "STUCK"
    BLOCKED = "BLOCKED"
    TARGET_LOST = "TARGET_LOST"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"


class ObjectiveLocationStatus(StrEnum):
    LOCAL_ENTITY = "LOCAL_ENTITY"
    LOCAL_OBJECT = "LOCAL_OBJECT"
    LOCAL_MARKER = "LOCAL_MARKER"
    WORLD_MAP_LOCATION = "WORLD_MAP_LOCATION"
    KNOWN_LOCATION = "KNOWN_LOCATION"
    SEARCH_AREA = "SEARCH_AREA"
    TRANSITION_REQUIRED = "TRANSITION_REQUIRED"
    UNKNOWN = "UNKNOWN"


def failure_reason_from_legacy(value: object) -> FailureReason:
    """Temporary boundary adapter while old string-based skills are migrated."""
    normalized = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized in FailureReason.__members__:
        return FailureReason[normalized]
    if "OBSERVATION_MISSING" in normalized:
        # The action's expected effect did not appear in fresh telemetry
        # (e.g. a hover over a scenery box named no unit).  Live 2026-10-03:
        # 36 such INSPECTs were typed TELEMETRY_STALE and routed to sensor
        # recovery although telemetry was fresh.
        return FailureReason.EXPECTED_STATE_NOT_REACHED
    if "STALE" in normalized or "TELEMETRY" in normalized:
        return FailureReason.TELEMETRY_STALE
    if "STUCK" in normalized or "NO_PROGRESS" in normalized:
        return FailureReason.STUCK
    if "OUT_OF_RANGE" in normalized or "CLOSER" in normalized:
        return FailureReason.OUT_OF_RANGE
    if "TARGET_LOST" in normalized:
        return FailureReason.TARGET_LOST
    if "TARGET" in normalized and ("MISSING" in normalized or "NOT_FOUND" in normalized):
        return FailureReason.TARGET_NOT_FOUND
    if "TIMEOUT" in normalized or "DEADLINE" in normalized:
        return FailureReason.TIMEOUT
    if "CANCEL" in normalized:
        return FailureReason.CANCELLED
    if "PLAYER_DEAD" in normalized or normalized.endswith("_DEAD"):
        return FailureReason.PLAYER_DEAD
    if "INTERRUPT" in normalized:
        return FailureReason.INTERRUPTED
    return FailureReason.INTERNAL_ERROR
