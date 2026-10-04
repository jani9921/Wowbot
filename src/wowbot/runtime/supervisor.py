"""Priority gates only; never plans, presses input or mutates WorldModel."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .active_skill import ActiveSkillState
from .cinematic_policy import CinematicSkipDecision, CinematicSkipPolicy
from .contracts import FailureReason, Intent, RuntimeEvent


class SupervisorDirectiveKind(StrEnum):
    CONTINUE = "CONTINUE"
    REPLAN = "REPLAN"
    BLOCK = "BLOCK"


class SupervisorState(StrEnum):
    """Observable ownership state for the single runtime control path.

    This is deliberately a *supervision* state, not a second planner or
    movement state machine.  It tells diagnostics which concern currently
    owns attention; physical movement remains owned by NavigationService.
    """

    IDLE = "IDLE"
    NAVIGATION = "NAVIGATION"
    QUEST_OBJECTIVE = "QUEST_OBJECTIVE"
    INTERACTION = "INTERACTION"
    LOOT = "LOOT"
    COMBAT = "COMBAT"
    COMBAT_RECOVERY = "COMBAT_RECOVERY"
    STUCK_RECOVERY = "STUCK_RECOVERY"
    EXPLORATION = "EXPLORATION"
    DEATH_RECOVERY = "DEATH_RECOVERY"
    DISCONNECT_RECOVERY = "DISCONNECT_RECOVERY"
    CRITICAL_RECOVERY = "CRITICAL_RECOVERY"


@dataclass(frozen=True)
class SupervisorRetryPolicy:
    """Bounded retry metadata for one supervisor state.

    This is descriptive policy consumed by the runtime owner. It cannot
    schedule work or issue input, which keeps the Supervisor a gate rather
    than a second executor.
    """

    max_attempts: int
    backoff_seconds: float


@dataclass(frozen=True)
class SupervisorStateSpec:
    """Immutable part of the V5 ``SupervisorState`` contract."""

    state_id: SupervisorState
    priority: int
    interruptible: bool
    timeout: float | None
    retry_policy: SupervisorRetryPolicy

    def can_enter(self, world_state: dict[str, Any],
                  active: ActiveSkillState | None = None) -> bool:
        """Return whether the state's evidence-backed entry gate is open."""
        if self.state_id is SupervisorState.DEATH_RECOVERY:
            return bool(world_state.get("is_dead") or world_state.get("is_ghost"))
        if self.state_id is SupervisorState.DISCONNECT_RECOVERY:
            return bool(world_state.get("disconnected") or world_state.get("connection_lost"))
        if self.state_id is SupervisorState.CRITICAL_RECOVERY:
            return bool(world_state.get("loading") or world_state.get("input_blocked")
                        or world_state.get("unexpected_modal")
                        or world_state.get("blocking_modal")
                        or world_state.get("cinematic_playing"))
        if self.state_id is SupervisorState.COMBAT:
            return bool(world_state.get("is_in_combat") or (
                active is not None and active.skill_type.upper() in Supervisor._COMBAT_SKILLS))
        if self.state_id is SupervisorState.COMBAT_RECOVERY:
            return bool(active is not None and
                        active.skill_type.upper() in {"COMBAT_RECOVER", "COMBAT_RECOVERY"})
        if self.state_id is SupervisorState.STUCK_RECOVERY:
            return bool(active is not None and active.skill_type.upper() in {"RECOVER", "UNSTUCK"})
        return not _hard_blocked(world_state)

    def can_exit(self, world_state: dict[str, Any]) -> bool:
        """Return whether the evidence that owns this state has cleared."""
        if self.state_id is SupervisorState.DEATH_RECOVERY:
            return not (world_state.get("is_dead") or world_state.get("is_ghost"))
        if self.state_id is SupervisorState.DISCONNECT_RECOVERY:
            return not (world_state.get("disconnected") or world_state.get("connection_lost"))
        if self.state_id is SupervisorState.CRITICAL_RECOVERY:
            return not (world_state.get("loading") or world_state.get("input_blocked")
                        or world_state.get("unexpected_modal")
                        or world_state.get("blocking_modal")
                        or world_state.get("cinematic_playing"))
        if self.state_id is SupervisorState.COMBAT:
            return not world_state.get("is_in_combat")
        return True


