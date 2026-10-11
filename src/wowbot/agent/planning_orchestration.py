"""One event-driven high-level planning cycle, without execution authority."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Plan, Proposal


@dataclass(frozen=True)
class PlanningCycleResult:
    proposal: Proposal
    proposals: tuple[Proposal, ...]
    recovery_resume: Proposal | None
    recovery_resume_ready: bool
    reasoning_observation: object | None = None
    events: tuple[tuple[str, dict], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PlanUpdate:
    plan: Plan | None
    signature: tuple | None
    changed: bool


@dataclass(frozen=True)
class PlanningResolution:
    """Final input-free result of navigation/recovery/plan adaptation."""

    proposal: Proposal
    proposals: tuple[Proposal, ...]
    recovery_for: str | None
    plan_update: PlanUpdate


class PlanningOrchestrator:
    """Compose proposal sources and arbitration; never dispatch a command."""

    def __init__(self, planner, goals, registry, supervisor, autonomy, reasoner=None, *,
                 navigation_adapter=None, recovery_planner=None) -> None:
        self.planner, self.goals, self.registry = planner, goals, registry
        self.supervisor, self.autonomy, self.reasoner = supervisor, autonomy, reasoner
        self.navigation_adapter = navigation_adapter
        self.recovery_planner = recovery_planner

    def choose(self, goal, world, planning_world: dict, now: float, *,
               recovery_resume: Proposal | None,
               recovery_resume_ready: bool) -> PlanningCycleResult:
        proposals = self.goals.filter(
            self.planner.candidates(goal, planning_world, now),
            self.registry.contracts, now)
        preferred = self._inject_supervisor_resume(proposals, world, now)
        events: list[tuple[str, dict]] = []
        recovery_resume, recovery_resume_ready, recovery_preferred = self._inject_recovery_resume(
            proposals, recovery_resume, recovery_resume_ready, world, now, events)
        if recovery_preferred is not None:
            preferred = recovery_preferred
        if not proposals:
            proposals = [Proposal.make(
                "WAIT", "Minden jelenlegi részfeladat ideiglenesen unresolved; új evidence szükséges")]
        proposal = (preferred if preferred is not None else
                    self.reasoner.advise(goal, world, proposals, now)
                    if self.reasoner else proposals[0])
        reasoning_observation = self.reasoner.take_observation(world, now) if self.reasoner else None
        if (proposal.confidence < .55
                and proposal.skill not in {"WAIT", "INSPECT", "DEFEND", "ESCAPE", "COMBAT"}):
            proposal = next(
                (item for item in proposals if item.skill == "INSPECT" and item.confidence >= .55),
                Proposal.make(
                    "WAIT", "A terv confidence-e végrehajtáshoz kevés; további evidence szükséges",
                    {"rejected_proposal": proposal.key}, confidence=proposal.confidence))
        proposal = self.autonomy.choose(proposals, proposal, goal, world, now)
        return PlanningCycleResult(
            proposal, tuple(proposals), recovery_resume, recovery_resume_ready,
            reasoning_observation, tuple(events))

    def build_plan(self, goal, proposal: Proposal, proposals: list[Proposal], *,
                   mode, replan_revision: int, now: float, observation_id: str,
                   planning_world: dict,
                   current_plan: Plan | None, last_signature: tuple | None) -> PlanUpdate:
        signature = (proposal.key, mode, goal.goal_id, replan_revision)
        if signature == last_signature:
            return PlanUpdate(current_plan, last_signature, False)
        contract = self.registry.contracts[proposal.skill]
        plan = Plan.create(
            goal, proposal, proposals, contract, now, observation_id,
            steps=self.planner.plan_horizon(proposal, planning_world),
            constraints=self.planner.plan_constraints(proposal),
            replan_triggers=("PREDICTION_ERROR", "QUEST_STATE_CHANGED",
                             "TARGET_IDENTITY_CHANGED", "PATH_BLOCKED",
                             "SENSOR_DEGRADED", "SAFETY_EVENT"),
            candidate_utilities=tuple(
                self.planner.last_scores.get(item.key, {
                    "proposal_id": item.key, "skill": item.skill})
                for item in proposals))
        return PlanUpdate(plan, signature, True)

    def resolve(self, cycle: PlanningCycleResult, *, goal, world,
                planning_world: dict, mode, replan_revision: int, now: float,
                observation_id: str, current_plan: Plan | None,
                last_signature: tuple | None, last_result: dict,
                navigation, failures: dict,
                current_recovery_for: str | None) -> PlanningResolution:
        """Apply the remaining proposal adapters without execution authority."""
        if self.navigation_adapter is None or self.recovery_planner is None:
            raise RuntimeError("planning resolution dependencies are not configured")
        proposals = list(cycle.proposals)
        proposal = self.navigation_adapter.adapt(
            cycle.proposal, proposals, world, now)
        recovery = self.recovery_planner.apply(
            proposal, world=world, goal=goal, last_result=last_result,
            navigation=navigation, registry=self.registry,
            autonomy=self.autonomy, failures=failures, now=now,
            current_recovery_for=current_recovery_for)
        proposal = recovery.proposal
        plan_update = self.build_plan(
            goal, proposal, proposals, mode=mode,
            replan_revision=replan_revision, now=now,
            observation_id=observation_id, planning_world=planning_world,
            current_plan=current_plan, last_signature=last_signature)
        return PlanningResolution(
            proposal, tuple(proposals), recovery.recovery_for, plan_update)

    @staticmethod
    def _local_interaction_pending(proposals: list[Proposal]) -> bool:
        """Loot of an own kill or a quest object right here.

        Live 2026-10-07 12:06: when combat ended, the suspended MOVE was
        preferred over every ranked proposal; the agent walked off before
        looting, and the later LOOT had no corpse position (Retail exports a
        world position only for the selected target): ``corpse_not_found``
        and back again.  The resume waits (its window is 180 s after combat).
        """
        return any(item.skill in {"LOOT", "OBJECT_USE"}
                   or (item.skill == "VISUAL_APPROACH"
                       and item.parameters.get("purpose") == "LOOT")
                   for item in proposals)

    def _inject_supervisor_resume(self, proposals: list[Proposal], world,
                                  now: float) -> Proposal | None:
        resume = self.supervisor.resume_candidate(world.state, now)
        if resume is None:
            return None
        if self._local_interaction_pending(proposals):
            return None
        candidate = Proposal.make(
            resume.intent.skill_type,
            "Megszakított, még mindig érvényes részfeladat kontrollált folytatása",
            {**resume.intent.parameters, "_resume_token": resume.token},
            confidence=1., priority=101)
        if self.registry.available(candidate, world):
            proposals.insert(0, candidate)
            return candidate
        self.supervisor.clear_resume("resume_preconditions_lost")
        return None

    def _inject_recovery_resume(self, proposals: list[Proposal], retained: Proposal | None,
                                ready: bool, world, now: float,
                                events: list[tuple[str, dict]]) -> tuple[Proposal | None, bool, Proposal | None]:
        if not ready or retained is None:
            return retained, ready, None
        parameters = retained.parameters
        state = world.state
        same_map = parameters.get("map_id") is None or parameters.get("map_id") == state.get("map_id")
        target_guid = str(parameters.get("target_guid") or "")
        current_target = state.get("target") or {}
        same_target = not target_guid or str(current_target.get("guid") or "") == target_guid
        ui_open = any(bool((state.get(key) or {}).get("open"))
                      for key in ("quest_ui", "gossip_ui", "vendor_ui"))
        if same_map and same_target and not ui_open and not state.get("is_in_combat"):
            candidate = Proposal.make(
                retained.skill,
                "Igazolt beragadás-helyreállítás után ugyanazon REACH kontrollált folytatása",
                {**parameters, "_resume_after_recovery": True},
                confidence=retained.confidence, priority=max(99., retained.priority),
                evidence=retained.evidence)
            if self.registry.available(candidate, world):
                proposals.insert(0, candidate)
                self.planner.blocked_until.pop(retained.key, None)
                events.append(("RECOVERY_RESUME_OFFERED", {
                    "skill": candidate.skill, "map_id": parameters.get("map_id"),
                    "target_guid": target_guid or None}))
                return None, False, candidate
            events.append(("RECOVERY_RESUME_REJECTED", {"reason": "skill_preconditions_lost"}))
            return None, False, None
        if not same_map or not same_target:
            events.append(("RECOVERY_RESUME_REJECTED", {
                "reason": "map_or_target_preconditions_lost",
                "same_map": same_map, "same_target": same_target}))
            return None, False, None
        return retained, ready, None
