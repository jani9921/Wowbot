"""Canonical skill start routing without physical input dispatch."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import uuid

from wowbot.agent.models import Attempt, Prediction, Proposal
from .contracts import Intent, SkillResult, SkillStatus
from .entity_identity import world_entity_id


@dataclass(frozen=True)
class SkillPreparation:
    commands: tuple = ()
    set_segment_baseline: bool = False
    camera_parameters: dict | None = None


@dataclass(frozen=True)
class SkillLaunch:
    """One prepared attempt installed into the canonical lifecycle.

    The value contains commands but cannot dispatch them.  `active_skill` is
    supplied by the Agent and remains the only running-skill state owner.
    """

    attempt: Attempt
    commands: tuple
    start_result: SkillResult | None = None


class SkillExecutor:
    """Prepare and start one skill while leaving input to CommandDispatcher.

    ActiveSkillRuntime remains the lifecycle authority.  This class only
    routes a validated proposal to its owning domain skill and returns typed
    results/commands.
    """

    _MOVEMENT = frozenset({"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"})
    _DEFERRED_M0 = frozenset({
        "COMBAT", "DEFEND", "WAIT_EVENT", "LOOT", "OBJECT_USE", "QUEST_DIALOG", "FIELD_TURN_IN", "EXTRA_ACTION",
        "USE_ON_TARGET", "ASSIST", "FOLLOW_INSTRUCTION"})
    _EMPTY_START_ALLOWED = _MOVEMENT | _DEFERRED_M0 | frozenset({
        "SEEK_VISUAL_CUE", "VISUAL_APPROACH"})

    def __init__(self, *, registry, navigation, target_skill, interact_skill,
                 m0_skills, search_skill, visual_approach_skill) -> None:
        self.registry, self.navigation = registry, navigation
        self.target_skill, self.interact_skill = target_skill, interact_skill
        self.m0_skills, self.search_skill = m0_skills, search_skill
        self.visual_approach_skill = visual_approach_skill

    @classmethod
    def allows_empty_start(cls, skill: str) -> bool:
        return skill in cls._EMPTY_START_ALLOWED

    @classmethod
    def requires_active_begin(cls, skill: str) -> bool:
        return skill in cls._DEFERRED_M0 | frozenset({
            "TARGET", "INTERACT", "TALK", "SEEK_VISUAL_CUE", "VISUAL_APPROACH"})

    def prepare(self, proposal: Proposal, world, observation_id: str,
                now: float) -> SkillPreparation:
        skill = proposal.skill
        if skill in self._MOVEMENT:
            self.navigation.start_skill_request(
                skill, proposal.parameters, world.state, observation_id, now)
            return SkillPreparation(
                tuple(self.navigation.command(world.state, observation_id, now)), True)
        if skill in self._DEFERRED_M0 | {"VISUAL_APPROACH", "SEEK_VISUAL_CUE"}:
            return SkillPreparation()
        intent = Intent(
            skill, proposal.parameters,
            str(proposal.parameters.get("guid") or "") or None,
            str(proposal.parameters.get("objective_id") or "") or None)
        if skill == "TARGET":
            return SkillPreparation(tuple(self.target_skill.commands_for(intent)))
        if skill in {"INTERACT", "TALK"}:
            return SkillPreparation(tuple(self.interact_skill.commands_for(intent)))
        commands = tuple(self.registry.commands(proposal, world))
        camera_parameters = None
        if skill in {"CAMERA_CONTROL", "REACQUIRE_TARGET"}:
            camera_parameters = ({**proposal.parameters, "camera_action": "REACQUIRE_TRACK"}
                                 if skill == "REACQUIRE_TARGET" else proposal.parameters)
        return SkillPreparation(commands, camera_parameters=camera_parameters)

    def begin(self, active_state, world_state: dict, visual_observation_id: str,
              now: float, prepared_commands: tuple) -> SkillResult:
        skill = active_state.skill_type
        if self.m0_skills.handles(skill):
            return self.m0_skills.begin(active_state, world_state, now)
        if skill == "SEEK_VISUAL_CUE":
            return self.search_skill.begin(
                active_state, world_state, visual_observation_id, now)
        if skill == "VISUAL_APPROACH":
            return self.visual_approach_skill.begin(
                active_state, world_state, visual_observation_id, now)
        return SkillResult(SkillStatus.RUNNING, commands=prepared_commands)

    def create_attempt(self, proposal: Proposal, commands: tuple, *, world, goal,
                       current_plan, timeouts, memory, now: float) -> Attempt:
        """Create the immutable pre-action baseline and verification window."""
        action_id = uuid.uuid4().hex
        contract = self.registry.contracts[proposal.skill]
        base_timeout = (
            self.navigation.max_reach_seconds if proposal.skill in self._MOVEMENT
            else self.visual_approach_skill.max_seconds if proposal.skill == "VISUAL_APPROACH"
            else self.search_skill.max_seconds if proposal.skill == "SEEK_VISUAL_CUE"
            else contract.timeout)
        base_timeout = timeouts.resolve(proposal.skill, base_timeout, world.state)
        timing = (memory.verification_window(
            proposal.skill, memory.learning_context(world.state, goal.domain), base_timeout)
                  if memory else {"earliest": .05, "likely_start": .1,
                                  "likely_end": base_timeout*.7, "deadline": base_timeout})
        deadline = now + timing["deadline"]
        prediction = Prediction(
            uuid.uuid4().hex, action_id, contract.expected, now, deadline,
            world.latest.observation_id, confidence=proposal.confidence,
            provenance=proposal.evidence, earliest_expected=now+timing["earliest"],
            likely_start=now+timing["likely_start"],
            likely_end=now+timing["likely_end"],
            expected_observations=(contract.success_condition,))
        # Use the merged canonical state, never a compact FAST packet, as the
        # verifier baseline. Otherwise existing inventory can look newly won.
        return Attempt(
            action_id, proposal, deepcopy(world.state), world.latest.observation_id,
            now, deadline, commands, prediction, current_plan.plan_id)

    def install_attempt(self, proposal: Proposal, prepared_commands: tuple, *,
                        active_skill, world, goal, current_plan, timeouts,
                        memory, visual_observation_id: str,
                        now: float) -> SkillLaunch:
        """Create exactly one attempt and, when required, start its lifecycle.

        This is the canonical bridge between proposal preparation and
        `ActiveSkillRuntime.start`.  It deliberately owns neither physical
        dispatch nor terminal finalization; both remain Agent responsibilities.
        """
        attempt = self.create_attempt(
            proposal, prepared_commands, world=world, goal=goal,
            current_plan=current_plan, timeouts=timeouts, memory=memory,
            now=now)
        commands = prepared_commands
        started = None
        if self.requires_active_begin(proposal.skill):
            parameters = proposal.parameters
            state = active_skill.start(
                intent=Intent(
                    proposal.skill, parameters,
                    world_entity_id(parameters.get("guid")),
                    str(parameters.get("objective_id") or "") or None),
                attempt=attempt, now=now, before_snapshot=attempt.baseline,
                skill_context={
                    "plan_id": attempt.plan_id,
                    "action_id": attempt.action_id,
                    "world_snapshot_version": getattr(world, "revision", None),
                },
            )
            started = self.begin(
                state, world.state, visual_observation_id, now,
                prepared_commands)
            commands = tuple(started.commands)
            attempt.commands = commands
        return SkillLaunch(attempt, tuple(commands), started)