def _hard_blocked(world_state: dict[str, Any]) -> bool:
    return bool(
        world_state.get("is_dead") or world_state.get("is_ghost")
        or world_state.get("disconnected") or world_state.get("connection_lost")
        or world_state.get("loading") or world_state.get("input_blocked")
        or world_state.get("unexpected_modal") or world_state.get("blocking_modal")
        or world_state.get("cinematic_playing")
    )


@dataclass(frozen=True)
class SupervisorDirective:
    kind: SupervisorDirectiveKind
    reason: FailureReason | None = None
    cancel_active: bool = False
    event: RuntimeEvent | None = None
    suspend_active: bool = False


@dataclass(frozen=True)
class SuspendedIntent:
    """One resumable intent; it is not an active skill or input lease."""
    token: str
    intent: Intent
    source_runtime_id: str
    suspended_at: float
    reason: FailureReason


@dataclass(frozen=True)
class RecoveryCheckpoint:
    """A safe pause record, never an autonomous resurrection/input script."""
    reason: FailureReason
    paused_at: float
    goal_id: str | None
    required_condition: str


class Supervisor:
    """Owns only interrupt/replan gates and their explicit priority order."""

    _COMBAT_SKILLS = frozenset({"COMBAT", "DEFEND", "ACQUIRE_TARGET", "ESCAPE"})
    _RESUMABLE_SKILLS = frozenset({
        "MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION", "INTERACT", "TALK",
        "LOOT", "VISUAL_APPROACH", "SEEK_VISUAL_CUE",
    })
    _RESUME_WINDOW_SECONDS = 20.
    _COMBAT_RESUME_WINDOW_SECONDS = 180.
    _STATE_SPECS = {
        SupervisorState.IDLE: SupervisorStateSpec(
            SupervisorState.IDLE, 0, True, None, SupervisorRetryPolicy(0, 0.)),
        SupervisorState.EXPLORATION: SupervisorStateSpec(
            SupervisorState.EXPLORATION, 10, True, 30., SupervisorRetryPolicy(2, .5)),
        SupervisorState.NAVIGATION: SupervisorStateSpec(
            SupervisorState.NAVIGATION, 20, True, 120., SupervisorRetryPolicy(2, .5)),
        SupervisorState.QUEST_OBJECTIVE: SupervisorStateSpec(
            SupervisorState.QUEST_OBJECTIVE, 25, True, None, SupervisorRetryPolicy(1, 1.)),
        SupervisorState.LOOT: SupervisorStateSpec(
            SupervisorState.LOOT, 30, True, 12., SupervisorRetryPolicy(2, .25)),
        SupervisorState.INTERACTION: SupervisorStateSpec(
            SupervisorState.INTERACTION, 35, True, 15., SupervisorRetryPolicy(2, .25)),
        SupervisorState.STUCK_RECOVERY: SupervisorStateSpec(
            SupervisorState.STUCK_RECOVERY, 50, True, 12., SupervisorRetryPolicy(2, .5)),
        SupervisorState.COMBAT: SupervisorStateSpec(
            SupervisorState.COMBAT, 60, True, 180., SupervisorRetryPolicy(1, .25)),
        SupervisorState.COMBAT_RECOVERY: SupervisorStateSpec(
            SupervisorState.COMBAT_RECOVERY, 70, True, 20., SupervisorRetryPolicy(2, .5)),
        SupervisorState.CRITICAL_RECOVERY: SupervisorStateSpec(
            SupervisorState.CRITICAL_RECOVERY, 80, False, None, SupervisorRetryPolicy(0, 0.)),
        SupervisorState.DISCONNECT_RECOVERY: SupervisorStateSpec(
            SupervisorState.DISCONNECT_RECOVERY, 90, False, None, SupervisorRetryPolicy(0, 0.)),
        SupervisorState.DEATH_RECOVERY: SupervisorStateSpec(
            SupervisorState.DEATH_RECOVERY, 100, False, None, SupervisorRetryPolicy(0, 0.)),
    }

    def __init__(self, *, cinematic_skip_enabled: bool = False) -> None:
        self._suspended: SuspendedIntent | None = None
        self._recovery: RecoveryCheckpoint | None = None
        self._last_resume_reason: str | None = None
        self._state = SupervisorState.IDLE
        self._state_since: float | None = None
        self._transitions: list[dict[str, Any]] = []
        self._loop_escalation: dict[str, Any] | None = None
        # V4-067: default-disabled, rate-limited opt-in skip gate. Never
        # proposes a skip on its own -- a caller must both construct the
        # Supervisor with skip enabled and separately query the decision.
        self.cinematic_skip_policy = CinematicSkipPolicy(enabled=cinematic_skip_enabled)

    def evaluate(self, state: dict[str, Any], active: ActiveSkillState | None,
                 now: float) -> SupervisorDirective:
        # Priority order follows V4: death, hard UI block, survival combat,
        # then retain the current skill. A running skill is never displaced by
        # an ordinary perception or planner suggestion.
        if state.get("is_dead") or state.get("is_ghost"):
            self.enter(SupervisorState.DEATH_RECOVERY, now, "player_dead", state, active)
            return self._directive(SupervisorDirectiveKind.BLOCK, FailureReason.PLAYER_DEAD,
                                   active is not None, "PLAYER_DIED", now)
        if state.get("disconnected") or state.get("connection_lost"):
            self.enter(SupervisorState.DISCONNECT_RECOVERY, now, "connection_lost", state, active)
            return self._directive(SupervisorDirectiveKind.BLOCK, FailureReason.TELEMETRY_STALE,
                                   active is not None, "CONNECTION_LOST", now)
        if state.get("loading"):
            self.enter(SupervisorState.CRITICAL_RECOVERY, now, "loading", state, active)
            return self._directive(SupervisorDirectiveKind.BLOCK, FailureReason.STALE_OBSERVATION,
                                   active is not None, "LOADING_STARTED", now)
        if state.get("cinematic_playing"):
            # Cinematic is a blocking state (V4-067): stop sending gameplay
            # input and wait. No skip input is issued here -- that stays an
            # explicit, rate-limited opt-in via CinematicSkipPolicy so this
            # gate never spams skip presses on its own.
            if self._state is not SupervisorState.CRITICAL_RECOVERY:
                # Rising edge into a (this) cinematic -- refill the bounded
                # skip-attempt budget for it.
                self.cinematic_skip_policy.reset()
            self.enter(SupervisorState.CRITICAL_RECOVERY, now, "cinematic_playing", state, active)
            return self._directive(SupervisorDirectiveKind.BLOCK, FailureReason.CINEMATIC_PLAYING,
                                   active is not None, "CINEMATIC_STARTED", now)
        if state.get("input_blocked") or state.get("unexpected_modal") or state.get("blocking_modal"):
            self.enter(SupervisorState.CRITICAL_RECOVERY, now, "input_blocked", state, active)
            return self._directive(SupervisorDirectiveKind.BLOCK, FailureReason.UI_UNKNOWN,
                                   active is not None, "UI_BLOCKING_STATE", now)
        # Anti-loop evidence cannot press keys or choose a recovery. It enters
        # through this sole priority gate, interrupts the current skill if one
        # still exists, and forces a fresh planner pass. Safety/combat gates
        # above retain their higher authority.
        if self._loop_escalation is not None:
            escalation = self._loop_escalation
            self._loop_escalation = None
            level = str(escalation["level"])
            event_type = f"LOOP_{level}_ESCALATED"
            correlation = f"supervisor:{event_type}:{escalation['signature']}"
            return SupervisorDirective(
                SupervisorDirectiveKind.REPLAN, FailureReason.INTERRUPTED,
                active is not None,
                RuntimeEvent(event_type, now, dict(escalation),
                             event_id=correlation, source="SUPERVISOR",
                             correlation_id=correlation),
                False)
        # An external recovery (revive, reconnect, or a human-dismissed modal)
        # has occurred.  We only permit a later normal planner pass; this
        # method intentionally sends no recovery input itself.
        if self._recovery is not None:
            self._recovery = None
            self._last_resume_reason = "recovery_stabilized_replan_required"
        self.enter(self._operating_state(state, active), now, "runtime_observation",
                   state, active, current_complete=True)
        if active and state.get("is_in_combat") and active.skill_type not in self._COMBAT_SKILLS:
            return self._directive(SupervisorDirectiveKind.REPLAN, FailureReason.INTERRUPTED,
                                   True, "COMBAT_STARTED", now, suspend_active=True)
        return SupervisorDirective(SupervisorDirectiveKind.CONTINUE)

    def state_spec(self, state: SupervisorState | None = None) -> SupervisorStateSpec:
        """Return the immutable contract for ``state`` or the current state."""
        return self._STATE_SPECS[state or self._state]

    @classmethod
    def state_specs(cls) -> tuple[SupervisorStateSpec, ...]:
        """Expose every required state contract in deterministic priority order."""
        return tuple(sorted(cls._STATE_SPECS.values(), key=lambda item: item.priority))

    @classmethod
    def can_preempt(cls, current: SupervisorState,
                    proposed: SupervisorState) -> bool:
        """Implement the minimum V5 preemption matrix without executing it."""
        if current is proposed:
            return False
        if proposed is SupervisorState.DEATH_RECOVERY:
            return True
        if current is SupervisorState.DEATH_RECOVERY:
            return False
        if proposed is SupervisorState.DISCONNECT_RECOVERY:
            return True
        if current is SupervisorState.DISCONNECT_RECOVERY:
            return False
        if proposed is SupervisorState.CRITICAL_RECOVERY:
            return current not in {
                SupervisorState.DEATH_RECOVERY, SupervisorState.DISCONNECT_RECOVERY,
            }
        if current is SupervisorState.CRITICAL_RECOVERY:
            return False
        if proposed in {SupervisorState.COMBAT, SupervisorState.COMBAT_RECOVERY}:
            return current in {
                SupervisorState.IDLE, SupervisorState.EXPLORATION,
                SupervisorState.NAVIGATION, SupervisorState.QUEST_OBJECTIVE,
                SupervisorState.INTERACTION, SupervisorState.LOOT,
                SupervisorState.STUCK_RECOVERY, SupervisorState.COMBAT,
            }
        if proposed is SupervisorState.STUCK_RECOVERY:
            return current is SupervisorState.NAVIGATION
        return False

    def can_enter(self, next_state: SupervisorState, world_state: dict[str, Any],
                  active: ActiveSkillState | None = None, *,
                  current_complete: bool = False) -> bool:
        """Check evidence and transition authority for an intended state."""
        spec = self.state_spec(next_state)
        if not spec.can_enter(world_state, active):
            return False
        if next_state is self._state:
            return True
        return (current_complete or self.state_spec().can_exit(world_state)
                or self.can_preempt(self._state, next_state))

    def enter(self, next_state: SupervisorState, now: float, cause: str,
              world_state: dict[str, Any] | None = None,
              active: ActiveSkillState | None = None, *,
              current_complete: bool = False) -> bool:
        """Enter a state after its evidence/preemption contract is satisfied."""
        observed = world_state or {}
        if not self.can_enter(next_state, observed, active,
                              current_complete=current_complete):
            return False
        self._set_state(next_state, now, cause)
        return True

    def tick(self, context: dict[str, Any], active: ActiveSkillState | None,
             now: float) -> SupervisorDirective:
        """Lifecycle-compatible alias for the sole priority-gate evaluation."""
        return self.evaluate(context, active, now)

    def cinematic_skip_decision(self, *, cinematic_playing: bool, now: float) -> CinematicSkipDecision:
        """V4-067: query whether a bounded, rate-limited skip attempt is
        currently authorized. Disabled by default (see `__init__`); a caller
        still owns actually pressing the skip input."""
        return self.cinematic_skip_policy.evaluate(cinematic_playing=cinematic_playing, now=now)

    def notify_loop(self, decision: Any, now: float) -> None:
        """Latch the strongest loop evidence for the next supervision tick."""
        level = str(getattr(decision, "level", "NONE"))
        if level not in {"SUSPECTED", "CONFIRMED"}:
            return
        incoming = {
            "level": level,
            "signature": str(getattr(decision, "signature", "")),
            "kind": str(getattr(decision, "kind", "LEGACY")),
            "count": int(getattr(decision, "count", 0)),
            "observed_at": float(now),
        }
        if (self._loop_escalation is None
                or level == "CONFIRMED"
                or self._loop_escalation.get("level") != "CONFIRMED"):
            self._loop_escalation = incoming

    def can_exit(self, world_state: dict[str, Any]) -> bool:
        return self.state_spec().can_exit(world_state)

    def exit(self, world_state: dict[str, Any], now: float, reason: str) -> bool:
        """Exit a cleared state to IDLE; never dispatch or release input itself."""
        if not self.can_exit(world_state):
            return False
        self._set_state(SupervisorState.IDLE, now, reason)
        return True

    def suspend(self, active: ActiveSkillState, now: float,
                reason: FailureReason) -> RuntimeEvent | None:
        """Save one safe-to-retry intent after an explicit interrupt.

        The ActiveSkillRuntime is still cancelled by the caller.  This record
        contains intent data only; it cannot retain an input lease or silently
        resume after manual mode, death, loading, or a lost precondition.
        """
        if active.skill_type not in self._RESUMABLE_SKILLS:
            self._last_resume_reason = f"not_resumable:{active.skill_type}"
            return None
        token = f"{active.runtime_id}:resume"
        self._suspended = SuspendedIntent(token, active.intent, active.runtime_id, now, reason)
        self._last_resume_reason = None
        return RuntimeEvent(
            "SKILL_SUSPENDED", now,
            {"skill": active.skill_type, "reason": reason.value,
             "source_runtime_id": active.runtime_id},
            event_id=token, source="SUPERVISOR", correlation_id=active.runtime_id,
        )

    def resume_candidate(self, state: dict[str, Any], now: float) -> SuspendedIntent | None:
        """Return, but do not consume, a still-safe suspended intent."""
        suspended = self._suspended
        if suspended is None:
            return None
        resume_window = (self._COMBAT_RESUME_WINDOW_SECONDS
                         if suspended.reason is FailureReason.INTERRUPTED
                         else self._RESUME_WINDOW_SECONDS)
        if now-suspended.suspended_at > resume_window:
            self.clear_resume("resume_window_expired")
            return None
        if state.get("is_in_combat") or state.get("is_dead") or state.get("is_ghost"):
            return None
        if state.get("loading") or state.get("input_blocked"):
            return None
        return suspended

    def consume_resume(self, token: str, now: float) -> RuntimeEvent | None:
        suspended = self._suspended
        if suspended is None or suspended.token != token:
            return None
        self._suspended = None
        self._last_resume_reason = "resumed"
        return RuntimeEvent(
            "SKILL_RESUMED", now,
            {"skill": suspended.intent.skill_type,
             "source_runtime_id": suspended.source_runtime_id},
            event_id=f"{token}:consumed", source="SUPERVISOR",
            correlation_id=suspended.source_runtime_id,
        )

    def clear_resume(self, reason: str) -> None:
        self._suspended = None
        self._last_resume_reason = reason

    def mark_safety_pause(self, reason: FailureReason, now: float,
                          *, goal_id: str | None = None) -> RecoveryCheckpoint:
        """Record why FULL_AI was made safe and what must happen externally."""
        condition = {
            FailureReason.PLAYER_DEAD: "PLAYER_ALIVE_AND_LOADING_STABLE",
            FailureReason.TELEMETRY_STALE: "CONNECTION_AND_TELEMETRY_STABLE",
            FailureReason.STALE_OBSERVATION: "LOADING_FINISHED_AND_FRESH_STATE",
            FailureReason.UI_UNKNOWN: "BLOCKING_MODAL_DISMISSED_AND_FRESH_STATE",
        }.get(reason, "FRESH_SAFE_STATE")
        self._recovery = RecoveryCheckpoint(reason, now, goal_id, condition)
        self.clear_resume("safety_pause")
        return self._recovery

    def snapshot(self) -> dict[str, Any]:
        suspended = self._suspended
        spec = self.state_spec()
        return {
            "suspended": ({"token": suspended.token,
                           "skill": suspended.intent.skill_type,
                           "source_runtime_id": suspended.source_runtime_id,
                           "suspended_at": suspended.suspended_at,
                           "reason": suspended.reason.value}
                          if suspended else None),
            "last_resume_reason": self._last_resume_reason,
            "loop_escalation": (dict(self._loop_escalation)
                                if self._loop_escalation else None),
            "recovery": ({"reason": self._recovery.reason.value,
                          "paused_at": self._recovery.paused_at,
                          "goal_id": self._recovery.goal_id,
                          "required_condition": self._recovery.required_condition}
                         if self._recovery else None),
            "state": self._state.value,
            "state_since": self._state_since,
            "state_contract": {
                "state_id": spec.state_id.value,
                "priority": spec.priority,
                "interruptible": spec.interruptible,
                "timeout": spec.timeout,
                "retry_policy": {
                    "max_attempts": spec.retry_policy.max_attempts,
                    "backoff_seconds": spec.retry_policy.backoff_seconds,
                },
            },
            "recent_transitions": list(self._transitions),
        }

    @staticmethod
    def _operating_state(state: dict[str, Any], active: ActiveSkillState | None) -> SupervisorState:
        if state.get("is_in_combat"):
            return SupervisorState.COMBAT
        if active is None:
            return SupervisorState.IDLE
        skill = active.skill_type.upper()
        if skill in {"COMBAT", "DEFEND", "ACQUIRE_TARGET", "ESCAPE"}:
            return SupervisorState.COMBAT
        if skill in {"COMBAT_RECOVER", "COMBAT_RECOVERY"}:
            return SupervisorState.COMBAT_RECOVERY
        if skill in {"RECOVER", "UNSTUCK"}:
            return SupervisorState.STUCK_RECOVERY
        if skill == "LOOT":
            return SupervisorState.LOOT
        if skill in {"INTERACT", "TALK", "ACCEPT_QUEST", "TURN_IN_QUEST"}:
            return SupervisorState.INTERACTION
        if skill in {"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION", "VISUAL_APPROACH"}:
            return SupervisorState.NAVIGATION
        if skill in {"QUEST_OBJECTIVE", "GATHER", "FISH", "QUEST_ITEM", "QUEST_TOOL"}:
            return SupervisorState.QUEST_OBJECTIVE
        if skill in {"SEEK_VISUAL_CUE", "INSPECT", "OPEN_MAP", "EXPLORE"}:
            return SupervisorState.EXPLORATION
        return SupervisorState.IDLE

    def _set_state(self, next_state: SupervisorState, now: float, cause: str) -> None:
        if next_state is self._state:
            return
        previous = self._state
        self._state = next_state
        self._state_since = now
        self._transitions.append({
            "from": previous.value,
            "to": next_state.value,
            "at": now,
            "cause": cause,
        })
        # Bound diagnostics so a long-running session cannot accumulate state
        # history indefinitely.
        del self._transitions[:-24]

    @staticmethod
    def _directive(kind: SupervisorDirectiveKind, reason: FailureReason,
                   cancel_active: bool, event_type: str, now: float,
                   *, suspend_active: bool = False) -> SupervisorDirective:
        correlation = f"supervisor:{event_type}:{now:.6f}"
        return SupervisorDirective(kind, reason, cancel_active,
                                   RuntimeEvent(event_type, now, {"reason": reason.value},
                                                event_id=correlation, source="SUPERVISOR",
                                                correlation_id=correlation), suspend_active)
