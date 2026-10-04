"""Uniform skill lifecycle contract over domain-specific skill implementations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from .active_skill import ActiveSkillState
from .contracts import FailureReason, SkillResult, SkillStatus


@runtime_checkable
class SkillBaseContract(Protocol):
    def start(self, context: ActiveSkillState, world: dict) -> SkillResult: ...
    def tick(self, context: ActiveSkillState, world: dict, now: float) -> SkillResult: ...
    def cancel(self, context: ActiveSkillState, reason: FailureReason) -> SkillResult: ...
    def on_enter(self, state: ActiveSkillState) -> None: ...
    def on_exit(self, state: ActiveSkillState) -> None: ...
    def snapshot(self, state: ActiveSkillState) -> dict: ...


@dataclass(frozen=True, slots=True)
class SkillContractAdapter:
    """Stateless adapter; ActiveSkillRuntime remains the lifecycle authority."""

    start_handler: Callable[[ActiveSkillState, dict], SkillResult]
    tick_handler: Callable[[ActiveSkillState, dict, float], SkillResult]

    def start(self, context: ActiveSkillState, world: dict) -> SkillResult:
        self.on_enter(context)
        return self.start_handler(context, world)

    def tick(self, context: ActiveSkillState, world: dict, now: float) -> SkillResult:
        result = self.tick_handler(context, world, now)
        if result.status in {SkillStatus.SUCCESS, SkillStatus.FAILURE,
                             SkillStatus.BLOCKED, SkillStatus.CANCELLED}:
            self.on_exit(context)
        return result

    def cancel(self, context: ActiveSkillState, reason: FailureReason) -> SkillResult:
        self.on_exit(context)
        return SkillResult(SkillStatus.CANCELLED, reason, replan_required=True)

    @staticmethod
    def on_enter(state: ActiveSkillState) -> None:
        # Explicit hook for future skill-local resources.  It intentionally
        # mutates nothing: lifecycle state belongs to ActiveSkillRuntime.
        return None

    @staticmethod
    def on_exit(state: ActiveSkillState) -> None:
        return None

    @staticmethod
    def snapshot(state: ActiveSkillState) -> dict:
        return {
            "runtime_id": state.runtime_id, "skill_type": state.skill_type,
            "phase": state.phase, "status": state.status.value,
            "lifecycle": state.lifecycle.value,
            "started_at": state.started_at,
            "phase_started_at": state.phase_started_at,
            "retry_count": state.local_retry_count,
            "target_ref": str(state.target_ref) if state.target_ref else None,
        }
