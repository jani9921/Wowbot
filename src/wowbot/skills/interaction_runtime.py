"""Runtime composition for an active interaction approach."""
from __future__ import annotations

from dataclasses import dataclass, field

from wowbot.runtime import SkillResult, SkillStatus, failure_reason_from_legacy


@dataclass(frozen=True)
class InteractionRuntimeStep:
    commands: tuple = ()
    movement_lane: bool = False
    terminal_result: SkillResult | None = None
    event_type: str | None = None
    diagnostics: dict = field(default_factory=dict)
    stop_movement: bool = False
    set_segment_baseline: bool = False


class InteractionRuntimeRunner:
    """Advance a WORLD_ENTITY approach without dispatching or finalizing."""

    def __init__(self, navigation, interact_skill, visual_approach_skill=None) -> None:
        self.navigation = navigation
        self.interact_skill = interact_skill
        self.visual_approach_skill = visual_approach_skill

    def step_world_entity(self, active_state, world_state: dict,
                          observation_id: str, now: float) -> InteractionRuntimeStep:
        assessment = self.navigation.observe(
            world_state, observation_id, now, commanded=True)
        if assessment.terminal:
            self.navigation.cancel_movement()
            if not assessment.success:
                return InteractionRuntimeStep(terminal_result=SkillResult(
                    SkillStatus.FAILURE,
                    reason=failure_reason_from_legacy(assessment.reason),
                    retryable=True, replan_required=True,
                    metadata={"legacy_reason": assessment.reason}))
            resumed = self.interact_skill.resume_after_approach(active_state, world_state)
            if resumed.status is not SkillStatus.RUNNING:
                return InteractionRuntimeStep(terminal_result=resumed)
            return InteractionRuntimeStep(
                commands=tuple(resumed.commands), movement_lane=False,
                event_type="INTERACT_APPROACH_ARRIVED",
                diagnostics={"movement": self.navigation.movement_snapshot()})
        commands = tuple(self.navigation.command(world_state, observation_id, now))
        return InteractionRuntimeStep(
            commands=commands, movement_lane=True,
            event_type="INTERACT_APPROACH_CONTROL_UPDATE",
            diagnostics={"movement": self.navigation.movement_snapshot()})

    def step_visual(self, active_state, world_state: dict,
                    observation_id: str, now: float) -> InteractionRuntimeStep:
        if self.visual_approach_skill is None:
            raise RuntimeError("Visual approach skill is not configured")
        approach = self.visual_approach_skill.observe(
            active_state, world_state, observation_id, now)
        if approach.status is not SkillStatus.RUNNING:
            if approach.status is not SkillStatus.SUCCESS:
                return InteractionRuntimeStep(
                    terminal_result=approach, stop_movement=True)
            resumed = self.interact_skill.resume_after_approach(active_state, world_state)
            if resumed.status is not SkillStatus.RUNNING:
                return InteractionRuntimeStep(
                    terminal_result=resumed, stop_movement=True)
            return InteractionRuntimeStep(
                commands=tuple(resumed.commands), movement_lane=False,
                event_type="INTERACT_VISUAL_APPROACH_READY",
                diagnostics={"visual_approach": self.visual_approach_skill.snapshot(active_state)},
                stop_movement=True)
        commands = tuple(approach.commands)
        discrete = any(command.kind in {"CAMERA_PAN", "HOVER", "POINTER"}
                       or command.binding == "INTERACTTARGET" for command in commands)
        return InteractionRuntimeStep(
            commands=commands, movement_lane=not discrete,
            event_type="INTERACT_VISUAL_APPROACH_CONTROL_UPDATE",
            diagnostics={"visual_approach": self.visual_approach_skill.snapshot(active_state)})

    def start_approach(self, active_state, world_state: dict, observation_id: str,
                       now: float, request: dict) -> InteractionRuntimeStep:
        if request.get("kind") == "WORLD_ENTITY":
            destination = self.navigation.move_to_entity(
                world_state, request.get("expected_guid"), observation_id, now,
                stop_distance=request.get("stop_distance", 4.5))
            if destination is None:
                from wowbot.runtime import FailureReason
                return InteractionRuntimeStep(terminal_result=SkillResult(
                    SkillStatus.FAILURE, reason=FailureReason.TARGET_MOVED,
                    retryable=True, replan_required=True,
                    metadata={"legacy_reason": "target_moved"}))
            return InteractionRuntimeStep(
                commands=tuple(self.navigation.command(world_state, observation_id, now)),
                movement_lane=True, event_type="INTERACT_APPROACH_STARTED",
                diagnostics={"destination": destination}, set_segment_baseline=True)
        if self.visual_approach_skill is None:
            raise RuntimeError("Visual approach skill is not configured")
        started = self.visual_approach_skill.begin(
            active_state, world_state, observation_id, now, parameters=request)
        if started.status is SkillStatus.SUCCESS:
            resumed = self.interact_skill.resume_after_approach(active_state, world_state)
            if resumed.status is not SkillStatus.RUNNING:
                return InteractionRuntimeStep(terminal_result=resumed)
            return InteractionRuntimeStep(
                commands=tuple(resumed.commands), event_type="INTERACT_VISUAL_APPROACH_READY",
                diagnostics={"visual_approach": self.visual_approach_skill.snapshot(active_state)})
        if started.status is not SkillStatus.RUNNING:
            return InteractionRuntimeStep(terminal_result=started)
        commands = tuple(started.commands)
        discrete = any(command.kind in {"CAMERA_PAN", "HOVER", "POINTER"}
                       or command.binding == "INTERACTTARGET" for command in commands)
        return InteractionRuntimeStep(
            commands=commands, movement_lane=not discrete,
            event_type="INTERACT_VISUAL_APPROACH_STARTED",
            diagnostics={"visual_approach": self.visual_approach_skill.snapshot(active_state)})

    def step_verification(self, active_state, world_state: dict, result: SkillResult,
                          *, world_observation_id: str, visual_observation_id: str,
                          now: float) -> InteractionRuntimeStep:
        request = result.metadata.get("approach_request")
        if request:
            observation_id = (world_observation_id if request.get("kind") == "WORLD_ENTITY"
                              else visual_observation_id)
            return self.start_approach(active_state, world_state, observation_id, now, request)
        face_request = result.metadata.get("local_face_request")
        if face_request:
            faced = self.navigation.face_entity(
                world_state, face_request.get("expected_guid"))
            if not faced.commands:
                from wowbot.runtime import FailureReason
                return InteractionRuntimeStep(terminal_result=SkillResult(
                    SkillStatus.FAILURE, reason=FailureReason.FACING_FAILED,
                    retryable=True, replan_required=True,
                    metadata={"legacy_reason": "facing_failed"}))
            return InteractionRuntimeStep(
                commands=tuple(faced.commands), movement_lane=True,
                event_type="INTERACT_FACE_UPDATE")
        los_request = result.metadata.get("local_los_request")
        if los_request:
            commands = tuple(self.navigation.local_combat_reposition(
                world_state, los_request))
            if not commands:
                from wowbot.runtime import FailureReason
                return InteractionRuntimeStep(terminal_result=SkillResult(
                    SkillStatus.FAILURE, reason=FailureReason.LINE_OF_SIGHT,
                    retryable=True, replan_required=True,
                    metadata={"legacy_reason": "los_reposition_unavailable"}))
            return InteractionRuntimeStep(
                commands=commands, movement_lane=True,
                event_type="INTERACT_LOS_REPOSITION")
        if result.commands:
            return InteractionRuntimeStep(
                commands=tuple(result.commands), movement_lane=False,
                event_type="INTERACT_RETRY")
        return InteractionRuntimeStep()
