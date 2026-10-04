"""Recovery proposal policy separated from the Agent orchestration loop."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Proposal


@dataclass(frozen=True)
class RecoveryPlanningDecision:
    proposal: Proposal
    recovery_for: str | None = None


class RecoveryPlanner:
    """Select bounded recovery intents; never execute movement or input."""

    STATIONARY_THRESHOLD_SECONDS = 120.

    def __init__(self) -> None:
        self.stationary_position: tuple | None = None
        self.stationary_since: float | None = None

    def reset(self) -> None:
        self.stationary_position = None
        self.stationary_since = None

    def apply(self, proposal: Proposal, *, world, goal, last_result: dict,
              navigation, registry, autonomy, failures: dict, now: float,
              current_recovery_for: str | None = None) -> RecoveryPlanningDecision:
        recovery_for = current_recovery_for
        supported_stuck = (
            last_result.get("skill") in {"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"}
            and last_result.get("outcome") == "FAILURE"
            and last_result.get("reason") == "supported_stuck")
        state = world.state
        interruptible = (
            not state.get("is_in_combat") and not state.get("is_casting")
            and not (state.get("quest_ui") or {}).get("open")
            and not (state.get("gossip_ui") or {}).get("open")
            and proposal.skill not in {
                "COMBAT", "DEFEND", "ESCAPE", "INTERACT", "TALK", "LOOT", "QUEST_DIALOG", "FIELD_TURN_IN"})
        if (interruptible and not state.get("is_dead") and not state.get("is_ghost")
                and (supported_stuck or navigation.stuck_recovery_active)):
            correlation = str(last_result.get("action_id") or last_result.get("key")
                              or "navigation_stuck")
            failed_action = str(last_result.get("action_id") or "") or None
            if supported_stuck and recovery_for and failed_action and failed_action != recovery_for:
                directive = navigation.report_recovery_result(success=False, now=now)
                recovery_for = failed_action
            else:
                directive = navigation.next_stuck_recovery(correlation, now, state)
                if supported_stuck and recovery_for is None:
                    recovery_for = failed_action
            if directive.action == "MARK_DANGER":
                marked = navigation.mark_current_route_danger(
                    state, now, correlation_id=directive.correlation_id)
                # MARK_DANGER changes memory but is not proof of recovery. Move
                # to the next finite ladder step and rebuild the corridor.
                directive = navigation.report_recovery_result(success=False, now=now)
            if directive.action == "NEW_LOCAL_WAYPOINT":
                observation_id = (world.latest.observation_id if world.latest else
                                  f"local-waypoint:{now:.6f}")
                waypoint = navigation.new_local_recovery_waypoint(
                    state, observation_id, now)
                if waypoint is not None:
                    recovery = Proposal.make(
                        "MOVE", "Beragadás helyreállítás: validált új lokális waypoint",
                        waypoint, confidence=.9, priority=99,
                        evidence=(str(directive.correlation_id or "stuck"),))
                    if registry.available(recovery, world):
                        autonomy.reset(now, "STUCK_NEW_LOCAL_WAYPOINT")
                        return RecoveryPlanningDecision(recovery, recovery_for)
                directive = navigation.report_recovery_result(success=False, now=now)
            if directive.action == "REBUILD_CORRIDOR":
                observation_id = (world.latest.observation_id if world.latest else
                                  f"rebuild-corridor:{now:.6f}")
                navigation.rebuild_current_corridor(state, observation_id, now)
            if directive.action == "BLACKLIST_TEMP":
                navigation.mark_current_route_danger(
                    state, now, correlation_id=directive.correlation_id,
                    ttl=300., cost=30., kind="TEMP_ROUTE_BLACKLIST")
                terminal = navigation.report_recovery_result(success=False, now=now)
                return RecoveryPlanningDecision(
                    Proposal.make(
                        "WAIT", "Beragadás-helyreállítási létra kimerült; új cél/útvonal szükséges",
                        {"stuck_recovery_state": terminal.state.value,
                         "replan_scope": "GLOBAL"}),
                    recovery_for)
            previous = proposal
            proposal, recovery_for = self._apply_directive(
                proposal, directive, world=world, goal=goal, registry=registry,
                autonomy=autonomy, count=failures.get(last_result.get("key"), 0),
                recovery_for=recovery_for,
                reason_prefix="Beragadás helyreállítás", now=now)
            if proposal is not previous and proposal.skill == "RECOVER":
                recovery_for = str(last_result.get("action_id") or "") or recovery_for
            if (getattr(directive, "terminal", False)
                    and getattr(directive, "reason", "") == "STUCK_RECOVERED"):
                recovery_for = None

        self._observe_stationary(world.player_position(), now)
        if self._stationary_recovery_allowed(proposal, state, now):
            count = failures.get("GLOBAL_STATIONARY_WATCHDOG", 0)
            directive = navigation.observe_external_hard_stuck(
                "GLOBAL_STATIONARY_WATCHDOG", now)
            updated, _ = self._apply_directive(
                proposal, directive, world=world, goal=goal, registry=registry,
                autonomy=autonomy, count=count, recovery_for=recovery_for,
                reason_prefix="Globális beragadás-őrszem", now=now)
            if updated is not proposal and updated.skill == "RECOVER":
                failures["GLOBAL_STATIONARY_WATCHDOG"] = count + 1
                self.stationary_since = now
            proposal = updated
        return RecoveryPlanningDecision(proposal, recovery_for)

    def _observe_stationary(self, position: tuple | None, now: float) -> None:
        if position is None:
            self.reset()
        elif position == self.stationary_position:
            if self.stationary_since is None:
                self.stationary_since = now
        else:
            self.stationary_position = position
            self.stationary_since = now

    def _stationary_recovery_allowed(self, proposal: Proposal, state: dict,
                                     now: float) -> bool:
        duration = now-self.stationary_since if self.stationary_since is not None else 0.
        return (duration >= self.STATIONARY_THRESHOLD_SECONDS
                and proposal.skill != "RECOVER"
                and not state.get("is_dead") and not state.get("is_ghost")
                and not state.get("is_in_combat") and not state.get("is_casting")
                and not state.get("world_map_open") and not state.get("input_blocked")
                and not (state.get("quest_ui") or {}).get("open")
                and not (state.get("vendor_ui") or {}).get("open")
                and not (state.get("gossip_ui") or {}).get("open"))

    @staticmethod
    def _apply_directive(proposal: Proposal, directive, *, world, goal, registry,
                         autonomy, count: int, recovery_for: str | None,
                         reason_prefix: str, now: float) -> tuple[Proposal, str | None]:
        if directive.action == "STOP_AND_OBSERVE":
            return Proposal.make(
                "WAIT", f"{reason_prefix}: friss megállás-megfigyelés szükséges",
                {"stuck_recovery_state": directive.state.value}), recovery_for
        if directive.action in {"BACKWARD", "TURN", "STRAFE", "JUMP_FORWARD"}:
            recovery = Proposal.make(
                "RECOVER", f"{reason_prefix}: {directive.action}",
                {"attempt": count, "recovery_step": directive.action,
                 "stuck_correlation": directive.correlation_id})
            if registry.available(recovery, world):
                autonomy.reset(now, "STUCK_CONFIRMED")
                return autonomy.choose([recovery], recovery, goal, world, now), recovery_for
            return proposal, recovery_for
        if directive.replan_scope:
            autonomy.reset(now, f"STUCK_{directive.replan_scope}_REPLAN")
            return Proposal.make(
                "WAIT", f"{reason_prefix}: {directive.replan_scope} újratervezés szükséges",
                {"stuck_recovery_state": directive.state.value,
                 "replan_scope": directive.replan_scope}), recovery_for
        return proposal, recovery_for
