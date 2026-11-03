"""The generic MOVE reaches lateral A* and roof exit/entry geometry."""
from copy import deepcopy
import math
from types import SimpleNamespace

import pytest

from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Goal, Proposal
from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.navigation.flight_route import FlightPlan, skyriding_path
from wowbot.navigation.flight_travel import plan_travel_flight
from wowbot.navigation.mmap_navmesh import NavMeshPath
from wowbot.navigation.service import NavigationService


class World:
    def __init__(self, *, roofs=(), wall=False, clipped=False, unknown=False):
        self.roofs, self.wall, self.clipped, self.unknown = roofs, wall, clipped, unknown
        self.last_diagnostics = {}
        self.last_surface_projection = {}

    def supports(self, instance): return instance == 2444
    def terrain_height(self, instance, x, y):
        if self.unknown and 120 < x < 180: return None, False
        return (220. if self.wall and 135 <= x <= 165 and abs(y) < 35 else 0.), False
    def vmap_surfaces_at(self, instance, point):
        return [15.] if any(a <= point['x'] <= b and c <= point['y'] <= d
                            for a, b, c, d in self.roofs) else []
    def project_position(self, instance, point, z_hint=None):
        return {**point, 'z': point.get('z', 0.), 'instance_id': instance,
                'coordinate_space': 'WORLD_YARDS'}
    def walkable_points_near(self, instance, point, radius): return []
    def walkable_heights_at(self, instance, point, radius=2.5): return [0.]
    def find_path(self, instance, start, end):
        if self.clipped:
            end = {**start, 'x': start['x']+.1}
        return NavMeshPath((dict(start), dict(end)), 2, 1,
                           math.hypot(end['x']-start['x'], end['y']-start['y']))
    def close(self): pass


def state(at=100., *, x=0., y=0., z=0., flying=False, mounted=True, indoors=False, sky=False):
    action = {'action': 'ACTIONBUTTON12', 'kind': 'summonmount', 'id': 123,
        'binding_primary': 'F12', 'is_usable': True, 'cooldown_remaining': 0.,
        'mount': {'mount_type_id': 402 if sky else 248, 'mount_collected': True,
                  'mount_usable': True, 'mount_active': mounted, 'mount_steady_flight': not sky}}
    return {'session_id': 'flight-test', 'monotonic_time': at, 'map_id': 2023,
        'orientation': 0., 'is_mounted': mounted, 'is_in_combat': False, 'is_dead': False,
        'in_vehicle': False, 'on_taxi': False,
        'mount_capability': {'known': True, 'has_mount': True, 'riding_known': True,
                            'flying_riding_known': True, 'usable_mount_count': 1},
        'actionbar': [action], 'flight': {'flyable_area': True, 'advanced_flyable_area': True,
                                        'can_glide': sky, 'gliding': False},
        'movement': {'flying': flying, 'falling': False, 'moving': False, 'indoors': indoors},
        'player_world_position': {'x': x, 'y': y, 'z': z, 'z_observed': True, 'z_known': True,
            'z_source': 'PACKET_CLIENT_MOVEMENT', 'sample_time': at, 'instance_id': 2444,
            'coordinate_space': 'WORLD_YARDS'}}


def goal(x=300., **extra):
    return {'x': x, 'y': 0., 'z': 0., 'z_known': True, 'instance_id': 2444,
            'coordinate_space': 'WORLD_YARDS', 'require_navmesh': True,
            'flight': True, 'flight_style': 'STEADY', 'stop_distance': 2., **extra}


def start(geometry, current=None, destination=None):
    nav = NavigationService(navmesh=geometry)
    nav.start_skill_request('MOVE', destination or goal(), current or state(), 'one-action', 100.)
    return nav


def test_generic_global_route_chooses_lateral_air_bends_and_existing_steady_control_follows_them():
    nav = start(World(wall=True))
    plan = nav._movement.flight.plan
    assert plan.waypoints and plan.cruise_z < 100.
    assert any(abs(point['y']) > 35. for point in plan.waypoints)
    assert FlightPlan.from_dict(plan.to_dict()) == plan
    assert nav.snapshot(100.)['global_route']['regions'][0]['flight_planner'] == 'LATERAL_ASTAR'
    assert [c.binding for c in nav.command(state(), 'takeoff', 100.)] == ['JUMP']
    current = state(101., z=plan.cruise_z, flying=True)
    nav.observe(current, 'air', 101.)
    commands = nav.command(current, 'air', 101.)
    assert any(c.binding in {'TURNLEFT', 'TURNRIGHT'} or
               {'TURNLEFT', 'TURNRIGHT'} & set(c.simultaneous) for c in commands)
    # Reaching the final XY without traversing the bends cannot finish the MOVE.
    result = nav.observe(state(102., x=300.), 'shortcut', 102.)
    assert not result.success


