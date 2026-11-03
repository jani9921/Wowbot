"""Bounded local recovery of the current combat target (REV4 CombatSkill split).

Moved out of ``CombatSkill`` (SRC_MELY_AUDIT 4.4: thin CombatSkill shell plus
separate positioning/recovery). For OUT_OF_RANGE, FACING_WRONG_WAY and
LINE_OF_SIGHT it decides one safe local correction of the *current* target
or a typed failure: a world approach request, a LOS reposition, an exact
facing turn / facing sweep, a small screen-anchored local retry, or the end
of its budget. NavigationService owns the resulting movement; this owns no
input and no target.

``facing`` is the owning skill until the FacingController split: it supplies
the facing commands (exact turn, sweep step), the world approach request and
the budget limits (overridable per skill).
"""
from __future__ import annotations

from wowbot.agent.models import number
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus


class CombatLocalRecovery:
    def __init__(self, facing) -> None:
        self.facing = facing

    def request(self, state: ActiveSkillState, world_state: dict,
                reason: FailureReason | None, now: float) -> SkillResult | None:
        """Request one safe local navigation correction, or return ``None``.

        Combat owns the decision that its *current* target needs a local retry;
        NavigationService owns the resulting turn/forward command.  No blind
        movement is permitted: a current matching target and fresh normalized
        screen position are required.  Missing localization therefore remains
        a typed combat failure for the planner to resolve at a higher level.
        """
        if reason not in {FailureReason.OUT_OF_RANGE, FailureReason.FACING_WRONG_WAY,
                          FailureReason.LINE_OF_SIGHT}:
            return None
        from .combat import CombatPhase
        context = state.skill_context.setdefault("combat", {})
        expected = context.get("expected_guid")
        target = world_state.get("target") or {}
        if reason is FailureReason.OUT_OF_RANGE and not context.get("approach_request"):
            started_at = context.get("range_recovery_started_at")
            if started_at is None:
                context["range_recovery_started_at"] = now
                started_at = now
            if now - float(started_at) >= self.facing.RANGE_RECOVERY_TIMEOUT_SECONDS:
                state.phase = CombatPhase.FAILED.value
                return SkillResult(
                    SkillStatus.FAILURE, FailureReason.OUT_OF_RANGE,
                    retryable=False, replan_required=True,
                    metadata={"target_unreachable": True,
                              "range_recovery_timeout_seconds":
                                  self.facing.RANGE_RECOVERY_TIMEOUT_SECONDS})
            desired_range = number(context.get("desired_range")) or 3.5
            world_request = self.facing._world_approach_request(
                world_state, expected, desired_range=desired_range)
            if world_request is not None:
                attempts = context.setdefault("world_approach_attempts", 0)
                if attempts < self.facing.RANGE_DIRECT_APPROACH_BUDGET:
                    context["world_approach_attempts"] = attempts + 1
                    context["approach_request"] = world_request
                    state.local_retry_count += 1
                    state.failure_history.append(reason)
                    state.phase = CombatPhase.RECOVER_RANGE.value
                    return SkillResult(SkillStatus.RUNNING,
                                       metadata={"approach_request": world_request})
        screen = target.get("screen_position") or {}
        x = number(screen.get("x"))
        y = number(screen.get("y"))
        sampled = number(screen.get("sample_time"))
        current_time = number(world_state.get("monotonic_time"))
        attempts = context.setdefault("local_recovery_attempts", {})
        count = int(attempts.get(reason.value, 0))
        if reason is FailureReason.LINE_OF_SIGHT and count >= self.facing.LOS_RECOVERY_ATTEMPTS:
            state.phase = CombatPhase.FAILED.value
            return SkillResult(
                SkillStatus.FAILURE, FailureReason.LINE_OF_SIGHT,
                retryable=True, replan_required=True,
                metadata={"target_unreachable": True,
                          "replan_scope": "LOCAL",
                          "los_recovery_phase": "TARGET_UNREACHABLE",
                          "los_recovery_attempts": count})
        # The third LOS step is not another blind screen-space pulse.  It is a
        # validated same-instance world request; NavigationService may route
        # it through Trinity mmap and its persistent movement controller.
        if reason is FailureReason.LINE_OF_SIGHT and count == 2:
            desired_range = number(context.get("desired_range")) or 4.5
            world_request = self.facing._world_approach_request(
                world_state, expected, desired_range=desired_range)
            if world_request is None:
                attempts[reason.value] = self.facing.LOS_RECOVERY_ATTEMPTS
                state.phase = CombatPhase.FAILED.value
                return SkillResult(
                    SkillStatus.FAILURE, FailureReason.LINE_OF_SIGHT,
                    retryable=True, replan_required=True,
                    metadata={"target_unreachable": True,
                              "replan_scope": "LOCAL",
                              "los_recovery_phase": "LOCAL_REPLAN_UNAVAILABLE",
                              "los_recovery_attempts": count})
            world_request["kind"] = "LOS_REPOSITION"
            context["approach_request"] = world_request
            attempts[reason.value] = count + 1
            state.local_retry_count += 1
            state.failure_history.append(reason)
            state.phase = CombatPhase.RECOVER_LOS.value
            return SkillResult(
                SkillStatus.RUNNING,
                metadata={"los_reposition_request": world_request,
                          "los_recovery_phase": "LOCAL_REPLAN",
                          "los_recovery_attempt": count,
                          "timeout": self.facing.LOS_RECOVERY_TIMEOUT_PER_ATTEMPT})
        if (reason is FailureReason.FACING_WRONG_WAY and not context.get("facing_sweep")
                and int(context.get("exact_facing_turns") or 0) < self.facing.FACE_EXACT_TURNS):
            exact = self.facing._exact_facing_turn(state, world_state, now,
                                            threshold=self.facing.FACE_RECOVERY_RADIANS, attack=True)
            if exact is not None:
                if exact.commands:
                    context["exact_facing_turns"] = int(context.get("exact_facing_turns") or 0) + 1
                    context["facing_handled_sequence"] = number(world_state.get("ui_error_sequence"))
                return exact
        if reason is FailureReason.FACING_WRONG_WAY:
            facing_started = context.get("facing_recovery_started_at")
            if facing_started is None:
                context["facing_recovery_started_at"] = now
                facing_started = now
            if now - float(facing_started) >= self.facing.FACING_RECOVERY_TIMEOUT_SECONDS:
                state.phase = CombatPhase.FAILED.value
                return SkillResult(
                    SkillStatus.FAILURE, FailureReason.FACING_FAILED,
                    retryable=True, replan_required=True,
                    metadata={"facing_recovery_timeout_seconds":
                                  self.facing.FACING_RECOVERY_TIMEOUT_SECONDS})
            if x is None or y is None:
                # Live 2026-10-02: the attacker was behind the character, so
                # it was not on screen and COMBAT gave up in 1.5 s.  Turn
                # toward the last bearing seen (default left); a full keyboard
                # turn takes ~2 s, within the facing timeout.
                follow = context.get("visual_follow") or {}
                last_x = number(follow.get("last_seen_x"))
                direction = follow.get("reacquire_direction")
                if direction not in {"TURNLEFT", "TURNRIGHT"}:
                    direction = ("TURNRIGHT" if last_x is not None and last_x >= .5
                                 else "TURNLEFT")
                state.phase = CombatPhase.RECOVER_FACING.value
                # Live 2026-10-03 13:57: turning blindly for 3 s without ever
                # retrying the attack ended in FACING_FAILED while a goat
                # beat the character to death.  Sweep instead: a ~35 degree
                # turn plus the attack key, repeated only while the client
                # keeps answering "not in front".
                sequence = number(world_state.get("ui_error_sequence"))
                if (not context.get("facing_sweep") and sequence is not None
                        and sequence == number(context.get("facing_handled_sequence"))):
                    # The addon keeps an error for 3 s; one already answered
                    # by a sweep step is not a new facing failure.
                    return None
                if not context.get("facing_sweep"):
                    context["facing_sweep"] = {
                        "steps": 0, "direction": direction,
                        "error_sequence": number(world_state.get("ui_error_sequence"))}
                return self.facing._facing_sweep_step(state, world_state, now)
        if (not expected or target.get("guid") != expected or x is None or y is None
                or not .02 < x < .98 or not .02 < y < .98
                or (sampled is not None and current_time is not None
                    and not 0 <= current_time-sampled <= 1.5)):
            return None
        # One facing correction, at most two small range corrections and two
        # LOS lateral probes preserve commitment without an uncontrolled loop.
        # LOS attempt three was handled above as a geometry-backed replan.
        maximum = (1 if reason is FailureReason.FACING_WRONG_WAY else
                   self.facing.LOS_RECOVERY_ATTEMPTS
                   if reason is FailureReason.LINE_OF_SIGHT else 2)
        if count >= maximum:
            if reason is FailureReason.OUT_OF_RANGE:
                state.phase = CombatPhase.FAILED.value
                return SkillResult(
                    SkillStatus.FAILURE, FailureReason.OUT_OF_RANGE,
                    retryable=False, replan_required=True,
                    metadata={"target_unreachable": True,
                              "replan_scope": "LOCAL",
                              "range_recovery_attempts": {
                                  "direct": context.get("world_approach_attempts", 0),
                                  "local": count,
                              }})
            if reason is FailureReason.LINE_OF_SIGHT:
                state.phase = CombatPhase.FAILED.value
                return SkillResult(
                    SkillStatus.FAILURE, FailureReason.LINE_OF_SIGHT,
                    retryable=True, replan_required=True,
                    metadata={"target_unreachable": True,
                              "replan_scope": "LOCAL",
                              "los_recovery_attempts": count})
            return None
        attempts[reason.value] = count + 1
        # CombatSkill receives the canonical mutable ActiveSkillState, not
        # the runtime façade.  Record this local retry on that sole active
        # state so the supervisor/debug snapshot sees it too.
        state.local_retry_count += 1
        state.failure_history.append(reason)
        phase = {
            FailureReason.OUT_OF_RANGE: CombatPhase.RECOVER_RANGE,
            FailureReason.FACING_WRONG_WAY: CombatPhase.RECOVER_FACING,
            FailureReason.LINE_OF_SIGHT: CombatPhase.RECOVER_LOS,
        }[reason]
        state.phase = phase.value
        context["await_post_recovery_cast"] = True
        return SkillResult(
            SkillStatus.RUNNING,
            metadata={"local_navigation_request": {
                "kind": "COMBAT_LOCAL_RECOVERY",
                "reason": reason.value,
                "expected_guid": expected,
                "target_screen_x": x,
                "target_screen_y": y,
                "attempt": count,
                "requested_at": now,
            }},
        )
