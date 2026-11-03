"""Live 20:31-20:36: mount-ready facts lagged the mount verification.

Ground MOVE kept running after can_glide arrived; it must yield once to the
same canonical navigation owner without inventing arrival or another task.
"""
from types import SimpleNamespace

import pytest

from wowbot.agent.models import Goal, Outcome, Proposal
from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.runtime import SkillResult, SkillStatus
from test_active_skill_supervision import context, supervisor
from test_skyriding_fast_control_20261025 import skyriding_world

GOAL = Goal.parse('Questelj', 1.)


def mount_result(action='mount:1', **extra):
    return {'skill': 'MOUNT', 'action_id': action, 'outcome': 'SUCCESS',
            'purpose': 'MOVEMENT_FLIGHT', **extra}


def test_explicit_flight_mount_waits_briefly_for_capability_then_flies_same_destination():
    policy = TravelModePolicy()
    world, move = skyriding_world(mounted=True)
    world.runtime_context = {'last_result': mount_result()}
    world.state['flight']['can_glide'] = False
    waiting = policy.apply([move], GOAL, world, 100.)
    assert [p.skill for p in waiting] == ['WAIT']
    assert waiting[0].parameters['wait_until'] == 102.
    assert policy.snapshot()['reason'] == 'mount_flight_telemetry_settling'
    policy.apply([move], GOAL, world, 101.)
    assert policy.flight_mount_wait_until == 102.  # unchanged result never extends the wait
    world.state['flight']['can_glide'] = True
    (flight,) = policy.apply([move], GOAL, world, 101.1)
    assert flight.parameters['flight_style'] == 'SKYRIDING'
    assert {k: flight.parameters[k] for k in move.parameters} == move.parameters


def test_missing_flight_capability_wait_expires_and_a_ground_mount_keeps_ground_travel():
    policy = TravelModePolicy()
    world, move = skyriding_world(mounted=True)
    world.runtime_context = {'last_result': mount_result()}
    world.state['flight']['can_glide'] = False
    policy.apply([move], GOAL, world, 100.)
    (ground,) = policy.apply([move], GOAL, world, 102.1)
    assert ground == move and not ground.parameters.get('flight')
    assert not policy.flight_now(move, world, 103.)


def test_running_ground_route_upgrades_when_mount_facts_arrive_and_never_cancels_flight_again():
    policy = TravelModePolicy()
    world, move = skyriding_world(mounted=True)
    world.state['flight']['can_glide'] = False
    assert not policy.flight_now(move, world, 100.)
    world.state['flight']['can_glide'] = True
    assert policy.flight_now(move, world, 101.)
    (flight,) = policy.apply([move], GOAL, world, 101.)
    assert not policy.flight_now(flight, world, 101.1)
    world.state['is_mounted'] = False
    assert not policy.flight_now(move, world, 101.2)


@pytest.mark.parametrize('bad', ['indoors', 'combat', 'vehicle', 'unknown_zone', 'short_route'])
def test_fresh_mount_facts_never_bypass_other_flight_conditions(bad):
    world, move = skyriding_world(mounted=True, yards=40. if bad == 'short_route' else 600.)
    if bad == 'indoors': world.state['movement']['indoors'] = True
    if bad == 'combat': world.state['is_in_combat'] = True
    if bad == 'vehicle': world.state['in_vehicle'] = True
    if bad == 'unknown_zone': world.state['flight'].pop('advanced_flyable_area')
    assert not TravelModePolicy().flight_now(move, world, 100.)


def test_recent_dismount_and_failed_mount_do_not_prevent_flight_after_a_successful_remount():
    policy = TravelModePolicy()
    world, move = skyriding_world(mounted=True)
    policy.dismounted_at = policy.failed_at = 99.
    policy.failed_point = (0., 0.)
    assert policy.flight_now(move, world, 100.)
    world.state['is_mounted'] = False
    assert policy._blocked(world.state, 100.) == 'recently_dismounted'


@pytest.mark.parametrize('reason,expected', [('skyriding_not_mounted', True), ('skyriding_takeoff_failed', False)])
def test_mount_transition_is_not_a_sixty_second_flight_failure_but_a_real_takeoff_failure_is(reason, expected):
    policy = TravelModePolicy()
    world, move = skyriding_world(mounted=True)
    world.runtime_context = {'last_result': {'skill': 'MOVE', 'action_id': 'move:1',
                                            'outcome': 'FAILURE', 'reason': reason}}
    policy.observe(world, 100.)
    assert policy.flight_now(move, world, 101.) is expected


def test_urgent_loot_is_not_delayed_by_mount_capability_settling():
    policy = TravelModePolicy()
    world, move = skyriding_world(mounted=True)
    world.runtime_context = {'last_result': mount_result()}
    world.state['flight']['can_glide'] = False
    loot = Proposal.make('LOOT', 'own corpse', {}, priority=120.)
    proposals = policy.apply([move, loot], GOAL, world, 100.)
    assert not any(p.parameters.get('waiting_for') == ['MOUNT_FLIGHT_CAPABILITY'] for p in proposals)


def test_mode_change_cancels_ground_movement_without_claiming_arrival():
    value = supervisor(SkillResult(SkillStatus.RUNNING))
    attempt, active, world = context('MOVE')
    world.latest = SimpleNamespace(source='ADDON', payload={})
    step = value.step(attempt, active, world, world_observation_id='obs:1',
        visual_observation_id='visual:1', now=1.,
        reference_reach_interrupt={'kind': 'FLIGHT_MODE_AVAILABLE', 'reason': 'flight_mode_available'})
    assert step.terminal_outcome is Outcome.CANCELLED
    assert step.reason == 'flight_mode_available' and step.stop_movement
    assert step.commands == ()


def test_medium_owner_notices_flight_readiness_even_when_the_fast_lane_drives_move(monkeypatch):
    from test_agent_core import agent, state
    from test_active_pointer_tracking import attempt
    from wowbot.agent.models import Observation
    bot, executor = agent('Menj oda', {'destination': {'map_id': 1609, 'x': .5, 'y': .1}})
    world, move = skyriding_world(mounted=True)
    world.state['flight']['can_glide'] = False
    bot.world.ingest(Observation.create(state(10., **world.state), 10.))
    bot.pending = attempt('MOVE', move.parameters)
    monkeypatch.setattr(bot.parallel_control, 'drives', lambda *args: True)
    seen = []
    monkeypatch.setattr(bot, '_apply_active_supervision', lambda step, now: seen.append(step) or True)
    world.state['flight']['can_glide'] = True
    bot.tick(state(10.1, **world.state), 10.1)
    assert len(seen) == 1
    assert seen[0].reason == 'flight_mode_available'
    assert seen[0].terminal_outcome is Outcome.CANCELLED
    assert seen[0].stop_movement and not seen[0].commands
