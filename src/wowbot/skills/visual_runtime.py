"""Runtime composition for active visual search and visual approach skills."""
from __future__ import annotations

from dataclasses import dataclass, field

from wowbot.runtime import SkillResult, SkillStatus


@dataclass(frozen=True, slots=True)
class VisualRuntimeStep:
    commands: tuple = ()
    movement_lane: bool = False
    terminal_result: SkillResult | None = None
    event_type: str | None = None
    diagnostics: dict = field(default_factory=dict)
    stop_movement: bool = False
    camera_action: str | None = None


class VisualRuntimeRunner:
    """Advance visual skills without dispatching input or finalizing attempts."""

    def __init__(self, search_skill, visual_approach_skill) -> None:
        self.search_skill = search_skill
        self.visual_approach_skill = visual_approach_skill

    def step_search(self, active_state, world_state: dict,
                    observation_id: str, now: float) -> VisualRuntimeStep:
        result = self.search_skill.observe(
            active_state, world_state, observation_id, now)
        if result.status is not SkillStatus.RUNNING:
            return VisualRuntimeStep(terminal_result=result, stop_movement=True)
        commands = tuple(result.commands)
        camera = any(command.kind == "CAMERA_PAN" for command in commands)
        hover = any(command.kind == "HOVER" for command in commands)
        pointer = any(command.kind == "POINTER" for command in commands)
        return VisualRuntimeStep(
            commands=commands,
            movement_lane=bool(commands) and not camera and not hover and not pointer,
            event_type="SEEK_VISUAL_CUE_CONTROL_UPDATE",
            diagnostics={"vision_seek": self.search_skill.snapshot(active_state)},
            stop_movement=camera or hover, camera_action="SCAN_SECTOR" if camera else None)

    def step_approach(self, active_state, world_state: dict,
                      observation_id: str, now: float) -> VisualRuntimeStep:
        result = self.visual_approach_skill.observe(
            active_state, world_state, observation_id, now)
        if result.status is not SkillStatus.RUNNING:
            return VisualRuntimeStep(terminal_result=result, stop_movement=True)
        commands = tuple(result.commands)
        camera = any(command.kind == "CAMERA_PAN" for command in commands)
        # POINTER keeps the forward lease: discrete input, no movement stop.
        pointer = any(command.kind == "POINTER" for command in commands)
        discrete = camera or pointer or any(
            command.kind == "HOVER" or command.binding == "INTERACTTARGET"
            for command in commands)
        occluded = (not commands
                    and self.visual_approach_skill.phase(active_state) == "OCCLUDED")
        return VisualRuntimeStep(
            commands=commands, movement_lane=bool(commands) and not discrete,
            event_type="VISUAL_APPROACH_CONTROL_UPDATE",
            diagnostics={"visual_approach": self.visual_approach_skill.snapshot(active_state)},
            stop_movement=(discrete and not camera and not pointer) or occluded,
            camera_action="REACQUIRE_TRACK" if camera else None)
