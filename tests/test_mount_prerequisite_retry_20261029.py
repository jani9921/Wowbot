"""16:24 By Broken Road: successful remount left flight MOVE blocked 120 s."""
from types import SimpleNamespace

import pytest

from wowbot.agent.decision_fingerprint import DecisionFingerprintGuard
from wowbot.agent.goal_manager import GoalManager
from wowbot.agent.models import Goal, Outcome, Proposal
from wowbot.agent.proposal_ranking import ProposalRanker
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.runtime.policies import RetryPolicy
from test_outcome_bookkeeping import apply, attempt
from test_travel_mode_20261020 import CAPABLE, favorite_mount


def scene(mounted=False):
    return {'session_id': 'test:mount-gate', 'map_id': 2023, 'is_mounted': mounted,
        'orientation': 0., 'position': {'x': .5, 'y': .5},
        'is_in_combat': False, 'movement': {'indoors': False, 'flying': False},
        'flight': {'advanced_flyable_area': True, 'can_glide': mounted},
        'mount_capability': CAPABLE, 'actionbar': [favorite_mount()],
        'player_world_position': {'coordinate_space': 'WORLD_YARDS', 'instance_id': 2444,
                                  'x': 0., 'y': 0.}}


def test_mount_must_be_verified_before_even_a_high_scoring_flight_move_can_win():
    current = scene()
    world = SimpleNamespace(state=current, distance=lambda p: 100., runtime_context={})
    move = Proposal.make('MOVE', 'next required arrival', {'x': 500., 'y': 0.,
        'coordinate_space': 'WORLD_YARDS', 'instance_id': 2444, 'require_navmesh': True,
        'purpose': 'LOCATE_QUEST_OBJECTIVE_REGION', 'quest_id': 65940}, priority=1000.)
    goal = Goal.parse('Questelj', 1.)
    candidates = TravelModePolicy().apply([move], goal, world, 100.)
    registry = SkillRegistry()
    assert {p.skill for p in candidates} == {'MOVE', 'MOUNT'}
    assert not registry.available(next(p for p in candidates if p.skill == 'MOVE'), world)
    ranked = ProposalRanker.rank(candidates, goal=goal, world=world, now=100.,
        registry=registry, memory=None, blocked_until={}, recent={}, evidence=())
    assert ranked.proposals[0].skill == 'MOUNT'
    current['is_mounted'] = True
    current['flight']['can_glide'] = True
    assert registry.available(next(p for p in candidates if p.skill == 'MOVE'), world)


@pytest.mark.parametrize('reason', ['skyriding_not_mounted', 'flight_not_mounted'])
def test_a_mount_precondition_failure_does_not_blacklist_the_destination(reason):
    value = attempt('MOVE', {'flight': True, 'quest_id': 65940})
    _, _, planner, _, _, _ = apply(value, Outcome.FAILURE, reason, now=100.)
    assert planner.blocked_until[value.proposal.key] <= 100.5


def test_verified_mounting_changes_decision_evidence_without_a_manual_move():
    guard = DecisionFingerprintGuard()
    goal = Goal.parse('Questelj', 1.)
    move = Proposal.make('MOVE', 'flight', {'flight': True, 'quest_id': 65940})
    before = scene()
    guard.record_nonretryable(move, goal, before, reason='skyriding_not_mounted', now=100.)
    assert not guard.permits(move, goal, {**before, 'frame_id': 'new-only'})
    assert guard.permits(move, goal, scene(mounted=True))


@pytest.mark.parametrize('configured', [20., 120., 999.])
def test_central_and_custom_retry_backoff_never_exceeds_twenty_seconds(configured):
    policy = RetryPolicy(max_backoff_seconds=configured)
    assert policy.max_backoff_seconds == 20.
    assert policy.backoff(99, None) == 20.
    assert RetryPolicy(max_backoff_seconds=3.).backoff(99, None) == 3.


def test_external_failure_decision_cannot_reintroduce_a_long_action_ban():
    value = attempt('MOVE', {'quest_id': 65940})
    decision = SimpleNamespace(retry_allowed=True, backoff_seconds=120.)
    _, _, planner, _, _, _ = apply(value, Outcome.FAILURE, 'supported_stuck',
                                    now=100., failure_decision=decision)
    assert planner.blocked_until[value.proposal.key] == 120.


@pytest.mark.parametrize('escalate', [False, True])
def test_goal_task_suppression_is_also_bounded_and_reopens(escalate):
    goals = GoalManager()
    goals.set_goal(Goal.parse('Questelj', 1.), 1.)
    move = Proposal.make('MOVE', 'route', {'quest_id': 65940})
    registry = SkillRegistry()
    goals.filter([move], registry.contracts, 100.)
    for now in (101., 102., 103.):
        decision = (SimpleNamespace(escalation_stage='GOAL_ALTERNATIVE', recovery_action='REPLAN')
                    if escalate else None)
        goals.outcome(move, False, 'supported_stuck', now, failure_decision=decision)
    task = next(iter(goals.tasks.values()))
    assert task.blocked_until <= 123.
    assert goals.filter([move], registry.contracts, 122.) == []
    assert goals.filter([move], registry.contracts, 124.) == [move]