@pytest.mark.parametrize('style', ['STEADY', 'SKYRIDING'])
def test_shared_plan_is_consumable_by_both_flight_styles_without_cutting_away_the_bends(style):
    trip = plan_travel_flight(World(wall=True), 2444, state()['player_world_position'], goal(),
                              flight_style=style)
    assert trip.plan is not None and trip.plan.waypoints
    if style == 'SKYRIDING':
        path = skyriding_path(trip.plan)
        positions = {(point['x'], point['y']) for point in path['waypoints']}
        assert all((point['x'], point['y']) in positions for point in trip.plan.waypoints)


def test_roof_exit_stays_grounded_and_cannot_complete_the_original_goal():
    geometry = World(roofs=[(-5., 5., -5., 5.), (295., 305., -5., 5.)])
    nav = start(geometry, state(indoors=True))
    assert nav._departure_active() and nav._movement.flight is None
    assert not nav._movement.destination['route_waypoint_final']
    assert all(c.binding != 'JUMP' for c in nav.command(state(indoors=True), 'exit', 100.))
    point = nav._active_route.anchors[-1]
    root = nav._active_request
    result = nav.observe(state(101., x=point['x'], y=point['y']), 'outside', 101.)
    assert not result.terminal and not result.success
    assert nav._active_request.correlation_id == root.correlation_id
    assert nav._active_request.destination['x'] == 300.
    assert nav._movement.flight is not None and not nav._departure_active()
    assert nav._movement.flight.plan.landing['x'] != 300. or nav._movement.flight.plan.landing['y'] != 0.


def test_actual_touchdown_outside_the_roof_transfers_to_mmap_for_the_original_indoor_goal():
    geometry = World(roofs=[(295., 305., -5., 5.)])
    nav = start(geometry)
    flight = nav._movement.flight
    landing = flight.plan.landing
    nav.observe(state(101., x=100., z=flight.plan.cruise_z, flying=True), 'air', 101.)
    result = nav.observe(state(102., x=landing['x'], y=landing['y']), 'land', 102.)
    assert not result.success and nav._movement.flight is None
    assert nav._active_request.correlation_id == 'one-action'
    assert nav._active_request.destination['x'] == 300.
    assert nav._active_route.regions[0]['route_source'] == 'TRINITYCORE_MMAP'
    result = nav.observe(state(103., x=300., indoors=True), 'goal', 103.)
    assert result.success


def test_clipped_walks_do_not_authorize_takeoff_or_landing_on_the_other_side_of_a_wall():
    trip = plan_travel_flight(World(roofs=[(-5., 5., -5., 5.)], clipped=True),
                              2444, state()['player_world_position'], goal())
    assert trip.plan is None and trip.reason == 'no_take_off_spot'


def test_unknown_ground_never_becomes_a_lateral_shortcut():
    trip = plan_travel_flight(World(unknown=True), 2444, state()['player_world_position'], goal())
    assert trip.plan is None


def test_planning_horizon_continues_same_owned_move_without_descending_or_claiming_arrival():
    nav = start(World(), destination=goal(2500.))
    flight = nav._movement.flight
    assert flight.plan.truncated
    first = flight.plan.landing
    current = state(101., x=first['x'], y=first['y'], z=first['z'], flying=True)
    result = nav.observe(current, 'horizon', 101.)
    assert not result.terminal and result.reason == 'flight_horizon_replanned'
    assert nav._active_request.correlation_id == 'one-action'
    assert nav._active_request.destination['x'] == 2500.
    assert nav._movement.flight.plan.start['x'] == pytest.approx(first['x'])
    assert nav._request_started_at == 100.


def test_agent_travel_policy_requests_a_proven_exit_walk_before_an_indoor_mount():
    geometry = World(roofs=[(-5., 5., -5., 5.)])
    agent = AutonomousAgent(RecordingExecutor(), navmesh=geometry)
    current = state(mounted=False, indoors=True, sky=True)
    agent.world.state = current
    move = Proposal.make('MOVE', 'quest destination', goal(500., flight=False))
    proposals = agent.planner.travel_mode.apply([move], Goal.parse('Questelj', 100.), agent.world, 100.)
    assert len(proposals) == 1 and proposals[0].skill == 'MOVE'
    assert proposals[0].parameters['flight'] is False and proposals[0].parameters['flight_departure']
    assert agent.planner.travel_mode.mount_now(proposals[0], Goal.parse('Questelj', 100.), agent.world, 100.) is False
    exit_point = proposals[0].parameters['flight_departure']['point']
    agent.world.state = state(101., mounted=False, x=exit_point['x'], y=exit_point['y'], sky=True)
    assert agent.planner.travel_mode.mount_now(proposals[0], Goal.parse('Questelj', 100.), agent.world, 101.)
    after = agent.planner.travel_mode.apply([move], Goal.parse('Questelj', 100.), agent.world, 101.)
    assert any(p.skill == 'MOUNT' for p in after)


def test_unproven_or_missing_exit_keeps_the_existing_ground_route_and_no_mount_input():
    current = state(mounted=False, indoors=True, sky=True)
    value = SimpleNamespace(state=current)
    move = Proposal.make('MOVE', 'quest destination', goal(500., flight=False))
    result = TravelModePolicy().apply([move], Goal.parse('Questelj', 100.), value, 100.)
    assert result == [move]


