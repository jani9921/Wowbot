"""A standing Retail client needs own movement feedback BEFORE a 3D route."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from wowbot.agent.fast_movement_lane import advance_fast_movement
from wowbot.agent.models import Mode, Proposal
from wowbot.navigation.contracts import ArrivalEnvelope, GlobalRoute, NavigationRequest
from wowbot.navigation.position_acquisition import required
from wowbot.navigation.service import NavigationService
from wowbot.runtime import FailureReason, failure_reason_from_legacy
from wowbot.skills.movement import MovementSkillRunner


def standing(at=10.):
    return {'session_id':'position-test','character_guid':'Player-1','map_id':2022,
        'monotonic_time':at,'orientation':0.,'player_present':True,
        'movement':{'flying':False,'falling':False,'moving':False},
        'packet_telemetry':{'selected_pid':123,'last_received_at':at},
        'player_world_position':{'x':0.,'y':0.,'z_known':False,'z_observed':False,
            'instance_id':2444,'coordinate_space':'WORLD_YARDS','sample_time':at}}


def request(**extra):
    return NavigationRequest('position-route','source-observation','MOVE_TO_LOCATION',
        {'x':20.,'y':0.,'z':100.,'z_known':True,'instance_id':2444,'require_navmesh':True,
         'coordinate_space':'WORLD_YARDS',**extra},arrival=ArrivalEnvelope(radius=2.),timeout=20.)


def measured(at=10.3):
    state=standing(at)
    state['player_world_position'].update(z=100.,z_observed=True,z_known=True,
        z_source='PACKET_CLIENT_MOVEMENT_HELD')
    return state


def configured(monkeypatch):
    nav=NavigationService(navmesh=False)
    plans=[]
    def plan(req,state,now,**kwargs):
        plans.append(deepcopy(state['player_world_position']))
        return GlobalRoute('r',({**state['player_world_position'],'z_known':True},dict(req.destination)),
                           (),20.,1.,now,now+30.)
    monkeypatch.setattr(nav._global_planner,'plan',plan)
    return nav,plans


def test_standing_first_fix_precedes_all_route_queries_and_cannot_certify_arrival(monkeypatch):
    nav,plans=configured(monkeypatch);state=standing()
    nav.start_request(request(x=0.),state,10.)
    assert plans==[] and nav._active_route is None
    assert nav.local_plan(state,now=10.01) is None and plans==[]
    assessment=nav.observe(state,'still-no-z',10.02)
    assert not assessment.terminal and not assessment.success and assessment.reason=='awaiting_server_position'
    assert nav.snapshot(10.02)['position_acquisition']['phase']=='AWAITING_PACKET'
    (tap,)=nav.command(state,'probe-1',10.02)
    assert tap.binding=='TURNLEFT' and tap.duration==.06
    assert nav.command(state,'probe-1',10.03)==()
    assert nav.command(standing(10.1),'probe-2',10.1)==()  # wait for response, never forward
    assert nav.command(standing(10.9),'probe-3',10.9)==() and plans==[]


def test_fresh_height_only_requests_a_handoff_then_medium_plans_the_same_trip(monkeypatch):
    nav,plans=configured(monkeypatch);req=request()
    nav.start_request(req,standing(),10.)
    current=measured()
    assert nav.position_plan_pending(current,10.3)
    assert nav.observe(current,'fast-measured',10.3).reason=='server_position_acquired_plan_pending'
    assert plans==[] and nav.command(current,'fast-measured',10.3)==()
    attempt=SimpleNamespace(proposal=Proposal.make('MOVE','test',req.destination))
    step=MovementSkillRunner(nav).step(attempt,current,'medium-measured',10.3,None)
    assert len(plans)==1 and plans[0]['z']==100. and plans[0]['z_observed'] is True
    assert not step.assessment.terminal and nav._position_wait is None
    assert nav.trip.started_at==10. and nav._request_started_at==10.
    assert nav.trip.request.destination==req.destination
    trace=nav.movement_snapshot()['position_acquisition']
    assert trace['phase']=='PLANNED' and trace['acquired_z']==100. and trace['active'] is False


def test_fast_lane_releases_lease_and_never_plans_the_measured_route(monkeypatch):
    nav,plans=configured(monkeypatch);nav.start_request(request(),standing(),10.)
    current=measured();stops=[]
    agent=SimpleNamespace(mode=Mode.FULL_AI,pending=SimpleNamespace(proposal=Proposal.make('MOVE','test')),
        navigation=nav,world=SimpleNamespace(state=deepcopy(current),session_id=current['session_id'],last_received=10.),
        command_dispatcher=SimpleNamespace(stop_movement=lambda:stops.append(True)))
    result=advance_fast_movement(agent,current,10.3,{'MOVE'},state_override=current)
    assert result=={'consumed':False,'force_medium':True,'reason':'movement_position_acquired_pending'}
    assert stops and plans==[] and nav._position_wait is not None


def test_pending_request_cannot_extend_its_deadline_and_timeout_is_position_uncertain(monkeypatch):
    nav,plans=configured(monkeypatch);req=request()
    nav.start_request(req,standing(),10.)
    nav.start_request(req,standing(12.),12.,continuing=True)
    assert nav._position_wait['started_at']==10. and nav._request_started_at==10.
    result=nav.observe(standing(13.),'timeout',13.)
    assert result.terminal and not result.success and result.reason=='server_position_probe_timeout'
    assert failure_reason_from_legacy(result.reason) is FailureReason.POSITION_UNCERTAIN
    nav.resume_position_request(measured(13.1),13.1)
    assert plans==[] and nav.command(measured(13.1),'after-timeout',13.1)==()


def test_short_original_request_budget_is_not_extended_by_acquisition(monkeypatch):
    nav,plans=configured(monkeypatch)
    nav.start_request(replace(request(),timeout=.25),standing(),10.)
    assert nav.observe(standing(10.26),'expired',10.26).terminal and plans==[]


@pytest.mark.parametrize('change',['session','character','map','pid','ui','combat','death','cast','fall','vehicle'])
def test_context_or_input_transition_stops_probe_without_planning(monkeypatch,change):
    nav,plans=configured(monkeypatch);nav.start_request(request(),standing(),10.)
    current=measured()
    if change=='session':current['session_id']='other'
    elif change=='character':current['character_guid']='Player-2'
    elif change=='map':current['player_world_position']['instance_id']=1
    elif change=='pid':current['packet_telemetry']['selected_pid']=456
    elif change=='ui':current['quest_ui_open']=True
    elif change=='combat':current['is_in_combat']=True
    elif change=='death':current['is_dead']=True
    elif change=='cast':current['is_casting']=True
    elif change=='fall':current['movement']['falling']=True
    else:current['in_vehicle']=True
    nav.resume_position_request(current,10.3)
    assert not nav.position_plan_pending(current,10.3) and nav.command(current,'blocked',10.3)==()
    result=nav.observe(current,'transition',10.3)
    assert result.terminal and not result.success and plans==[]


@pytest.mark.parametrize('cancel',['cancel_movement','reset'])
def test_cancel_drops_the_probe_and_cannot_rearm_it_on_a_late_packet(monkeypatch,cancel):
    nav,plans=configured(monkeypatch);nav.start_request(request(),standing(),10.)
    getattr(nav,cancel)()
    nav.resume_position_request(measured(),10.3)
    assert nav._position_wait is None and plans==[] and nav._active_request is None


@pytest.mark.parametrize('change',['no-packets','held-height','flying','vehicle','combat','legacy','no-route-required'])
def test_existing_non_probe_contracts_are_preserved(change):
    state=standing();dest=request().destination
    if change=='no-packets':state.pop('packet_telemetry')
    elif change=='held-height':state=measured()
    elif change=='flying':state['movement']['flying']=True
    elif change=='vehicle':state['in_vehicle']=True
    elif change=='combat':state['is_in_combat']=True
    elif change=='legacy':dest={**dest,'coordinate_space':'NORMALIZED_MAP'}
    else:dest={**dest,'require_navmesh':False}
    assert not required(dest,state)


def test_missing_verified_turn_binding_never_falls_back_to_a_guessed_key(monkeypatch):
    nav,plans=configured(monkeypatch)
    nav._movement.bindings=SimpleNamespace(contains=lambda action:False)
    nav.start_request(request(),standing(),10.)
    assert nav.command(standing(),'unbound',10.1)==() and plans==[]


def test_same_guid_is_rechecked_before_resuming_the_queued_entity_route(monkeypatch):
    nav,plans=configured(monkeypatch);state=standing();state['target']={'guid':'expected'}
    nav.start_request(request(target_guid='expected'),state,10.)
    current=measured();current['target']={'guid':'wrong'}
    nav.resume_position_request(current,10.3)
    assert plans==[] and nav.observe(current,'identity-lost',10.3).terminal


def test_parallel_servo_yields_the_same_attempt_to_medium_on_position_handoff():
    from test_parallel_control import setup
    agent,_=setup()
    servo=agent.parallel_control
    servo._last_action=agent.pending.action_id;servo._last_control_at=10.2
    servo.last_reason='movement_position_acquired_pending'
    assert not servo.drives(agent.pending,10.2)


def test_timeout_persists_one_bounded_probe_detail_even_after_controller_reset(monkeypatch):
    import json
    from wowbot.agent.models import Outcome
    from wowbot.agent.navigation_terminal import NavigationTerminalProcessor
    nav,plans=configured(monkeypatch);nav.start_request(request(),standing(),10.)
    nav.command(standing(),'probe-intent',10.1)
    failure=nav.observe(standing(13.),'expired',13.)
    attempt=SimpleNamespace(action_id='owned-action',proposal=SimpleNamespace(skill='MOVE',parameters={}))
    result=NavigationTerminalProcessor(nav).process(attempt,Outcome.FAILURE,failure.reason,
        FailureReason.POSITION_UNCERTAIN,standing(),standing(13.),latest_observation_id='expired',now=13.)
    kind,payload=result.events[0]
    assert kind=='NAVIGATION_FAILURE_DETAIL'
    trace=payload['position_acquisition']
    assert trace['phase']=='FAILED' and trace['active'] is False
    assert trace['failure_reason']=='server_position_probe_timeout'
    assert trace['proposed_probe']['binding']=='TURNLEFT' and trace['proposed_probe']['at']==10.1
    assert plans==[] and len(json.dumps(payload))<1800
    trace['proposed_probe']['binding']='MUTATED_SNAPSHOT'
    assert nav.movement_snapshot()['position_acquisition']['proposed_probe']['binding']=='TURNLEFT'
