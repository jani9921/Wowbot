"""Canonical per-attempt wrapper for the existing visual servo."""
from __future__ import annotations

from wowbot.agent.visual_approach import VisualApproachController
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus


class VisualApproachSkill:
    _CONTEXT_KEY = "visual_approach_controller"

    def __init__(self, bindings=None) -> None:
        self.bindings = bindings
        self.max_seconds = VisualApproachController.max_seconds
        self._last_snapshot = {"phase": "IDLE", "authority": "ActiveSkillRuntime"}

    @staticmethod
    def _reason(value: str) -> FailureReason:
        if value == "target_identity_changed" or "visual_track_lost" in value:
            return FailureReason.TARGET_LOST
        if value == "target_dead":
            return FailureReason.TARGET_DEAD
        if "deadline" in value or "timeout" in value:
            return FailureReason.TIMEOUT
        return FailureReason.INTERNAL_ERROR

    def _controller(self, active: ActiveSkillState) -> VisualApproachController:
        controller = active.skill_context.get(self._CONTEXT_KEY)
        if not isinstance(controller, VisualApproachController):
            raise RuntimeError("Visual approach was observed before begin")
        return controller

    def _result(self, controller: VisualApproachController, assessment, state: dict,
                observation_id: str, now: float) -> SkillResult:
        if assessment.terminal:
            self._last_snapshot = {**controller.snapshot(), "authority": "ActiveSkillRuntime"}
            if assessment.success:
                return SkillResult(SkillStatus.SUCCESS, metadata={"reason": assessment.reason})
            return SkillResult(SkillStatus.FAILURE, self._reason(assessment.reason),
                               replan_required=True,
                               metadata={"legacy_reason": assessment.reason})
        commands = controller.command(state, observation_id, now)
        self._last_snapshot = {**controller.snapshot(), "authority": "ActiveSkillRuntime"}
        return SkillResult(SkillStatus.RUNNING, commands=commands,
                           metadata={"reason": assessment.reason})

    def begin(self, active: ActiveSkillState, state: dict, observation_id: str, now: float,
              *, parameters: dict | None = None) -> SkillResult:
        """Start the shared servo for this active skill.

        ``parameters`` permits a parent skill (currently M0 Interact) to own
        the lifecycle while supplying its already-validated approach contract.
        The servo remains per-attempt state and never becomes an independent
        planner action in that mode.
        """
        controller = VisualApproachController(self.bindings)
        active.skill_context[self._CONTEXT_KEY] = controller
        active.phase = "APPROACH"
        approach_parameters = parameters if parameters is not None else active.intent.parameters
        return self._result(controller, controller.start(approach_parameters, state, observation_id, now),
                            state, observation_id, now)

    def observe(self, active: ActiveSkillState, state: dict, observation_id: str, now: float) -> SkillResult:
        controller = self._controller(active)
        return self._result(controller, controller.observe(state, observation_id, now),
                            state, observation_id, now)

    def phase(self, active: ActiveSkillState | None = None) -> str:
        if active is not None:
            controller = active.skill_context.get(self._CONTEXT_KEY)
            if isinstance(controller, VisualApproachController):
                return controller.phase.value
        return str(self._last_snapshot.get("phase") or "IDLE")

    def snapshot(self, active: ActiveSkillState | None = None) -> dict:
        if active is not None:
            controller = active.skill_context.get(self._CONTEXT_KEY)
            if isinstance(controller, VisualApproachController):
                return {**controller.snapshot(), "authority": "ActiveSkillRuntime"}
        return dict(self._last_snapshot)

    def reset_diagnostics(self) -> None:
        self._last_snapshot = {"phase": "IDLE", "authority": "ActiveSkillRuntime"}
