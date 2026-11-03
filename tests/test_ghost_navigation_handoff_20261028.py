"""Live 22:51-23:09: mounted ghost, flying=False, corpse 530 yd away.

Policy lost the model's oracles in a snapshot; the physical MOVE adapter
then replaced require_navmesh=False with True. Fourteen missing-route
failures suppressed the same subtask instead of starting corpse recovery.
"""
from copy import deepcopy
from types import SimpleNamespace
import math

import pytest

from wowbot.query_ports import NavigationQueryPorts

from wowbot.agent.death_recovery_planning import DeathRecoveryPolicy, corpse_run_matches
from wowbot.agent.goal_manager import GoalManager
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.navigation_planning import NavigationProposalAdapter
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from test_agent_core import agent, state


CORPSE = {'coordinate_space': 'NORMALIZED_MAP', 'map_id': 2023,
          'world_position': {'coordinate_space': 'WORLD_YARDS', 'instance_id': 2444,
                             'ui_map_id': 2023, 'x': -361.52478, 'y': 900.43799, 'z_known': False}}


def ghost(t=100., *, near=False, mounted=True):
    x, y = (-340., 900.) if near else (-549.63269, 404.43475)
    return state(t, map_id=2023, is_dead=False, is_ghost=True, is_mounted=mounted,
        movement={'flying': False, 'falling': False, 'moving': False, 'indoors': False},
        flight={'flyable_area': True, 'can_glide': False, 'gliding': False},
        orientation=math.atan2(900.43799-y, -361.52478-x),
        player_world_position={'coordinate_space': 'WORLD_YARDS', 'instance_id': 2444,
                               'ui_map_id': 2023, 'x': x, 'y': y, 'z': 525.3714,
                               'z_known': True, 'z_observed': True},
        death_recovery={'corpse': deepcopy(CORPSE), 'popup': '', 'recovery_delay': 0})


def test_mounted_ghost_far_away_keeps_common_routing_when_flying_flag_is_false():
    current = ghost()
    (move,) = DeathRecoveryPolicy().propose(current, 100., walk_cost=lambda *a: 600.)
    assert move.skill == 'MOVE' and move.parameters['require_navmesh'] is True
    assert corpse_run_matches(current, move.parameters)
    guarded = NavigationProposalAdapter._guard_physical_move(move, SimpleNamespace(state=current))
    assert guarded.parameters['require_navmesh'] is True
    assert guarded.parameters['purpose'] == 'CORPSE_RUN'


def test_a_ground_safe_spot_is_not_planned_from_a_far_ghost_mount():
    def hostiles(*args):
        pytest.fail('A far ghost mount first approaches the corpse, then plans the local safe spot')
    (move,) = DeathRecoveryPolicy().propose(ghost(), 100., walk_cost=lambda *a: 600., hostile_units=hostiles)
    assert move.parameters['require_navmesh'] is True
    assert not move.parameters.get('safe_resurrection_spot')


def test_planner_owns_navigation_queries_and_selects_shared_steady_flight_for_a_snapshot():
    current = ghost(near=True)
    world = WorldModel()
    world.ingest(Observation.create(current, 100.))
    calls = []
    queries = NavigationQueryPorts(
        hostile_units=lambda *a: calls.append('hostiles') or [{'x': -361., 'y': 900.}])
    planner = Planner(SkillRegistry(), travel_cost=lambda *a: calls.append('path'),
                      navigation_queries=queries)
    snapshot = world.planning_snapshot(100.)
    assert 'walk_cost' not in snapshot.__dict__
    assert 'hostile_units' not in world.__dict__
    (proposal,) = planner.candidates(Goal.parse('Questelj', 1.), snapshot, 100.)
    assert set(calls) == {'path', 'hostiles'}
    assert proposal.skill == 'MOVE' and proposal.parameters['flight_style'] == 'STEADY'


@pytest.mark.parametrize('bad', ['alive', 'unreleased_dead', 'unknown_corpse', 'other_destination',
    'other_purpose', 'outside_safe_spot', 'other_corpse_world'])
def test_the_exception_cannot_turn_a_living_or_unrelated_move_into_unchecked_navigation(bad):
    current = ghost()
    (proposal,) = DeathRecoveryPolicy().propose(current, 100.)
    parameters = dict(proposal.parameters)
    if bad == 'alive': current['is_ghost'] = False
    if bad == 'unreleased_dead': current.update(is_ghost=False, is_dead=True)
    if bad == 'unknown_corpse': current['death_recovery']['corpse'] = None
    if bad == 'other_destination': parameters['x'] += 10
    if bad == 'other_purpose': parameters['purpose'] = 'LOCATE_TURN_IN_REGION'
    if bad == 'outside_safe_spot': parameters.update(x=parameters['x']+40., safe_resurrection_spot=True)
    if bad == 'other_corpse_world': current['death_recovery']['corpse']['world_position']['instance_id'] = 2175
    assert not corpse_run_matches(current, parameters)
    move = Proposal.make('MOVE', 'guard check', parameters)
    guarded = NavigationProposalAdapter._guard_physical_move(move, SimpleNamespace(state=current))
    assert guarded.parameters['require_navmesh'] is True


