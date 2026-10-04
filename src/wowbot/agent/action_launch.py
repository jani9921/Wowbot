"""Non-dispatching orchestration for starting one selected skill."""
from __future__ import annotations

from dataclasses import dataclass

from wowbot.execution import DispatchLane
from wowbot.runtime import FailureReason, SkillStatus

from .models import Outcome, Proposal


@dataclass(frozen=True)
class ImmediateTerminal:
    outcome: Outcome
    reason: str
    typed_reason: FailureReason | None = None


@dataclass(frozen=True)
class InstalledAction:
    attempt: object
    commands: tuple
    immediate_terminal: ImmediateTerminal | None
    dispatch_lane: DispatchLane


class ActionLaunchCoordinator:
    """Compose SkillExecutor launch data without owning physical execution.

    SkillExecutor and ActiveSkillRuntime remain the canonical preparation and
    lifecycle authorities.  This coordinator only removes launch-policy
    branching from the Agent: empty-start eligibility, typed immediate-result
    projection and dispatch-lane selection.  It never dispatches or finalizes.
    """

    _MOVEMENT = frozenset({"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"})
    _PERSISTENT_INPUT = frozenset({
        "APPROACH_TARGET", "VISUAL_APPROACH", "SEEK_VISUAL_CUE",
    })

    def __init__(self, skill_executor, m0_skills, verification_engine) -> None:
        self.skill_executor = skill_executor
        self.m0_skills = m0_skills
        self.verification_engine = verification_engine

    def prepare(self, proposal: Proposal, world, observation_id: str, now: float):
        return self.skill_executor.prepare(proposal, world, observation_id, now)

    def may_install(self, proposal: Proposal, commands: tuple) -> bool:
        return bool(commands) or self.skill_executor.allows_empty_start(proposal.skill)

    def install(self, proposal: Proposal, commands: tuple, *, active_skill,
                world, goal, current_plan, timeouts, memory,
                visual_observation_id: str, now: float) -> InstalledAction:
        launch = self.skill_executor.install_attempt(
            proposal, commands, active_skill=active_skill, world=world,
            goal=goal, current_plan=current_plan, timeouts=timeouts,
            memory=memory, visual_observation_id=visual_observation_id,
            now=now)
        terminal = self._immediate_terminal(proposal, launch.start_result, world.state)
        return InstalledAction(
            launch.attempt, tuple(launch.commands), terminal,
            self.dispatch_lane(proposal, tuple(launch.commands)))

    def _immediate_terminal(self, proposal: Proposal, started,
                            world_state: dict) -> ImmediateTerminal | None:
        if started is None or started.status is SkillStatus.RUNNING:
            return None
        if self.m0_skills.handles(proposal.skill):
            decision = self.verification_engine.project(
                proposal.skill, started, world_state)
            if decision.pending:
                return None
            return ImmediateTerminal(
                Outcome.SUCCESS if decision.success else Outcome.FAILURE,
                decision.reason, started.reason)
        reason = (started.metadata.get("reason")
                  or started.metadata.get("legacy_reason")
                  or (started.reason.value.lower()
                      if started.reason else "skill_start_failed"))
        if started.status is SkillStatus.SUCCESS:
            # A start routine cannot author success. Keep the installed skill
            # alive so the next observation reaches its verifier.
            return None
        return ImmediateTerminal(Outcome.FAILURE, reason, started.reason)

    @classmethod
    def dispatch_lane(cls, proposal: Proposal, commands: tuple) -> DispatchLane:
        if (proposal.skill in {"CAMERA_CONTROL", "REACQUIRE_TARGET"}
                or (proposal.skill == "INSPECT"
                    and proposal.parameters.get("camera_pan"))):
            if (len(commands) == 1 and commands[0].kind == "BIND"
                    and commands[0].binding in {"TURNLEFT", "TURNRIGHT"}):
                # Follow-camera horizontal view control is physical player
                # steering and must use the single watchdog-owned movement
                # lease, never the ordinary discrete input lane.
                return DispatchLane.MOVEMENT
        if (proposal.skill in {"VISUAL_APPROACH", "SEEK_VISUAL_CUE"}
                and any(command.kind in {"CAMERA_PAN", "HOVER", "POINTER"}
                        or command.binding == "INTERACTTARGET"
                        for command in commands)):
            return DispatchLane.DISCRETE
        if proposal.skill in cls._MOVEMENT | cls._PERSISTENT_INPUT:
            return DispatchLane.MOVEMENT
        return DispatchLane.DISCRETE
