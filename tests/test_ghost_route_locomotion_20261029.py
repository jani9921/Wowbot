"""Ghost recovery uses the shared MMAP / Steady Flight MOVE lifecycle.

The 15:49 recording repeatedly cancelled a plain corpse MOVE with
flight_mode_available: death planning bypassed TravelModePolicy, while its
mid-route query incorrectly offered Skyriding for an airborne ghost.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.death_recovery_planning import DeathRecoveryPolicy
from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.flight_capability import ghost_steady_flight_available
from wowbot.agent.flight_control import FlightControl
from wowbot.agent.models import Goal, Mode, Proposal
from wowbot.agent.navigation_planning import NavigationProposalAdapter
from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.navigation.mmap_navmesh import NavMeshPath
from wowbot.navigation.service import NavigationService
from test_agent_core import state
from test_flight_plan_20261025 import Geometry


class RecoveryGeometry(Geometry):
    def find_path(self, instance, start, end):
        # The supported ground route bends around an obstruction.
        return NavMeshPath(({**start, 'z': 10.}, {'x': 150., 'y': 30., 'z': 10.},
                            {**end, 'z': 10.}), 8, 1, 420.)


def ghost(at=100., *, x=0., z=10., mounted=True, packet_airborne=False):
    value = state(at, map_id=2023, is_ghost=True, is_mounted=mounted,
        movement={'flying': False, 'falling': False, 'moving': False, 'indoors': False},
        flight={'flyable_area': True, 'can_glide': False, 'gliding': False},
        player_world_position={'x': x, 'y': 0., 'z': z, 'z_known': True,
            'z_observed': True, 'z_source': 'PACKET_CLIENT_MOVEMENT', 'sample_time': at,
            'instance_id': 2444, 'coordinate_space': 'WORLD_YARDS'},
        death_recovery={'popup': '', 'recovery_delay': 0, 'corpse': {
            'coordinate_space': 'WORLD_YARDS', 'instance_id': 2444,
            'ui_map_id': 2023, 'x': 400., 'y': 0., 'z_known': False}})
    if packet_airborne:
        value['packet_flight'] = {'sample_time': at, 'adv_flying': True}
    return value


def move_for(current, now=100.):
    proposals = DeathRecoveryPolicy().propose(current, now)
    policy = TravelModePolicy()
    return policy.apply(proposals, Goal.parse('Questelj', 1.), SimpleNamespace(state=current), now)[0]


def test_a_mounted_ghost_selects_steady_without_a_journal_mount_or_skyriding():
    current = ghost(packet_airborne=True)
    current['skyriding_seen'] = True  # previous living travel is irrelevant
    before = deepcopy(current)
    move = move_for(current)
    assert move.parameters['require_navmesh'] is True
    assert move.parameters['flight'] is True and move.parameters['flight_style'] == 'STEADY'
    assert current == before
    policy = TravelModePolicy()
    assert not policy.flight_now(move, SimpleNamespace(state=current), 100.)
    assert policy._skyriding_travel([move], current, 100.) is None


@pytest.mark.parametrize('change', [
    {'is_ghost': False}, {'is_mounted': False}, {'loading': True}, {'in_vehicle': True},
    {'on_taxi': True}, {'is_in_combat': True}, {'movement': {'indoors': True}},
    {'flight': {}}, {'flight': {'flyable_area': False, 'can_glide': False}},
    {'flight': {'flyable_area': True, 'can_glide': True}},
])
def test_ghost_flight_requires_current_supported_context(change):
    current = ghost()
    current.update(change)
    assert not ghost_steady_flight_available(current)


def test_wrong_corpse_or_arbitrary_move_cannot_obtain_ghost_flight_permission():
    current = ghost()
    move = Proposal.make('MOVE', 'unrelated', {'coordinate_space': 'WORLD_YARDS',
        'instance_id': 2444, 'x': 600., 'y': 0., 'purpose': 'CORPSE_RUN'})
    result = TravelModePolicy().apply([move], Goal.parse('Questelj', 1.),
                                     SimpleNamespace(state=current), 100.)
    assert not result[0].parameters.get('flight')
    guarded = NavigationProposalAdapter._guard_physical_move(
        Proposal.make('MOVE', 'old direct fallback', {**move.parameters, 'require_navmesh': False}),
        SimpleNamespace(state=current))
    assert guarded.parameters['require_navmesh'] is True


def test_ground_ghost_uses_real_detour_anchors_and_never_requests_a_mount():
    current = ghost(mounted=False)
    move = move_for(current)
    assert not move.parameters.get('flight') and move.parameters['require_navmesh'] is True
    nav = NavigationService(navmesh=RecoveryGeometry())
    nav.start_skill_request('MOVE', move.parameters, current, 'corpse-ground', 100.)
    assert nav._active_route.regions[0]['route_source'] == 'TRINITYCORE_MMAP'
    assert nav._active_route.anchors[1]['y'] == 30.
    assert nav._movement.flight is None


def test_common_flight_uses_terrain_profile_and_only_steady_controls():
    current = ghost()
    move = move_for(current)
    nav = NavigationService(navmesh=RecoveryGeometry())
    nav.start_skill_request('MOVE', move.parameters, current, 'one-owner', 100.)
    assert nav._active_route.regions[0]['route_source'] == 'FLIGHT_PLAN'
    assert isinstance(nav._movement.flight, FlightControl)
    assert nav._movement.flight.plan.ground_ahead(70.) == 50.  # ridge
    assert nav.flight_controls_allowed(current)
    assert [c.binding for c in nav.command(current, 'takeoff', 100.)] == ['JUMP']
    air = ghost(100.5, x=60., z=22., packet_airborne=True)
    nav.observe(air, 'air', 100.5)
    commands = nav.command(air, 'air', 100.5)
    assert any(c.binding == 'JUMP' for c in commands)  # climb above the ridge
    assert nav._active_request.correlation_id == 'one-owner'
    assert all(c.binding not in {'PITCHUP', 'PITCHDOWN', 'ACTIONBUTTON1'} for c in commands)
    unrelated = deepcopy(air)
    unrelated['death_recovery']['corpse']['x'] = 700.
    assert not nav.flight_controls_allowed(unrelated)
    assert nav.command(unrelated, 'changed-corpse', 100.6) == ()


def test_full_recording_agent_keeps_one_move_when_packet_airborne_becomes_available():
    recorder = RecordingExecutor()
    bot = AutonomousAgent(recorder, navmesh=RecoveryGeometry())
    bot.set_goal('Questelj', 1.)
    bot.set_mode(Mode.FULL_AI)
    bot.tick(ghost(), 100.)
    assert bot.pending and bot.pending.proposal.parameters['flight_style'] == 'STEADY'
    action_id = bot.pending.action_id
    for t in (100.2, 100.4, 100.6, 100.8):
        bot.tick(ghost(t, x=(t-100.)*10., z=22., packet_airborne=True), t)
        assert bot.pending and bot.pending.action_id == action_id
        assert bot.last_result.get('reason') != 'flight_mode_available'
    assert recorder.commands and any(c.binding == 'JUMP' for c in recorder.commands)


def test_above_corpse_xy_does_not_arrive_or_transition_to_ground_on_false_addon_flag():
    current = ghost(x=400., z=90., packet_airborne=True)
    move = move_for(current)
    nav = NavigationService(navmesh=RecoveryGeometry())
    nav.start_skill_request('MOVE', move.parameters, current, 'land', 100.)
    assert isinstance(nav._movement.flight, FlightControl)
    assessment = nav.observe(current, 'above', 100.)
    assert not assessment.terminal and not nav.needs_ground_approach(current, 100.)
    assert any(c.binding == 'SITORSTAND' for c in nav.command(current, 'above', 100.))
    stale = ghost(102., x=400., z=90.)
    assert not nav.needs_ground_approach(stale, 102.)
    # A fresh own height on the landing surface can complete the air leg.
    landed = ghost(103., x=400., z=10.)
    nav._movement.flight.observe_height(landed, 103.)
    assert nav.needs_ground_approach(landed, 103.)
    landed['death_recovery'].update(popup='RECOVER_CORPSE', enabled=True, x=.5, y=.6)
    assert move_for(landed, 103.).skill == 'DEATH_RECOVERY'


def test_unknown_geometry_cannot_claim_arrival_above_the_corpse():
    current = ghost(x=400., z=90., packet_airborne=True)
    nav = NavigationService()
    nav.start_skill_request('MOVE', move_for(current).parameters, current, 'missing', 100.)
    assert nav.command(current, 'missing', 100.) == ()
    assert nav._route_failure_reason == 'flight_plan_no_world_geometry'


def test_failed_takeoff_is_bounded_by_the_existing_flight_controller():
    current = ghost()
    nav = NavigationService(navmesh=RecoveryGeometry())
    nav.start_skill_request('MOVE', move_for(current).parameters, current, 'takeoff', 100.)
    flight = nav._movement.flight
    for t in (100., 103., 106.):
        flight.assess(current, 400., 6., t)
        flight.commands(current, 400., 0., 6., t)
    assert flight.assess(current, 400., 6., 109.) == ('FAILED', 'flight_takeoff_failed')