@pytest.mark.parametrize('bad', ['wrong_instance', 'normalized_pixels', 'missing_instance'])
def test_ghost_fallback_still_requires_a_same_instance_world_destination(bad):
    current = ghost()
    (proposal,) = DeathRecoveryPolicy().propose(current, 100.)
    parameters = dict(proposal.parameters)
    if bad == 'wrong_instance': parameters['instance_id'] = 2175
    if bad == 'normalized_pixels': parameters.update(coordinate_space='NORMALIZED_MAP', x=.5, y=.5)
    if bad == 'missing_instance': parameters.pop('instance_id')
    assert NavigationProposalAdapter._guard_physical_move(
        Proposal.make('MOVE', 'bad ghost target', parameters), SimpleNamespace(state=current)) is None


def test_an_old_failed_shortcut_does_not_suppress_the_common_ghost_route():
    current = ghost()
    (move,) = DeathRecoveryPolicy().propose(current, 100.)
    old = Proposal.make('MOVE', 'old shortcut', {**move.parameters, 'require_navmesh': False})
    registry, goals = SkillRegistry(), GoalManager()
    goals.set_goal(Goal.parse('Questelj', 1.), 1.)
    goals.filter([old], registry.contracts, 100.)
    for at in (101., 102., 103.): goals.outcome(old, False, 'required_navmesh_route_unavailable', at)
    assert goals.filter([old], registry.contracts, 104.) == []
    assert goals.filter([move], registry.contracts, 104.) == [move]
    # The new method retains its own finite failure budget; no global reset.
    for at in (105., 106., 107.): goals.outcome(move, False, 'supported_stuck', at)
    assert goals.filter([move], registry.contracts, 108.) == []


def test_recording_agent_does_not_walk_straight_through_missing_geometry():
    bot, executor = agent('Questelj')
    result = bot.tick(ghost(), 100.)
    assert result['mode'] == 'FULL_AI'
    assert result['decision']['skill'] == 'MOVE'
    assert not any(c.binding == 'MOVEFORWARD' for c in executor.commands)


def test_near_ghost_requests_a_shared_flight_plan_instead_of_unplanned_descents():
    bot, executor = agent('Questelj')
    result = bot.tick(ghost(near=True), 100.)
    assert result['mode'] == 'FULL_AI'
    assert result['decision']['skill'] == 'MOVE'
    assert not any(c.binding == 'SITORSTAND' for c in executor.commands)


@pytest.mark.parametrize('skill', ['MOVE', 'RECOVER'])
def test_a_corpse_run_stops_without_claiming_arrival_when_the_player_is_no_longer_a_ghost(skill):
    from test_active_skill_supervision import supervisor, context
    from wowbot.agent.models import Outcome
    from wowbot.runtime import SkillResult, SkillStatus
    value = supervisor(SkillResult(SkillStatus.RUNNING))
    attempt, active, world = context(skill)
    attempt.proposal = Proposal.make(skill, 'corpse recovery', {'purpose': 'CORPSE_RUN'})
    world.state = {'is_dead': False, 'is_ghost': False}
    step = value.step(attempt, active, world, world_observation_id='resurrected',
                      visual_observation_id='unused', now=101.)
    assert step.terminal_outcome is Outcome.CANCELLED
    assert step.reason == 'corpse_run_no_longer_ghost' and step.stop_movement
    assert not step.commands


def test_flat_arrival_over_a_corpse_with_unknown_height_requests_landing_until_the_real_popup():
    current = ghost()
    current['player_world_position'].update(x=-361.52478, y=900.43799)
    policy = DeathRecoveryPolicy()
    (step,) = policy.propose(current, 100.)
    assert step.skill == 'MOVE' and step.parameters['require_navmesh']
    current['death_recovery'].update(popup='RECOVER_CORPSE', enabled=True, x=.5, y=.6)
    (step,) = policy.propose(current, 104.)
    assert step.skill == 'DEATH_RECOVERY' and step.parameters['action'] == 'RECOVER_CORPSE'


@pytest.mark.parametrize('enabled', [True, False])
def test_reclaim_delay_near_the_corpse_is_not_an_instruction_to_descend(enabled):
    current = ghost()
    current['player_world_position'].update(x=-361.52478, y=900.43799)
    current['death_recovery'].update(popup='RECOVER_CORPSE', enabled=enabled,
                                      x=.5, y=.6, recovery_delay=12.)
    assert DeathRecoveryPolicy().propose(current, 100.)[0].skill == 'WAIT'
