"""Input-free routing for one observation of an already-active skill."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Outcome
from wowbot.runtime import (FailureReason, SkillResult, SkillStatus,
                            failure_reason_from_legacy)


_PERSISTENT_INPUT = frozenset({"APPROACH_TARGET", "VISUAL_APPROACH", "SEEK_VISUAL_CUE"})


@dataclass(frozen=True)
class ActiveSkillSupervisionStep:
    commands: tuple = ()
    movement_lane: bool = False
    event_type: str | None = None
    diagnostics: dict = field(default_factory=dict)
    stop_movement: bool = False
    set_segment_baseline: bool = False
    terminal_outcome: Outcome | None = None
    reason: str | None = None
    typed_reason: FailureReason | None = None
    dispatch_failure_terminal: bool = False
    return_after_terminal: bool = False
    yield_tick: bool = False
    camera_action: str | None = None
    movement_assessment: object | None = None
    next_segment_baseline: dict | None = None
    # Sent on the discrete lane next to a movement lease (CAMERA_GLANCE).
    side_commands: tuple = ()
    preserve_navigation: bool = False


class ActiveSkillSupervisor:
    """Route verification to the owning domain runner, without side effects.

    The supplied domain runners may update their own input-free FSMs and
    NavigationService state. This component never dispatches commands, owns an
    active skill, or finalizes a terminal result.
    """

    def __init__(self, *, m0_skills, verification_engine, interaction_runtime,
                 combat_runtime, loot_runtime, registry,
                 movement_runtime=None, visual_runtime=None) -> None:
        self.m0_skills = m0_skills
        self.verification_engine = verification_engine
        self.interaction_runtime = interaction_runtime
        self.combat_runtime = combat_runtime
        self.loot_runtime = loot_runtime
        self.registry = registry
        self.movement_runtime = movement_runtime
        self.visual_runtime = visual_runtime

    def step(self, attempt, active_state, world, *, world_observation_id: str,
             visual_observation_id: str, now: float,
             segment_baseline: dict | None = None,
             reference_reach_interrupt: str | dict | None = None,
             allow_route_queries: bool = True) -> ActiveSkillSupervisionStep:
        skill = attempt.proposal.skill
        state = world.state
        route_options = {} if allow_route_queries else {'allow_route_queries':False}
        if ((getattr(attempt.proposal, 'parameters', None) or {}).get('purpose') == 'CORPSE_RUN'
                and state.get('is_ghost') is not True):
            return self._verified_outcome(
                skill, Outcome.CANCELLED, 'corpse_run_no_longer_ghost', state,
                stop_movement=True, verifier='DEATH_STATE_TRANSITION_VERIFIER')
        if skill in {"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"}:
            return self._movement(
                attempt, state, world.latest, world_observation_id, now,
                segment_baseline, reference_reach_interrupt)
        if skill in {"SEEK_VISUAL_CUE", "VISUAL_APPROACH"}:
            return self._visual(active_state, state, visual_observation_id, now)
        if skill == "TARGET":
            result = self.m0_skills.verify(active_state, state, now)
            if result.status is SkillStatus.RUNNING and result.commands:
                # Hover-confirm-click (see skills/hover_confirm.py).
                return ActiveSkillSupervisionStep(commands=tuple(result.commands),
                                                  event_type="TARGET_HOVER_CONFIRM_UPDATE")
            return self._project(skill, result, state)
        if skill in {"INTERACT", "TALK"}:
            return self._interaction(active_state, state, world_observation_id,
                                     visual_observation_id, now, **route_options)
        if skill in {"COMBAT", "DEFEND"}:
            return self._combat(active_state, state, world_observation_id, now, **route_options)
        if skill == "LOOT":
            context = active_state.skill_context.get("loot", {})
            runtime_step = (
                self.loot_runtime.continue_approach(
                    active_state, state, world_observation_id, now, **route_options)
                if context.get("approach_request") else
                self.loot_runtime.step_verification(
                    active_state, state, world_observation_id, now, **route_options))
            if runtime_step.terminal_result is not None:
                return self._project(skill, runtime_step.terminal_result, state)
            return self._runtime(runtime_step, skill, state)
        if skill == "OBJECT_USE":
            result = self.m0_skills.verify(active_state, state, now)
            if result.status is SkillStatus.RUNNING and result.commands:
                return ActiveSkillSupervisionStep(commands=tuple(result.commands),
                    event_type="OBJECT_USE_CONTROL_UPDATE",
                    diagnostics={'post_use_motion':result.metadata['post_use_motion']}
                    if 'post_use_motion' in result.metadata else {})
            return self._project(skill, result, state)
        if skill == "USE_ON_TARGET":
            result = self.m0_skills.verify(active_state, state, now)
            if result.status is SkillStatus.RUNNING and result.commands:
                return ActiveSkillSupervisionStep(commands=tuple(result.commands),
                                                  event_type="ITEM_USE_CONTROL_UPDATE")
            return self._project(skill, result, state)
        if skill == "REST":
            # The one food press of a rest (skills/rest.py); otherwise input-free.
            result = self.m0_skills.verify(active_state, state, now)
            if result.status is SkillStatus.RUNNING and result.commands:
                return ActiveSkillSupervisionStep(commands=tuple(result.commands),
                                                  event_type="REST_CONTROL_UPDATE")
            return self._project(skill, result, state)
        if skill in {"WAIT_EVENT", "QUEST_DIALOG", "FIELD_TURN_IN", "EXTRA_ACTION", "ADDON_ACTION",
                     "ASSIST", "FOLLOW_INSTRUCTION"}:
            return self._project(
                skill, self.m0_skills.verify(active_state, state, now), state)

        outcome, reason = self.registry.verify(attempt, world, now)
        if outcome == Outcome.PENDING:
            commands = (tuple(self.registry.commands(attempt.proposal, world))
                        if skill in _PERSISTENT_INPUT else ())
            return ActiveSkillSupervisionStep(
                commands=commands, movement_lane=bool(commands),
                dispatch_failure_terminal=False)
        return self._verified_outcome(
            skill, outcome, reason, state,
            stop_movement=skill in _PERSISTENT_INPUT,
            verifier="GENERIC_POSTCONDITION_VERIFIER")

    def _movement(self, attempt, state: dict, latest, observation_id: str,
                  now: float, segment_baseline: dict | None,
                  visual_interrupt: str | dict | None) -> ActiveSkillSupervisionStep:
        if ((state.get("quest_ui") or {}).get("open") is True
                or state.get("quest_ui_open") is True
                or (state.get("gossip_ui") or {}).get("open") is True
                or state.get("gossip_open") is True):
            # The click can open its dialog one telemetry page *after* an
            # unrelated route was launched. UI ownership preempts that route
            # immediately; reaching a waypoint is not inferred from the UI.
            return self._verified_outcome(
                attempt.proposal.skill, Outcome.CANCELLED,
                "interaction_ui_opened_during_move", state,
                stop_movement=True, verifier="INTERACTION_UI_INTERRUPT_VERIFIER")
        if visual_interrupt:
            interrupt = (visual_interrupt if isinstance(visual_interrupt, dict)
                         else {"reason": str(visual_interrupt)})
            projected = self._verified_outcome(
                attempt.proposal.skill,
                (Outcome.CANCELLED if interrupt.get("kind") in {
                    "QUEST_ROUTE_VISUAL_CUE", "OBJECTIVE_UNIT_HOVERED",
                    "QUEST_ROUTE_NPC_HOVERED", "SERVER_TURN_IN_ENTITY_AVAILABLE", "SERVER_OBJECTIVE_NPC_AVAILABLE",
                    "SERVER_TURN_IN_INTERACTION_READY", "SERVER_QUEST_OBJECT_CHANGED",
                    "SERVER_QUEST_OBJECT_PASSING", "QUEST_OBJECT_HOVERED",
                    "SERVER_QUEST_OBJECT_EDGE", "RESCUE_NPC_SOFT_INTERACT",
                    "MOUNT_FOR_LONG_ROUTE", "FLIGHT_MODE_AVAILABLE", "VEHICLE_QUEST_CONTROLS"}
                 else Outcome.SUCCESS),
                str(interrupt.get("reason") or "visual_navigation_interrupt"), state,
                stop_movement=True, verifier="VISUAL_INTERRUPT_VERIFIER")
            values = dict(projected.__dict__)
            values["reason"] = str(interrupt.get("reason") or "visual_navigation_interrupt")
            values["diagnostics"] = {**projected.diagnostics,
                                     "movement_visual_handoff": dict(interrupt)}
            return ActiveSkillSupervisionStep(**values)
        provenance = latest.payload.get("provenance") or {}
        if (latest.source == "WORLD3D"
                and provenance.get("control_lane") == "REFERENCE_REACH_SEARCH"):
            return ActiveSkillSupervisionStep(yield_tick=True)
        movement = self.movement_runtime.step(
            attempt, state, observation_id, now, segment_baseline)
        assessment = movement.assessment
        if assessment.terminal:
            projected = self._verified_outcome(
                attempt.proposal.skill,
                Outcome.SUCCESS if assessment.success else Outcome.FAILURE,
                assessment.reason, state, stop_movement=True,
                verifier="MOVEMENT_POSTCONDITION_VERIFIER")
            values = dict(projected.__dict__)
            values["movement_assessment"] = assessment
            values["next_segment_baseline"] = movement.next_segment_baseline
            return ActiveSkillSupervisionStep(**values)
        from wowbot.execution.command_dispatch import flight_ability_tap
        return ActiveSkillSupervisionStep(
            commands=tuple(movement.commands),
            movement_lane=not flight_ability_tap(tuple(movement.commands)),
            event_type="MOVEMENT_CONTROL_UPDATE",
            movement_assessment=assessment,
            next_segment_baseline=movement.next_segment_baseline,
            side_commands=self._sweep_glance(attempt, movement.commands, now))

    GLANCE_SECONDS = 2.5
    GLANCE_OFFSET = .14

    def _sweep_glance(self, attempt, movement_commands, now: float) -> tuple:
        """Zone sweep (user 2026-10-10): keep walking, the camera looks left
        and right in turn; Retail's follow camera swings back by itself."""
        if (attempt.proposal.parameters.get("scan_while_moving") is not True
                or not any(command.binding == "MOVEFORWARD" for command in movement_commands)):
            return ()
        glance = self.__dict__.setdefault("_glance", {})
        if glance.get("action_id") != attempt.action_id:
            glance.clear()
            glance.update(action_id=attempt.action_id, at=now, side=1)
            return ()
        if now - glance["at"] < self.GLANCE_SECONDS:
            return ()
        glance["side"] = -glance["side"]
        glance["at"] = now
        from .models import Command
        return (Command("CAMERA_GLANCE", x=.5 + self.GLANCE_OFFSET*glance["side"], y=.40,
                        button="LEFT", duration=.22),)

    def _visual(self, active_state, state: dict, observation_id: str,
                now: float) -> ActiveSkillSupervisionStep:
        runtime_step = (
            self.visual_runtime.step_search(active_state, state, observation_id, now)
            if active_state.skill_type == "SEEK_VISUAL_CUE" else
            self.visual_runtime.step_approach(active_state, state, observation_id, now))
        projected = self._runtime(
            runtime_step, active_state.skill_type, state)
        values = dict(projected.__dict__)
        values["camera_action"] = getattr(runtime_step, "camera_action", None)
        # A visual terminal result must be replanned on the same fresh frame:
        # the confirmed screen anchor may disappear on the next addon page.
        values["return_after_terminal"] = False
        return ActiveSkillSupervisionStep(**values)

    def _interaction(self, active_state, state: dict, world_observation_id: str,
                     visual_observation_id: str, now: float, *, allow_route_queries=True) -> ActiveSkillSupervisionStep:
        route_options = {} if allow_route_queries else {'allow_route_queries':False}
        context = active_state.skill_context.get("interaction", {})
        approach = context.get("approach_request")
        if approach:
            if approach.get("kind") == "WORLD_ENTITY":
                return self._runtime(self.interaction_runtime.step_world_entity(
                    active_state, state, world_observation_id, now, **route_options),
                    active_state.skill_type, state)
            if approach.get("purpose") == "INTERACT":
                return self._runtime(self.interaction_runtime.step_visual(
                    active_state, state, visual_observation_id, now),
                    active_state.skill_type, state)
            return ActiveSkillSupervisionStep(
                terminal_outcome=Outcome.FAILURE,
                reason=FailureReason.INTERNAL_ERROR.value.lower(),
                typed_reason=FailureReason.INTERNAL_ERROR,
                return_after_terminal=True)
        result = self.m0_skills.verify(active_state, state, now)
        if result.status is SkillStatus.RUNNING:
            return self._runtime(self.interaction_runtime.step_verification(
                active_state, state, result,
                world_observation_id=world_observation_id,
                visual_observation_id=visual_observation_id, now=now, **route_options),
                active_state.skill_type, state)
        return self._project(active_state.skill_type, result, state)

    def _combat(self, active_state, state: dict, observation_id: str,
                now: float, *, allow_route_queries=True) -> ActiveSkillSupervisionStep:
        from wowbot.skills.navigation_handoff import deadline
        route_options = {} if allow_route_queries else {'allow_route_queries':False}
        context = active_state.skill_context.get("combat", {})
        if context.get("approach_request"):
            return self._runtime(self.combat_runtime.continue_approach(
                active_state, state, observation_id, now, **route_options),
                active_state.skill_type, state)
        result = self.m0_skills.verify(active_state, state, now)
        if result.status is SkillStatus.RUNNING:
            return self._runtime(self.combat_runtime.step_verification(
                state, result, observation_id, now, deadline=deadline(active_state), **route_options),
                active_state.skill_type, state)
        return self._project(active_state.skill_type, result, state)

    def _project(self, skill: str, result, state: dict) -> ActiveSkillSupervisionStep:
        decision = self.verification_engine.confirm(skill, result, state)
        if decision.pending:
            return ActiveSkillSupervisionStep()
        return ActiveSkillSupervisionStep(
            terminal_outcome=(Outcome.CANCELLED if result.status is SkillStatus.CANCELLED else
                              Outcome.SUCCESS if decision.success else Outcome.FAILURE),
            reason=decision.reason, typed_reason=decision.typed_reason,
            diagnostics={
                "verification_method": decision.verifier,
                "verification_evidence": list(decision.evidence),
                **({'post_use_motion':result.metadata['post_use_motion']}
                   if skill == 'OBJECT_USE' and 'post_use_motion' in result.metadata else {}),
            })

    def _runtime(self, step, skill: str, state: dict) -> ActiveSkillSupervisionStep:
        if getattr(step, 'plan_pending', False):
            return ActiveSkillSupervisionStep(yield_tick=True, stop_movement=True, preserve_navigation=True,
                reason='skill_navigation_plan_pending', event_type='SKILL_NAVIGATION_PLAN_PENDING',
                diagnostics=dict(step.diagnostics))
        result = step.terminal_result
        if result is not None:
            projected = self._project(skill, result, state)
            values = dict(projected.__dict__)
            if not projected.reason:
                values["reason"] = (result.metadata.get("legacy_reason")
                                    or result.metadata.get("reason")
                                    or (result.reason.value.lower() if result.reason
                                        else "active_skill_runtime_failed"))
            values["stop_movement"] = bool(getattr(step, "stop_movement", False))
            if result.metadata.get('navigation_failure'):
                values['diagnostics'] = {**values['diagnostics'],
                    'navigation_failure':result.metadata['navigation_failure']}
            values["dispatch_failure_terminal"] = True
            values["return_after_terminal"] = True
            return ActiveSkillSupervisionStep(**values)
        return ActiveSkillSupervisionStep(
            commands=tuple(step.commands),
            movement_lane=bool(step.movement_lane),
            event_type=step.event_type,
            diagnostics=dict(step.diagnostics),
            stop_movement=bool(getattr(step, "stop_movement", False)),
            set_segment_baseline=bool(getattr(step, "set_segment_baseline", False)),
            dispatch_failure_terminal=True)

    def _verified_outcome(self, skill: str, outcome: Outcome, reason: str,
                          state: dict, *, stop_movement: bool = False,
                          verifier: str) -> ActiveSkillSupervisionStep:
        if outcome == Outcome.PENDING:
            return ActiveSkillSupervisionStep()
        typed_reason = (
            None if outcome == Outcome.SUCCESS else
            FailureReason.CANCELLED if outcome == Outcome.CANCELLED else
            failure_reason_from_legacy(reason))
        result = SkillResult(
            SkillStatus.SUCCESS if outcome == Outcome.SUCCESS else
            SkillStatus.CANCELLED if outcome == Outcome.CANCELLED else
            SkillStatus.FAILURE,
            typed_reason,
            metadata={"legacy_reason": reason})
        decision = self.verification_engine.confirm(
            skill, result, state, verifier=verifier)
        return ActiveSkillSupervisionStep(
            terminal_outcome=(Outcome.SUCCESS if decision.success else outcome),
            reason=reason,
            typed_reason=decision.typed_reason,
            stop_movement=stop_movement,
            diagnostics={
                "verification_method": decision.verifier,
                "verification_evidence": list(decision.evidence),
            })