def test_public_outdoor_flag_alone_cannot_skip_a_geometry_proven_roof_exit():
    geometry = World(roofs=[(-5., 5., -5., 5.)])
    agent = AutonomousAgent(RecordingExecutor(), navmesh=geometry)
    agent.world.state = state(mounted=False, indoors=False, sky=True)
    move = Proposal.make('MOVE', 'quest destination', goal(500., flight=False))
    policy = agent.planner.travel_mode
    proposal, = policy.apply([move], Goal.parse('Questelj', 100.), agent.world, 100.)
    assert proposal.parameters['flight_departure']
    assert not policy.mount_now(proposal, Goal.parse('Questelj', 100.), agent.world, 100.)


def test_unflyable_outdoor_context_continues_on_ground_after_exit_without_claiming_goal_arrival():
    geometry = World(roofs=[(-5., 5., -5., 5.)])
    nav = NavigationService(navmesh=geometry)
    initial = state(mounted=False, indoors=True, sky=True)
    departure = nav.flight_departure_walk(goal(500.), initial)
    nav.start_skill_request('MOVE', goal(500., flight=False,
        flight_departure={**departure, 'flight_style': 'SKYRIDING'}), initial, 'same-task', 100.)
    point = departure['point']
    outside = state(101., x=point['x'], y=point['y'], mounted=False, sky=True)
    outside['flight']['advanced_flyable_area'] = False
    result = nav.observe(outside, 'no-fly-zone', 101.)
    assert not result.terminal and nav._movement.flight is None
    assert nav._active_request.correlation_id == 'same-task'
    assert nav._active_route.regions[0]['route_source'] == 'TRINITYCORE_MMAP'
    assert not nav._active_request.destination.get('flight_departure')


def test_flight_planning_runs_at_request_boundaries_and_cancellation_removes_control(monkeypatch):
    import wowbot.navigation.flight_travel as module
    nav = start(World())
    def unexpected(*args, **kwargs):
        raise AssertionError('A* was called in the fast observation/control path')
    monkeypatch.setattr(module, 'plan_travel_flight', unexpected)
    for index in range(20):
        at = 101.+index*.02
        current = state(at, x=10.+index*.1, z=30., flying=True)
        nav.observe(current, f'fast:{index}', at)
        nav.command(current, f'fast:{index}', at)
    nav.cancel_movement()
    assert nav._movement.flight is None
    assert nav.command(state(103., flying=True, z=30.), 'cancelled', 103.) == ()


def test_air_planning_deadline_returns_an_explicit_unavailable_route(monkeypatch):
    import wowbot.navigation.flight_travel as module
    monkeypatch.setattr(module, 'PLAN_SECONDS', -1.)
    result = plan_travel_flight(World(), 2444, state()['player_world_position'], goal())
    assert result.plan is None and result.reason == 'air_planning_budget_exhausted'


def test_vertical_steady_approach_climbs_when_below_the_known_landing():
    from wowbot.agent.flight_control import FlightControl
    plan = FlightPlan(2444, {'x': 0., 'y': 0., 'z': 0.}, {'x': 0., 'y': 0., 'z': 80.},
                      0., ((0., 0.),), cruise_z=110.)
    control = FlightControl(plan)
    assert control.assess(state(), 0., 3., 100.)[0] == 'MOVING'
    commands = control.commands(state(101., z=20., flying=True), 0., 0., 3., 101.)
    assert [command.binding for command in commands] == ['JUMP']


def test_supplied_departure_anchors_cannot_bypass_current_mmap_reachability():
    nav = NavigationService(navmesh=World(clipped=True))
    unproven = {'point': {'x': 8., 'y': 0., 'z': 0.}, 'flight_style': 'STEADY',
                'anchors': [{'x': 0., 'y': 0., 'z': 0.}, {'x': 8., 'y': 0., 'z': 0.}]}
    nav.start_skill_request('MOVE', goal(500., flight=False, flight_departure=unproven),
                           state(mounted=False, indoors=True), 'unproven-exit', 100.)
    assert not nav._active_route.anchors
    assert nav.command(state(mounted=False, indoors=True), 'blocked', 100.) == ()


@pytest.mark.parametrize('sky', [False, True])
def test_known_off_mesh_rooftop_preserves_touchdown_arrival_instead_of_an_impossible_walk(sky):
    class RoofTop(World):
        def project_position(self, instance, point, z_hint=None):
            return None if point['x'] >= 290. else super().project_position(instance, point, z_hint)
    nav = start(RoofTop(), state(sky=sky), goal(z=80., flight_style='SKYRIDING' if sky else 'STEADY'))
    flight = nav._movement.flight
    if sky:
        assert flight.path.landing_on_navmesh is False
    else:
        assert flight.plan.landing['navmesh'] is False
    nav.observe(state(101., x=100., z=110., flying=True, sky=sky), 'rooftop-air', 101.)
    result = nav.observe(state(102., x=300., z=80., sky=sky), 'rooftop-land', 102.)
    assert result.success and not nav._active_request.request_id.endswith(':ground')
