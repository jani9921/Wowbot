"""Recovery proposal policy separated from the Agent orchestration loop."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .models import Proposal, number


@dataclass(frozen=True)
class RecoveryPlanningDecision:
    proposal: Proposal
    recovery_for: str | None = None


class RecoveryPlanner:
    """Select bounded recovery intents; never execute movement or input."""

    STATIONARY_THRESHOLD_SECONDS = 120.
    GHOST_REPLAN_LIMIT = 3

    def __init__(self) -> None:
        self.stationary_position: tuple | None = None
        self.stationary_since: float | None = None
        self.ghost_recovery_context = None
        self.ghost_recovery_attempts = 0
        self.ghost_failure_id = None
        self.ghost_recovery_origin = None

    def reset(self) -> None:
        self.stationary_position = None
        self.stationary_since = None
        self.ghost_recovery_context = None
        self.ghost_recovery_attempts = 0
        self.ghost_failure_id = None
        self.ghost_recovery_origin = None

    def apply(self, proposal: Proposal, *, world, goal, last_result: dict,
              navigation, registry, autonomy, failures: dict, now: float,
              current_recovery_for: str | None = None) -> RecoveryPlanningDecision:
        recovery_for = current_recovery_for
        supported_stuck = (
            last_result.get("skill") in {"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"}
            and last_result.get("outcome") == "FAILURE"
            and last_result.get("reason") == "supported_stuck")
        state = world.state
        from .vehicle_abilities import stationary_vehicle_controls
        if stationary_vehicle_controls(state) or state.get("on_taxi") is True:
            # A quest console is not a ground-route blockage. Never replace
            # its action/WAIT with a stale jump/strafe/reach recovery ladder.
            self.stationary_position = self.stationary_since = None
            return RecoveryPlanningDecision(proposal, None)
        if state.get("is_ghost") and proposal.parameters.get("purpose") == "CORPSE_RUN":
            return self._ghost_recovery(proposal, world, navigation, last_result, now,
                                        supported_stuck, recovery_for)
        if not state.get("is_dead") and not state.get("is_ghost"):
            self.ghost_recovery_context = None
            self.ghost_recovery_attempts = 0
            self.ghost_failure_id = None
            self.ghost_recovery_origin = None
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
            directive = self._safe_step(directive, navigation, state)
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
            directive = self._safe_step(navigation.observe_external_hard_stuck(
                "GLOBAL_STATIONARY_WATCHDOG", now), navigation, state)
            updated, _ = self._apply_directive(
                proposal, directive, world=world, goal=goal, registry=registry,
                autonomy=autonomy, count=count, recovery_for=recovery_for,
                reason_prefix="Globális beragadás-őrszem", now=now)
            if updated is not proposal and updated.skill == "RECOVER":
                failures["GLOBAL_STATIONARY_WATCHDOG"] = count + 1
                self.stationary_since = now
            proposal = updated
        return RecoveryPlanningDecision(proposal, recovery_for)

    def _ghost_recovery(self, proposal, world, navigation, last_result, now,
                        supported_stuck, recovery_for):
        """Only canonical, navmesh-validated MOVE can recover a corpse run.

        No living RECOVER key sequence, map or visual search is admitted by
        the death gate. Retain one finite budget per corpse/character context;
        confirmed movement or resurrection permits fresh recovery evidence.
        """
        state, params = world.state, proposal.parameters
        player = state.get("player_world_position") or {}
        context = (state.get("session_id"), params.get("instance_id"),
                   params.get("x"), params.get("y"))
        px, py = number(player.get("x")), number(player.get("y"))
        progressed = (self.ghost_recovery_origin is not None and px is not None and py is not None
                      and math.hypot(px-self.ghost_recovery_origin[0], py-self.ghost_recovery_origin[1]) >= 6.)
        if context != self.ghost_recovery_context or progressed:
            self.ghost_recovery_context = context
            self.ghost_recovery_attempts = 0
            self.ghost_failure_id = None
            self.ghost_recovery_origin = (px, py) if px is not None and py is not None else None
        failure_id = str(last_result.get("action_id") or last_result.get("key") or "corpse_stuck")
        if supported_stuck and failure_id != self.ghost_failure_id:
            self.ghost_failure_id = failure_id
            self.ghost_recovery_attempts += 1
            mark = getattr(navigation, "mark_current_route_danger", None)
            if callable(mark):
                mark(state, now, correlation_id=failure_id, ttl=120., cost=30., kind="CORPSE_ROUTE_STUCK")
            waypoint = getattr(navigation, "new_local_recovery_waypoint", None)
            if self.ghost_recovery_attempts <= self.GHOST_REPLAN_LIMIT and callable(waypoint):
                destination = waypoint(state, f"corpse-recovery:{failure_id}", now)
                if destination is not None:
                    return RecoveryPlanningDecision(Proposal.make(
                        "MOVE", "Szellem: validált MMAP kitérő az elakadt hullához vezető út helyett",
                        {**destination, "purpose": "CORPSE_RUN", "allow_combat": True,
                         "require_navmesh": True, "corpse_recovery_waypoint": True},
                        confidence=.9, priority=150), failure_id)
        if self.ghost_recovery_attempts > self.GHOST_REPLAN_LIMIT:
            return RecoveryPlanningDecision(Proposal.make(
                "WAIT", "A szellem útvonal-helyreállítása kimerült; új hulla/helyzet bizonyíték szükséges",
                {"purpose": "CORPSE_RUN", "waiting_for": ["CORPSE_OR_POSITION_UPDATE"]},
                priority=150), recovery_for)
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
    def _safe_step(directive, navigation, state: dict):
        """A backward/sideways/forward-jump step toward a drop becomes a turn
        (live 2026-10-13 17:57: backing off the pit spiral's fence)."""
        drops = getattr(navigation, "recovery_step_drops", None)
        if (getattr(directive, "action", None) in {"BACKWARD", "STRAFE", "JUMP_FORWARD"}
                and callable(drops) and drops(state, directive.action)):
            from dataclasses import replace
            return replace(directive, action="TURN")
        return directive

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
