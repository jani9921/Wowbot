"""The sole authority for a running skill's lifecycle.

It deliberately does not choose inputs or inspect quest semantics.  Existing
skills can be migrated behind it one at a time without creating another active
action owner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .contracts import FailureReason, Intent, RuntimeEvent, SkillResult, SkillStatus
from .entity_identity import WorldEntityId, world_entity_id


_TERMINAL = frozenset({SkillStatus.SUCCESS, SkillStatus.FAILURE,
                       SkillStatus.BLOCKED, SkillStatus.CANCELLED})


class SkillLifecycleState(StrEnum):
    CREATED = "CREATED"
    WAITING_PRECONDITIONS = "WAITING_PRECONDITIONS"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    RETRYING = "RETRYING"
    RECOVERING = "RECOVERING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PREEMPTED = "PREEMPTED"


@dataclass
class CancellationToken:
    """Observable cancellation only; it cannot release or dispatch input."""

    cancelled: bool = False
    cancelled_at: float | None = None
    reason: FailureReason | None = None

    def cancel(self, now: float, reason: FailureReason) -> None:
        if not self.cancelled:
            self.cancelled = True
            self.cancelled_at = now
            self.reason = reason


@dataclass(frozen=True)
class SkillContext:
    skill_id: str
    correlation_id: str
    parameters: dict[str, Any]
    started_at: float
    deadline: float | None
    attempt: Any
    world_snapshot_version: int | str | None
    cancellation_token: CancellationToken


@dataclass(frozen=True)
class SkillLifecycleTransition:
    state: SkillLifecycleState
    at: float
    reason: str


@dataclass
class ActiveSkillState:
    runtime_id: str
    skill_type: str
    intent: Intent
    target_ref: WorldEntityId | None
    phase: str
    started_at: float
    phase_started_at: float
    attempt: Any
    local_retry_count: int = 0
    failure_history: list[FailureReason] = field(default_factory=list)
    timeout_policy: Any = None
    retry_policy: Any = None
    before_snapshot: dict[str, Any] = field(default_factory=dict)
    skill_context: dict[str, Any] = field(default_factory=dict)
    last_result: SkillResult | None = None
    status: SkillStatus = SkillStatus.STARTING
    lifecycle: SkillLifecycleState = SkillLifecycleState.CREATED
    context: SkillContext | None = None
    lifecycle_history: list[SkillLifecycleTransition] = field(default_factory=list)


class ActiveSkillRuntime:
    """Own exactly zero or one active skill; terminal state is immutable."""

    def __init__(self):
        self._state: ActiveSkillState | None = None
        self._events: list[RuntimeEvent] = []
        self._event_sequence = 0

    @property
    def state(self) -> ActiveSkillState | None:
        return self._state

    @property
    def attempt(self) -> Any:
        return self._state.attempt if self._state else None

    @property
    def exists(self) -> bool:
        return self._state is not None and self._state.status not in _TERMINAL

    def start(self, *, intent: Intent, attempt: Any, now: float,
              before_snapshot: dict[str, Any] | None = None,
              timeout_policy: Any = None, retry_policy: Any = None,
              skill_context: dict[str, Any] | None = None,
              preconditions_satisfied: bool = True) -> ActiveSkillState:
        if self.exists:
            raise RuntimeError("Cannot start a second skill while one is running")
        # A target is actionable only when it is a live, telemetry-backed GUID.
        # In particular, do not turn an NPC template ID or a visual track into
        # an input target merely because it was placed in an intent payload.
        target_ref = world_entity_id(intent.target_ref or intent.parameters.get("guid"))
        runtime_id = uuid4().hex
        compatibility_context = dict(skill_context or {})
        token = CancellationToken()
        context = SkillContext(
            skill_id=runtime_id,
            correlation_id=str(compatibility_context.get("action_id") or runtime_id),
            parameters=dict(intent.parameters),
            started_at=now,
            deadline=getattr(attempt, "deadline", None),
            attempt=attempt,
            world_snapshot_version=compatibility_context.get("world_snapshot_version"),
            cancellation_token=token,
        )
        self._state = ActiveSkillState(
            runtime_id=runtime_id, skill_type=intent.skill_type, intent=intent,
            target_ref=target_ref, phase="START", started_at=now,
            phase_started_at=now, attempt=attempt,
            timeout_policy=timeout_policy, retry_policy=retry_policy,
            before_snapshot=dict(before_snapshot or {}),
            skill_context=compatibility_context, status=SkillStatus.RUNNING,
            lifecycle=SkillLifecycleState.CREATED, context=context,
            lifecycle_history=[SkillLifecycleTransition(
                SkillLifecycleState.CREATED, now, "created")],
        )
        self._transition_lifecycle(
            SkillLifecycleState.WAITING_PRECONDITIONS, now, "preconditions_gate")
        if preconditions_satisfied:
            self._transition_lifecycle(
                SkillLifecycleState.RUNNING, now, "preconditions_satisfied")
        self._emit("SKILL_STARTED", now, runtime_id=self._state.runtime_id,
                   skill=self._state.skill_type, target_ref=target_ref)
        return self._state

    def mark_preconditions_satisfied(self, now: float) -> None:
        state = self._require_nonterminal()
        if state.lifecycle is not SkillLifecycleState.WAITING_PRECONDITIONS:
            raise RuntimeError("Skill is not waiting for preconditions")
        self._transition_lifecycle(
            SkillLifecycleState.RUNNING, now, "preconditions_satisfied")

    def set_phase(self, phase: str, now: float) -> None:
        state = self._require_running()
        if phase != state.phase:
            state.phase, state.phase_started_at = phase, now
            self._emit("SKILL_PHASE_CHANGED", now, runtime_id=state.runtime_id,
                       skill=state.skill_type, phase=phase)

    def record_retry(self, reason: FailureReason) -> None:
        state = self._require_running()
        state.local_retry_count += 1
        state.failure_history.append(reason)
        self._transition_lifecycle(SkillLifecycleState.RETRYING,
                                   state.phase_started_at, reason.value)
        self._transition_lifecycle(SkillLifecycleState.RUNNING,
                                   state.phase_started_at, "retry_started")

    def begin_verification(self, now: float) -> None:
        self._require_running()
        self._transition_lifecycle(
            SkillLifecycleState.VERIFYING, now, "postcondition_verification")

    def begin_recovery(self, now: float, reason: FailureReason) -> None:
        self._require_running()
        self._transition_lifecycle(SkillLifecycleState.RECOVERING, now, reason.value)

    def resume_running(self, now: float, reason: str = "resume") -> None:
        self._require_running()
        self._transition_lifecycle(SkillLifecycleState.RUNNING, now, reason)

    def finish(self, result: SkillResult, now: float) -> ActiveSkillState:
        state = self._require_running()
        if result.status not in _TERMINAL:
            raise ValueError("Only a terminal SkillResult can finish an active skill")
        state.status, state.last_result = result.status, result
        state.phase, state.phase_started_at = result.status.value, now
        if result.reason:
            state.failure_history.append(result.reason)
        terminal_lifecycle = (
            SkillLifecycleState.SUCCESS if result.status is SkillStatus.SUCCESS
            else SkillLifecycleState.PREEMPTED if result.status is SkillStatus.CANCELLED
            else SkillLifecycleState.FAILED)
        if result.status is SkillStatus.CANCELLED and state.context is not None:
            state.context.cancellation_token.cancel(
                now, result.reason or FailureReason.CANCELLED)
        self._transition_lifecycle(
            terminal_lifecycle, now,
            result.reason.value if result.reason else result.status.value)
        self._emit(f"SKILL_{result.status.value}", now, runtime_id=state.runtime_id,
                   skill=state.skill_type, reason=result.reason.value if result.reason else None)
        return state

    def cancel(self, now: float, reason: FailureReason = FailureReason.CANCELLED) -> ActiveSkillState | None:
        if not self.exists:
            return self._state
        return self.finish(SkillResult(SkillStatus.CANCELLED, reason,
                                       replan_required=True), now)

    def finalize(self) -> ActiveSkillState | None:
        state, self._state = self._state, None
        return state

    def drain_events(self) -> tuple[RuntimeEvent, ...]:
        events, self._events = tuple(self._events), []
        return events

    def _require_running(self) -> ActiveSkillState:
        if not self.exists:
            raise RuntimeError("No active running skill")
        assert self._state is not None
        return self._state

    def _require_nonterminal(self) -> ActiveSkillState:
        if not self.exists:
            raise RuntimeError("No active nonterminal skill")
        assert self._state is not None
        return self._state

    def _transition_lifecycle(self, lifecycle: SkillLifecycleState,
                              now: float, reason: str) -> None:
        state = self._state
        if state is None or state.lifecycle is lifecycle:
            return
        state.lifecycle = lifecycle
        state.lifecycle_history.append(SkillLifecycleTransition(lifecycle, now, reason))
        del state.lifecycle_history[:-24]

    def _emit(self, event_type: str, at: float, **metadata: Any) -> None:
        self._event_sequence += 1
        runtime_id = self._state.runtime_id if self._state else "no-active-skill"
        self._events.append(RuntimeEvent(
            event_type, at, metadata,
            event_id=f"{runtime_id}:{self._event_sequence}:{event_type}",
            source="ACTIVE_SKILL_RUNTIME", correlation_id=runtime_id,
        ))
