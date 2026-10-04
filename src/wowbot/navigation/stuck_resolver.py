"""Bounded stuck-recovery policy, separate from movement input control.

The resolver selects exactly one next recovery *intent* after evidence from
the current one. It neither presses keys nor restarts routes itself; those
remain explicit decisions for NavigationService/SkillExecutor.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from .progress import ProgressPhase


class StuckResolutionState(StrEnum):
    IDLE = "IDLE"
    CONFIRM_STUCK = "CONFIRM_STUCK"
    STOP_AND_OBSERVE = "STOP_AND_OBSERVE"
    BACKWARD = "BACKWARD"
    TURN = "TURN"
    STRAFE = "STRAFE"
    JUMP_FORWARD = "JUMP_FORWARD"
    NEW_LOCAL_WAYPOINT = "NEW_LOCAL_WAYPOINT"
    LOCAL_REPLAN = "LOCAL_REPLAN"
    MARK_DANGER = "MARK_DANGER"
    REBUILD_CORRIDOR = "REBUILD_CORRIDOR"
    GLOBAL_REPLAN = "GLOBAL_REPLAN"
    BLACKLIST_TEMP = "BLACKLIST_TEMP"
    VERIFY_RECOVERY = "VERIFY_RECOVERY"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RecoveryDirective:
    state: StuckResolutionState
    correlation_id: str | None
    action: str | None
    replan_scope: str | None = None
    terminal: bool = False
    reason: str = ""
    stuck_kind: str = "UNKNOWN"


class StuckResolver:
    """Finite, evidence-gated recovery ladder for one navigation attempt."""

    # Live 2026-10-02 (shipwreck at Murloc Hideaway, absent from mmaps): the
    # agent backed off, re-ran the same route and hit the wreck again.  A
    # running jump is already tried by the movement controller; after backing
    # off, the obstacle is learned and the corridor rebuilt around it.
    _LADDER = (
        StuckResolutionState.BACKWARD,
        StuckResolutionState.MARK_DANGER,
        StuckResolutionState.REBUILD_CORRIDOR,
        StuckResolutionState.JUMP_FORWARD,
        StuckResolutionState.STRAFE,
        StuckResolutionState.TURN,
        StuckResolutionState.NEW_LOCAL_WAYPOINT,
        StuckResolutionState.LOCAL_REPLAN,
        StuckResolutionState.GLOBAL_REPLAN,
        StuckResolutionState.BLACKLIST_TEMP,
    )
    _PHYSICAL = frozenset({StuckResolutionState.BACKWARD, StuckResolutionState.STRAFE,
                           StuckResolutionState.JUMP_FORWARD, StuckResolutionState.TURN})
    # A new stuck this close to the previous one, this soon, continues the
    # ladder instead of restarting it: backing off always "succeeds" (the
    # position changes), so a restart repeated BACKWARD forever.
    MEMORY_RADIUS_YARDS = 5.
    MEMORY_SECONDS = 180.

    def __init__(self) -> None:
        self.memory: dict[str, object] | None = None
        self.position: tuple[float, float] | None = None
        self.reset()

    def reset(self) -> None:
        self.state = StuckResolutionState.IDLE
        self.correlation_id: str | None = None
        self.started_at: float | None = None
        self.step_index = -1
        self.stuck_kind = "UNKNOWN"
        self.awaiting_step_result = False
        self.transitions: list[dict[str, object]] = []
        self._tried: set = set()

    def begin(self, correlation_id: str, now: float, *, stuck_kind: str = "UNKNOWN",
              position: tuple[float, float] | None = None) -> RecoveryDirective:
        """Enter observation first; no blind recovery command is implied.

        ``position`` (world yards) lets a repeated stuck at the same spot
        resume the ladder where the previous attempt left it."""
        if self.state is not StuckResolutionState.IDLE and self.correlation_id == correlation_id:
            return self._directive(reason="recovery_already_active")
        self.reset()
        self.correlation_id = correlation_id
        self.stuck_kind = str(stuck_kind)
        self.started_at = now
        self.position = position
        self._transition(StuckResolutionState.CONFIRM_STUCK, now, "hard_stuck_evidence")
        memory = self.memory
        if (memory is not None and position is not None
                and memory.get("kind") == self.stuck_kind
                and 0 <= now-float(memory["at"]) <= self.MEMORY_SECONDS
                and math.hypot(position[0]-float(memory["x"]),
                               position[1]-float(memory["y"])) <= self.MEMORY_RADIUS_YARDS):
            self.step_index = int(memory["step_index"])
            self._tried = {StuckResolutionState(value) for value in memory.get("tried") or ()}
            self._transition(StuckResolutionState.CONFIRM_STUCK, now,
                             "repeated_stuck_resumes_ladder")
        self._transition(StuckResolutionState.STOP_AND_OBSERVE, now, "confirm_before_recovery")
        return self._directive(action="STOP_AND_OBSERVE", reason="hard_stuck_confirmed")

    def observe_progress(self, phase: ProgressPhase, now: float) -> RecoveryDirective:
        """Advance only after the current state receives new progress evidence."""
        if self.state is StuckResolutionState.IDLE:
            return self._directive(reason="no_active_recovery")
        if phase in {ProgressPhase.MAKING_PROGRESS, ProgressPhase.RECOVERED}:
            self.awaiting_step_result = False
            self._transition(StuckResolutionState.VERIFY_RECOVERY, now, "progress_observed")
            self._transition(StuckResolutionState.IDLE, now, "stuck_recovered")
            return self._directive(terminal=True, reason="STUCK_RECOVERED")
        if phase is ProgressPhase.HARD_STUCK and self.state is StuckResolutionState.STOP_AND_OBSERVE:
            return self._advance(now, "still_hard_stuck_after_observation")
        return self._directive(reason="awaiting_confirming_progress_evidence")

    def report_step_result(self, *, success: bool, now: float) -> RecoveryDirective:
        """A failed step unlocks one next step; success must still be verified."""
        if self.state is StuckResolutionState.IDLE:
            return self._directive(reason="no_active_recovery")
        if not self.awaiting_step_result:
            return self._directive(reason="no_recovery_step_awaiting_result")
        self.awaiting_step_result = False
        self._transition(StuckResolutionState.VERIFY_RECOVERY, now,
                         "recovery_step_result_observed")
        if success:
            # This method is called only after the skill's ordinary verifier
            # already confirmed its postcondition (normally position change).
            self._transition(StuckResolutionState.IDLE, now, "stuck_recovered")
            return self._directive(terminal=True, reason="STUCK_RECOVERED")
        ladder = self._ladder_for_kind()
        current = ladder[self.step_index] if 0 <= self.step_index < len(ladder) else None
        if current in self._PHYSICAL:
            # Live 2026-10-03 23:49: wedged between a post and a rock, the
            # back-off did not move the character, and the ladder went on to
            # MARK_DANGER / replanning, which cannot free a wedged character;
            # it stayed stuck.  A physical escape that did not move is
            # followed by the next untried physical escape first.
            tried = self.__dict__.setdefault("_tried", set())
            following = next((index for index in range(len(ladder))
                              if ladder[index] in self._PHYSICAL and ladder[index] not in tried), None)
            if following is None:
                # Physical escapes exhausted: the earliest untried step next
                # (learn the obstacle, rebuild the corridor, ...).
                following = next((index for index in range(len(ladder))
                                  if ladder[index] not in tried), None)
            if following is not None:
                self.step_index = following - 1
                return self._advance(now, "physical_escape_did_not_move")
        return self._advance(now, "previous_recovery_step_failed")

    @property
    def active(self) -> bool:
        return self.state is not StuckResolutionState.IDLE

    def _advance(self, now: float, reason: str) -> RecoveryDirective:
        ladder = self._ladder_for_kind()
        tried = self.__dict__.setdefault("_tried", set())
        self.step_index += 1
        # Steps already run in this episode (physical escapes reordered
        # ahead) are not repeated.
        while self.step_index < len(ladder) and ladder[self.step_index] in tried:
            self.step_index += 1
        if self.step_index >= len(ladder):
            self.awaiting_step_result = False
            self._transition(StuckResolutionState.FAILED, now, "recovery_ladder_exhausted")
            return self._directive(terminal=True, reason="recovery_ladder_exhausted")
        state = ladder[self.step_index]
        tried.add(state)
        self._transition(state, now, reason)
        self.awaiting_step_result = True
        if self.position is not None:
            self.memory = {"x": self.position[0], "y": self.position[1], "at": now,
                           "step_index": self.step_index, "kind": self.stuck_kind,
                           "tried": sorted(item.value for item in tried)}
        if state in {StuckResolutionState.LOCAL_REPLAN, StuckResolutionState.REBUILD_CORRIDOR}:
            return self._directive(action=state.value, replan_scope="LOCAL", reason=reason)
        if state is StuckResolutionState.GLOBAL_REPLAN:
            return self._directive(action=state.value, replan_scope="GLOBAL", reason=reason)
        return self._directive(action=state.value, reason=reason)

    def _directive(self, *, action: str | None = None, replan_scope: str | None = None,
                   terminal: bool = False, reason: str) -> RecoveryDirective:
        return RecoveryDirective(self.state, self.correlation_id, action, replan_scope, terminal, reason,
                                 self.stuck_kind)

    def _ladder_for_kind(self) -> tuple[StuckResolutionState, ...]:
        if self.stuck_kind == "DROP_OR_CLIFF":
            # Never use the generic jump-forward escape at a suspected edge.
            # Preserve the danger as planning evidence and rebuild away from
            # it without granting this policy any input authority.
            return (StuckResolutionState.MARK_DANGER,
                    StuckResolutionState.NEW_LOCAL_WAYPOINT,
                    StuckResolutionState.LOCAL_REPLAN,
                    StuckResolutionState.REBUILD_CORRIDOR)
        if self.stuck_kind == "WRONG_HEADING":
            return (StuckResolutionState.TURN, StuckResolutionState.NEW_LOCAL_WAYPOINT,
                    StuckResolutionState.LOCAL_REPLAN, StuckResolutionState.REBUILD_CORRIDOR)
        if self.stuck_kind == "OSCILLATION":
            return (StuckResolutionState.NEW_LOCAL_WAYPOINT, StuckResolutionState.LOCAL_REPLAN,
                    StuckResolutionState.REBUILD_CORRIDOR, StuckResolutionState.GLOBAL_REPLAN)
        if self.stuck_kind == "DYNAMIC_BLOCK":
            # ``begin`` already performed the bounded stop/observe phase.
            # Do not waste a second recovery tick repeating it.
            return (StuckResolutionState.STRAFE, StuckResolutionState.NEW_LOCAL_WAYPOINT,
                    StuckResolutionState.LOCAL_REPLAN)
        if self.stuck_kind == "PATH_LOOP":
            return (StuckResolutionState.MARK_DANGER, StuckResolutionState.REBUILD_CORRIDOR,
                    StuckResolutionState.GLOBAL_REPLAN)
        return self._LADDER

    def _transition(self, next_state: StuckResolutionState, now: float, cause: str) -> None:
        previous = self.state
        self.state = next_state
        self.transitions.append({"from": previous.value, "to": next_state.value,
                                 "at": now, "cause": cause})
        del self.transitions[:-32]

    def snapshot(self) -> dict[str, object]:
        return {"state": self.state.value, "correlation_id": self.correlation_id,
                "started_at": self.started_at, "step_index": self.step_index,
                "stuck_kind": self.stuck_kind,
                "awaiting_step_result": self.awaiting_step_result,
                "memory": dict(self.memory) if self.memory else None,
                "recent_transitions": list(self.transitions)}
