from types import SimpleNamespace

from wowbot.agent.models import Proposal
from wowbot.agent.planning_orchestration import PlanningOrchestrator
from wowbot.runtime import Intent


class Planner:
    def __init__(self, proposals):
        self.proposals = proposals
        self.blocked_until = {}

    def candidates(self, goal, planning_world, now): return list(self.proposals)
    def plan_horizon(self, proposal, planning_world): return ({"skill": proposal.skill},)
    def plan_constraints(self, proposal): return ("single_active_skill",)
    last_scores = {}


class Goals:
    def filter(self, proposals, contracts, now): return proposals


class Registry:
    def __init__(self, available=True):
        self.is_available = available
        self.contracts = {name: SimpleNamespace(
            expected="expected", success_condition="verified", recovery="replan")
            for name in ("WAIT", "MOVE", "INSPECT")}
    def available(self, proposal, world): return self.is_available


class Supervisor:
    def __init__(self, resume=None): self.resume, self.cleared = resume, None
    def resume_candidate(self, state, now): return self.resume
    def clear_resume(self, reason): self.cleared = reason


class Autonomy:
    def choose(self, proposals, proposal, goal, world, now): return proposal


class World:
    def __init__(self, state=None):
        self.state = state or {}
        self.latest = SimpleNamespace(observation_id="obs:latest")
    def player_position(self): return (.1, .1)


class NavigationAdapter:
    def __init__(self): self.calls = []
    def adapt(self, proposal, proposals, world, now):
        self.calls.append((proposal, tuple(proposals), world, now))
        return Proposal.make("MOVE", "navigation adapted", {"x": .2, "y": .2})


class RecoveryPlanner:
    def __init__(self): self.calls = []
    def apply(self, proposal, **kwargs):
        self.calls.append((proposal, kwargs))
        return SimpleNamespace(
            proposal=Proposal.make("WAIT", "bounded recovery"),
            recovery_for="action:failed")


def orchestrator(proposals=(), *, supervisor=None, available=True):
    planner = Planner(proposals)
    value = PlanningOrchestrator(
        planner, Goals(), Registry(available), supervisor or Supervisor(), Autonomy())
    return value, planner


def test_empty_candidate_set_becomes_wait_without_executing_anything():
    value, _ = orchestrator()
    result = value.choose(object(), World(), {}, 1., recovery_resume=None,
                          recovery_resume_ready=False)
    assert result.proposal.skill == "WAIT"


def test_valid_supervisor_resume_is_preferred_but_not_consumed_here():
    resume = SimpleNamespace(
        intent=Intent("MOVE", {"x": .5, "y": .5}), token="resume:1")
    value, _ = orchestrator([Proposal.make("WAIT", "other")],
                            supervisor=Supervisor(resume))
    result = value.choose(object(), World(), {}, 1., recovery_resume=None,
                          recovery_resume_ready=False)
    assert result.proposal.skill == "MOVE"
    assert result.proposal.parameters["_resume_token"] == "resume:1"


def test_invalid_supervisor_resume_is_cleared():
    supervisor = Supervisor(SimpleNamespace(
        intent=Intent("MOVE", {"x": .5, "y": .5}), token="resume:1"))
    value, _ = orchestrator([Proposal.make("WAIT", "other")],
                            supervisor=supervisor, available=False)
    value.choose(object(), World(), {}, 1., recovery_resume=None,
                 recovery_resume_ready=False)
    assert supervisor.cleared == "resume_preconditions_lost"


def test_recovery_resume_requires_same_map_and_target():
    retained = Proposal.make("MOVE", "resume", {"map_id": 1, "target_guid": "npc"})
    value, _ = orchestrator([Proposal.make("WAIT", "other")])
    result = value.choose(
        object(), World({"map_id": 2, "target": {"guid": "other"}}), {}, 1.,
        recovery_resume=retained, recovery_resume_ready=True)
    assert result.recovery_resume is None
    assert result.recovery_resume_ready is False
    assert result.events[0][0] == "RECOVERY_RESUME_REJECTED"


def test_valid_recovery_resume_is_offered_once_and_unblocks_proposal():
    retained = Proposal.make("MOVE", "resume", {"map_id": 1})
    value, planner = orchestrator([Proposal.make("WAIT", "other")])
    planner.blocked_until[retained.key] = 99.
    result = value.choose(
        object(), World({"map_id": 1}), {}, 1.,
        recovery_resume=retained, recovery_resume_ready=True)
    assert result.proposal.skill == "MOVE"
    assert result.proposal.parameters["_resume_after_recovery"] is True
    assert retained.key not in planner.blocked_until
    assert result.events[0][0] == "RECOVERY_RESUME_OFFERED"


def test_plan_revision_is_created_only_when_signature_changes():
    value, _ = orchestrator([Proposal.make("WAIT", "observe")])
    proposal = Proposal.make("WAIT", "observe")
    goal = SimpleNamespace(goal_id="goal:1")
    first = value.build_plan(
        goal, proposal, [proposal], mode="FULL_AI", replan_revision=1,
        now=1., observation_id="obs:1", planning_world={},
        current_plan=None, last_signature=None)
    assert first.changed is True
    assert first.plan.skill == "WAIT"
    second = value.build_plan(
        goal, proposal, [proposal], mode="FULL_AI", replan_revision=1,
        now=2., observation_id="obs:2", planning_world={},
        current_plan=first.plan, last_signature=first.signature)
    assert second.changed is False
    assert second.plan is first.plan


def test_resolve_composes_navigation_recovery_and_plan_without_dispatch():
    adapter, recovery = NavigationAdapter(), RecoveryPlanner()
    value, _ = orchestrator([Proposal.make("WAIT", "observe")])
    value.navigation_adapter, value.recovery_planner = adapter, recovery
    goal = SimpleNamespace(goal_id="goal:1")
    cycle = value.choose(
        goal, World(), {}, 1., recovery_resume=None,
        recovery_resume_ready=False)

    result = value.resolve(
        cycle, goal=goal, world=World(), planning_world={}, mode="FULL_AI",
        replan_revision=1, now=1., observation_id="obs:1",
        current_plan=None, last_signature=None, last_result={},
        navigation=object(), failures={}, current_recovery_for=None)

    assert adapter.calls and recovery.calls
    assert recovery.calls[0][0].skill == "MOVE"
    assert result.proposal.skill == "WAIT"
    assert result.recovery_for == "action:failed"
    assert result.plan_update.changed is True
    assert result.plan_update.plan.skill == "WAIT"
