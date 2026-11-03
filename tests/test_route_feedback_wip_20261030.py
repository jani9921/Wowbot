"""REV4 route-feedback WIP (handoff 2026-10-30 §5): after a slow route or
local-plan query no movement command may come from the frame the query was
computed on; a measurement taken after the query must arrive first."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

from wowbot.agent.fast_movement_lane import advance_fast_movement
from wowbot.agent.models import Mode, Proposal
from wowbot.navigation.contracts import ArrivalEnvelope, GlobalRoute, NavigationRequest
from wowbot.navigation.entity_goal import ANCHOR_TOLERANCE_FLOOR, anchor_tolerance
from wowbot.navigation.route_feedback import RouteFeedback, feedback_scope, position
from wowbot.navigation.service import NavigationService
from wowbot.runtime import FailureReason, failure_reason_from_legacy
from wowbot.skills.movement import MovementSkillRunner

WORLD = {'coordinate_space': 'WORLD_YARDS'}


def measured(at=10., *, sample=None, x=0., y=0., z=100., **extra):
    return {'session_id': 'feedback-test', 'character_guid': 'Player-1', 'map_id': 2022,
            'monotonic_time': at, 'orientation': 0., 'player_present': True,
            'movement': {'flying': False, 'falling': False, 'moving': False},
            'packet_telemetry': {'selected_pid': 123, 'last_received_at': at},
            'player_world_position': {'x': x, 'y': y, 'z': z, 'z_known': True, 'z_observed': True,
                                      'z_source': 'PACKET_CLIENT_MOVEMENT_HELD', 'instance_id': 2444,
                                      'coordinate_space': 'WORLD_YARDS',
                                      'sample_time': at if sample is None else sample},
            **extra}


def request(timeout=20., **extra):
    return NavigationRequest('feedback-route', 'source-observation', 'MOVE_TO_LOCATION',
                             {'x': 20., 'y': 0., 'z': 100., 'z_known': True, 'instance_id': 2444,
                              'require_navmesh': True, 'coordinate_space': 'WORLD_YARDS', **extra},
                             arrival=ArrivalEnvelope(radius=2.), timeout=timeout)


def configured(monkeypatch):
    nav = NavigationService(navmesh=False)
    plans = []

    def plan(req, state, now, **kwargs):
        plans.append(deepcopy(state['player_world_position']))
        return GlobalRoute('r', ({**state['player_world_position'], 'z_known': True}, dict(req.destination)),
                           (), 20., 1., now, now+30.)
    monkeypatch.setattr(nav._global_planner, 'plan', plan)
    nav._planning_clock = lambda: 0.               # warm, instant queries unless a test says otherwise
    return nav, plans


def slow(nav, seconds):
    """The next query measures ``seconds`` of planning, later ones are instant."""
    values = iter((0., seconds))
    nav._planning_clock = lambda: next(values, seconds)


def slow_start(monkeypatch, seconds=.7, at=10., req=None):
    nav, plans = configured(monkeypatch)
    slow(nav, seconds)
    nav.start_request(req or request(), measured(at), at)
    return nav, plans


# ---- the feedback prerequisite itself ------------------------------------

def test_feedback_needs_a_sample_measured_after_the_query():
    state = measured(10.)
    feedback = RouteFeedback('r', 10.7, .7, position(state, WORLD), feedback_scope(state))
    assert feedback.assess(measured(10.6), WORLD, 10.6) == 'WAITING'
    assert feedback.assess(measured(10.9, sample=10.), WORLD, 10.9) == 'WAITING'   # relabelled old frame
    relabelled = measured(10.9)
    relabelled['player_world_position'].pop('sample_time')
    assert feedback.assess(relabelled, WORLD, 10.9) == 'WAITING'                   # merged-state time only
    assert feedback.assess(measured(10.8), WORLD, 10.8) == 'READY'
    assert feedback.assess(measured(10.8, sample=11.), WORLD, 10.8) == 'WAITING'   # not from the future


def test_feedback_replans_after_a_real_move_or_a_newly_known_height():
    state = measured(10.)
    feedback = RouteFeedback('r', 10.7, .7, position(state, WORLD), feedback_scope(state))
    assert feedback.assess(measured(10.8, x=2.), WORLD, 10.8) == 'READY'           # exactly 2 yd stays
    assert feedback.assess(measured(10.8, x=2.01), WORLD, 10.8) == 'REPLAN'
    assert feedback.assess(measured(10.8, z=103.), WORLD, 10.8) == 'REPLAN'        # observed Z changed
    unknown = measured(10.)
    unknown['player_world_position'].update(z=None, z_observed=False, z_known=False)
    blind = RouteFeedback('r', 10.7, .7, position(unknown, WORLD), feedback_scope(unknown))
    assert blind.assess(measured(10.8), WORLD, 10.8) == 'REPLAN'                   # height now known
    zero = RouteFeedback('r', 10.7, .7, position(measured(10., z=0.), WORLD), feedback_scope(measured(10.)))
    assert zero.assess(measured(10.8, z=0.), WORLD, 10.8) == 'READY'               # a real Z=0 is a height


def test_feedback_fails_on_scope_interruption_and_after_two_seconds():
    state = measured(10.)
    feedback = RouteFeedback('r', 10.7, .7, position(state, WORLD), feedback_scope(state))
    moved_map = measured(10.8)
    moved_map['player_world_position']['instance_id'] = 0
    for changed in (moved_map, measured(10.8, is_dead=True), measured(10.8, is_ghost=True),
                    measured(10.8, in_vehicle=True)):
        assert feedback.assess(changed, WORLD, 10.8) == 'post_plan_feedback_context_changed'
    for blocked in (measured(10.8, loading=True), measured(10.8, input_blocked=True),
                    measured(10.8, player_present=False)):
        assert feedback.assess(blocked, WORLD, 10.8) == 'post_plan_feedback_interrupted'
    assert feedback.assess(measured(12.7, sample=10.), WORLD, 12.7) == 'post_plan_feedback_timeout'
    assert failure_reason_from_legacy('post_plan_feedback_timeout') is FailureReason.STALE_OBSERVATION
    assert failure_reason_from_legacy('post_plan_feedback_context_changed') is FailureReason.WRONG_MAP_CONTEXT


# ---- NavigationService integration ---------------------------------------

def test_a_slow_route_query_issues_no_command_from_its_own_frame(monkeypatch):
    nav, plans = slow_start(monkeypatch)
    assert len(plans) == 1 and nav.route_feedback_pending()
    assert nav.command(measured(10.), 'same-frame', 10.) == ()
    assessment = nav.observe(measured(10.), 'same-frame', 10.)
    assert not assessment.terminal and assessment.reason == 'awaiting_post_plan_feedback'
    trace = nav.movement_snapshot()['route_feedback']
    assert trace['status'] == 'WAITING' and trace['active'] is True and trace['earliest_sample'] == 10.7
    assert nav.command(measured(10.9, sample=10.), 'relabelled', 10.9) == ()
    assert nav.resume_owned_route(measured(10.9, sample=10.), 10.9) is False      # still waiting
    assert nav.resume_owned_route(measured(10.8), 10.8) is True
    assert not nav.route_feedback_pending() and len(plans) == 1                   # READY: no re-query
    assert nav.command(measured(10.8), 'fresh', 10.8) != ()
    assert nav.movement_snapshot()['route_feedback']['status'] == 'READY'


def test_warm_queries_do_not_stop_and_the_threshold_is_exclusive(monkeypatch):
    for seconds, pending in ((.5, False), (.6, False), (.61, True)):
        nav, _ = slow_start(monkeypatch, seconds)
        assert nav.route_feedback_pending() is pending, seconds
    nav, _ = slow_start(monkeypatch, .5)
    assert nav.command(measured(10.), 'warm', 10.) != ()


def test_a_slow_local_replan_also_waits_for_feedback(monkeypatch):
    nav, _ = configured(monkeypatch)
    nav.start_request(request(), measured(10.), 10.)
    assert not nav.route_feedback_pending()
    slow(nav, .8)
    assert nav.command(measured(10.2), 'slow-local', 10.2) == ()
    assert nav.route_feedback_pending()
    assert nav.local_plan(measured(10.3), now=10.3) is None                       # no plan from the old frame


def test_a_moved_player_replans_the_same_trip_without_a_new_budget(monkeypatch):
    nav, plans = slow_start(monkeypatch)
    started = nav._request_started_at
    attempt = SimpleNamespace(proposal=Proposal.make('MOVE', 'test', request().destination))
    MovementSkillRunner(nav).step(attempt, measured(11., x=3.), 'medium-moved', 11., None)
    assert len(plans) == 2 and plans[1]['x'] == 3.
    assert nav._request_started_at == started == 10. and nav.trip.started_at == 10.
    assert nav.movement_snapshot()['route_feedback']['status'] == 'REPLAN'


def test_the_original_deadline_is_not_extended_by_the_wait(monkeypatch):
    nav, _ = slow_start(monkeypatch, req=request(timeout=1.))
    assert nav.resume_owned_route(measured(11.1, sample=10.), 11.1) is True
    result = nav.observe(measured(11.1, sample=10.), 'late', 11.1)
    assert result.terminal and not result.success and result.reason == 'movement_safety_deadline'


def test_feedback_timeout_and_context_change_fail_the_move(monkeypatch):
    nav, _ = slow_start(monkeypatch)
    assert nav.resume_owned_route(measured(12.8, sample=10.), 12.8) is True
    result = nav.observe(measured(12.8, sample=10.), 'timeout', 12.8)
    assert result.terminal and result.reason == 'post_plan_feedback_timeout'
    nav, _ = slow_start(monkeypatch)
    away = measured(10.8)
    away['player_world_position']['instance_id'] = 0
    nav.resume_owned_route(away, 10.8)
    assert nav.observe(away, 'scope', 10.8).reason == 'post_plan_feedback_context_changed'


def test_cancel_and_reset_drop_the_wait_and_a_late_sample_revives_nothing(monkeypatch):
    nav, plans = slow_start(monkeypatch)
    nav.cancel_movement()
    assert not nav.route_feedback_pending()
    nav.resume_owned_route(measured(10.8), 10.8)
    assert len(plans) == 1
    nav, _ = slow_start(monkeypatch)
    nav.reset()
    assert not nav.route_feedback_pending() and nav.movement_snapshot()['route_feedback'] is None


def test_fast_lane_releases_the_lease_and_hands_the_wait_to_medium(monkeypatch):
    nav, plans = slow_start(monkeypatch)
    current, stops = measured(10.8), []
    agent = SimpleNamespace(mode=Mode.FULL_AI, pending=SimpleNamespace(proposal=Proposal.make('MOVE', 'test')),
                            navigation=nav, world=SimpleNamespace(state=deepcopy(current),
                                                                 session_id=current['session_id'],
                                                                 last_received=10.8),
                            command_dispatcher=SimpleNamespace(stop_movement=lambda: stops.append(True)))
    result = advance_fast_movement(agent, current, 10.8, {'MOVE'}, state_override=current)
    assert result == {'consumed': False, 'force_medium': True, 'reason': 'movement_route_plan_pending'}
    assert stops and len(plans) == 1 and nav.route_feedback_pending()            # FAST queried nothing


# ---- projected endpoint, corridor identity, moving target ---------------

def test_a_projected_endpoint_keeps_the_target_within_the_interaction_band():
    target = {'x': 10., 'y': 0., 'z': 0., 'z_known': True}
    assert anchor_tolerance(target, {'x': 7., 'y': 0., 'z': 0.}, 3.5) == .5        # 3 yd off: .5 left
    assert anchor_tolerance(target, {'x': 10., 'y': 0., 'z': 0.}, 3.5) == 3.5      # on the target
    assert anchor_tolerance(target, {'x': 4., 'y': 0., 'z': 0.}, 3.5) == ANCHOR_TOLERANCE_FLOOR
    assert anchor_tolerance(target, {'x': 10., 'y': 0., 'z': 2.}, 3.5) == 1.5      # known Z=0 counts
    unknown = {**target, 'z_known': False}
    assert anchor_tolerance(unknown, {'x': 10., 'y': 0., 'z': 2.}, 3.5) == 3.5     # unknown Z adds nothing
    assert anchor_tolerance({'x': None, 'y': 0.}, {'x': 1., 'y': 0.}, 3.5) == 3.5


def test_zero_or_missing_ranges_fall_back_to_the_controller_tolerance():
    nav = NavigationService(navmesh=False)
    band = nav._interaction_band
    assert band(request()) == 2.
    assert band(replace(request(), arrival=ArrivalEnvelope(radius=0., desired_range=0.))) == \
        nav._movement.world_arrival_tolerance
    assert band(replace(request(), arrival=ArrivalEnvelope(radius=1., desired_range=0.))) == 1.
    assert band(replace(request(), arrival=ArrivalEnvelope(desired_range=3.))) == 3.


def test_a_new_corridor_waypoint_does_not_inherit_the_old_arrival_proof():
    nav = NavigationService(navmesh=False)
    movement, resets = nav._movement, []
    original = movement.reset
    movement.reset = lambda: (resets.append(True), original())[1]

    def leg(route_id, index, *, anchor=True):
        before = len(resets)
        movement.start({'x': 5., 'y': 0., 'coordinate_space': 'WORLD_YARDS', 'instance_id': 2444,
                        'entity_route_anchor': anchor, 'route_id': route_id,
                        'route_waypoint_index': index}, measured(10.), 'o', 10.)
        return len(resets) > before                            # arrival/progress evidence cleared
    leg('route:a', 1)
    assert leg('route:a', 1) is False                          # the same leg keeps its evidence
    assert leg('route:a', 2) is True and leg('route:b', 2) is True
    leg('route:c', 1, anchor=False)
    assert leg('route:d', 1, anchor=False) is False            # plain MOVE legs: XY identity only


def test_a_small_target_move_after_arrival_replans_only_when_the_band_is_left():
    from wowbot.agent.movement_controller import MovementPhase
    from test_domain_navigation_handoff_20261030 import GUID, navigation, world
    nav, _ = navigation()
    nav._planning_clock = lambda: 0.
    destination = nav.move_to_entity(world(), GUID, 'reach-edge', 10., stop_distance=3.5)
    assert destination is not None and not nav.owned_route_plan_pending(world(10.1), 10.1)
    nav._movement.phase = MovementPhase.ARRIVED
    near = world(10.2)
    near['player_world_position']['x'] = 12.                # 3 yd from the actor
    near['packet_entities'][GUID]['position']['x'] = 15.4   # 0.4 yd: still in the band
    assert nav.owned_route_plan_pending(near, 10.2) is False
    near['packet_entities'][GUID]['position']['x'] = 16.   # 1 yd, but now 4 yd away
    assert nav.owned_route_plan_pending(near, 10.3) is True
    nav._movement.phase = MovementPhase.MOVING              # walking: the 2 yd rule alone
    assert nav.owned_route_plan_pending(near, 10.4) is False
