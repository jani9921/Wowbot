"""Shared entity routing, real FSM handoff and own-pose projection; no OS input."""
from copy import deepcopy
import math
from types import SimpleNamespace

import pytest

from wowbot.agent.active_skill_supervision import ActiveSkillSupervisor
from wowbot.agent.models import Outcome, Proposal
from wowbot.agent.world_packet_reducer import WorldPacketReducer
from wowbot.navigation.mmap_navmesh import NavMeshPath
from wowbot.navigation.service import NavigationService
from wowbot.runtime import FailureReason, SkillResult, SkillStatus
from wowbot.skills.combat_runtime import CombatRuntimeRunner
from wowbot.skills.interaction_runtime import InteractionRuntimeRunner
from wowbot.skills.loot import LootSkill
from wowbot.skills.loot_runtime import LootRuntimeRunner
from test_m0_combat_loot_skills import active

GUID='Creature-0-1469-0-29720-50039-000064C1B0'


class Geometry:
    """Deterministic geometry API test double, not native/live path evidence."""
    revision='test-geometry'
    def __init__(self): self.calls=[]
    def find_path(self, instance, start, end):
        self.calls.append((instance,deepcopy(start),deepcopy(end)))
        points=[dict(start),{'x':(start['x']+end['x'])/2,'y':end['y']+2.,'z':end['z']},dict(end)]
        anchors=tuple({**p,'coordinate_space':'WORLD_YARDS','instance_id':instance,
                       'source':'TRINITYCORE_MMAP','z_known':True} for p in points)
        return NavMeshPath(anchors,3,1,sum(math.dist((a['x'],a['y'],a['z']),
            (b['x'],b['y'],b['z'])) for a,b in zip(anchors,anchors[1:])))


def navigation():
    geometry=Geometry()
    return NavigationService(navmesh=geometry),geometry


def world(at=10., *, dead=False):
    return {'session_id':'domain-test','character_guid':'Player-1','monotonic_time':at,
        'target_sample_time':at,'orientation':0.,'movement':{'falling':False,'flying':False},
        'target':{'guid':GUID,'dead':dead,'attackable':not dead,'world_position':False},
        'player_world_position':{'x':0.,'y':0.,'z':10.,'z_known':True,'z_observed':True,
            'coordinate_space':'WORLD_YARDS','instance_id':0,'sample_time':at},
        'packet_entities':{GUID:{'guid':GUID,'kind':'CREATURE','map_id':0,'entry_id':50039,'dead':dead,
            'position':{'x':15.,'y':0.,'z':10.,'source':'PACKET_CREATE_MOVEMENT'}}}}


def runtime_active(skill, state):
    return active(skill,{'guid':GUID},state,deadline=30.)


def approach_result(skill):
    request=({'kind':'WORLD_CORPSE','corpse_guid':GUID} if skill=='LOOT'
             else {'kind':'WORLD_ENTITY' if skill=='INTERACT' else 'WORLD_COMBAT','expected_guid':GUID})
    return SkillResult(SkillStatus.RUNNING,metadata={'approach_request':{**request,'stop_distance':3.5}})


def test_entity_api_queries_shared_geometry_and_preserves_the_corridor_waypoint():
    nav,geo=navigation();state=world()
    destination=nav.move_to_entity(state,GUID,'owned',10.,stop_distance=3.5)
    assert geo.calls and nav._active_request.mode=='APPROACH_ENTITY'
    assert destination['entity_goal'] is True and destination['require_navmesh'] is True
    assert nav._active_request.target_entity_id==GUID and nav._active_route.regions[0]['route_source']=='TRINITYCORE_MMAP'
    waypoint=deepcopy(nav._movement.destination)
    assert waypoint['x']==7.5 and waypoint['y']==2. and waypoint['entity_route_anchor']
    assert nav._movement._refresh_object_destination(state)
    assert (nav._movement.destination['x'],nav._movement.destination['y'])==(7.5,2.)
    assert waypoint.get('face_on_arrival') is not True  # intermediate corners never face the final actor


@pytest.mark.parametrize('skill',['COMBAT','INTERACT','LOOT'])
def test_every_domain_defers_fast_planning_then_medium_resumes_the_same_attempt(skill):
    state=world(dead=skill=='LOOT');nav,geo=navigation();running=runtime_active(skill,state)
    result=approach_result(skill)
    dummy=SimpleNamespace(verify=lambda *a:result,resume_after_approach=lambda *a,**k:SkillResult(SkillStatus.RUNNING))
    if skill=='COMBAT':
        runner=CombatRuntimeRunner(nav,dummy)
        step=runner.step_verification(state,result,'fast',10.,allow_route_queries=False,deadline=30.)
        continuing=runner.continue_approach
    elif skill=='INTERACT':
        runner=InteractionRuntimeRunner(nav,dummy)
        step=runner.step_verification(running,state,result,world_observation_id='fast',
            visual_observation_id='v',now=10.,allow_route_queries=False)
        continuing=runner.step_world_entity
    else:
        runner=LootRuntimeRunner(nav,dummy)
        step=runner.step_verification(running,state,'fast',10.,allow_route_queries=False)
        continuing=runner.continue_approach
    assert step.plan_pending and step.stop_movement and not step.commands and geo.calls==[]
    assert nav._deferred_request is nav._active_request and nav._active_request.timeout==20.
    retry_count=running.local_retry_count
    assert continuing(running,state,'fast-again',10.1,allow_route_queries=False).plan_pending
    assert geo.calls==[] and running.local_retry_count==retry_count
    step=continuing(running,state,'medium',10.2)
    assert not step.plan_pending and step.movement_lane and len(geo.calls)==1
    assert nav._deferred_request is None and nav._request_started_at==10. and nav.trip.started_at==10.
    assert running.local_retry_count==retry_count and running.attempt.deadline==30.


@pytest.mark.parametrize('skill',['COMBAT','INTERACT','LOOT'])
def test_domain_original_deadline_expires_before_a_queued_path_query(skill):
    state=world(dead=skill=='LOOT');nav,geo=navigation();running=runtime_active(skill,state)
    nav.move_to_entity(state,GUID,'queued',10.,allow_dead=skill=='LOOT',defer_plan=True,deadline=30.)
    dummy=SimpleNamespace()
    runner=({'COMBAT':CombatRuntimeRunner,'INTERACT':InteractionRuntimeRunner,'LOOT':LootRuntimeRunner}[skill])(nav,dummy)
    continue_=runner.step_world_entity if skill=='INTERACT' else runner.continue_approach
    step=continue_(running,world(30.,dead=skill=='LOOT'),'expired',30.)
    assert step.terminal_result.reason is FailureReason.TIMEOUT and step.stop_movement
    assert geo.calls==[] and nav._deferred_request is None and not step.commands


@pytest.mark.parametrize('change',['target','map','session','loading','ui'])
def test_queued_query_rechecks_current_identity_scope_and_input_state(change):
    state=world();nav,geo=navigation()
    nav.move_to_entity(state,GUID,'queued',10.,defer_plan=True,deadline=30.)
    current=world(10.2)
    if change=='target':current['target']['guid']='other-guid'
    elif change=='map':current['player_world_position']['instance_id']=1
    elif change=='session':current['session_id']='next-session'
    elif change=='loading':current['loading']=True
    else:current['quest_ui_open']=True
    nav.resume_owned_route(current,10.2)
    assert geo.calls==[] and nav._deferred_request is None
    assert nav.observe(current,'bad-context',10.2).terminal and nav.command(current,'no-input',10.2)==()


def test_manual_cancel_discards_pending_query_and_late_data_cannot_restart_it():
    nav,geo=navigation();state=world()
    nav.move_to_entity(state,GUID,'queued',10.,defer_plan=True)
    nav.cancel_movement();nav.resume_owned_route(world(10.2),10.2)
    assert geo.calls==[] and nav._active_request is None and nav._deferred_request is None


def test_moving_actor_replans_in_medium_and_trip_arrival_resolves_the_same_guid():
    nav,geo=navigation();nav.move_to_entity(world(),GUID,'moving',10.,stop_distance=3.5)
    original_goal=nav.trip.request.destination
    moving=world(10.3);moving['packet_entities'][GUID]['position']['x']=25.
    old_waypoint=deepcopy(nav._movement.destination)
    assert not nav.resume_owned_route(moving,10.3,allow_route_queries=False)
    assert len(geo.calls)==1 and nav._movement.destination==old_waypoint
    nav.resume_owned_route(moving,10.3)
    assert len(geo.calls)==2 and geo.calls[-1][2]['x']==25.
    assert nav.trip.request.destination==original_goal and nav.trip.started_at==10.
    moving['player_world_position']['x']=23.
    assert nav.trip.final_arrival_problem(moving,10.3) is None
    moving['player_world_position']['x']=13.
    assert nav.trip.final_arrival_problem(moving,10.3)=='trip_original_goal_not_reached'
    moving['target']['guid']='different-spawn-same-entry'
    assert nav.trip.final_arrival_problem(moving,10.3)=='trip_entity_identity_or_position_lost'


def test_loot_uses_server_corpse_position_without_promoting_it_to_loot_eligibility():
    from wowbot.agent.packet_entity_facts import interaction_position
    state=world(dead=True)
    assert interaction_position(state,GUID) is None
    assert interaction_position(state,GUID,allow_dead=True)['x']==15.
    assert LootSkill._world_approach_request(state,GUID)['corpse_guid']==GUID
    nav,geo=navigation();nav.move_to_entity(state,GUID,'corpse',10.,allow_dead=True)
    assert geo.calls and nav._active_request.destination['allow_dead'] is True
    assert 'owned_corpse_guids' not in state and 'lootable' not in state['target']
    assert 'loot_eligible' not in nav._active_request.destination


def test_los_query_uses_exact_server_position_and_the_same_deferred_navigation_boundary():
    nav,geo=navigation();state=world();state['is_in_combat']=True
    point=nav.reposition_for_los(state,GUID,'los',10.,defer_plan=True,deadline=30.)
    assert point['z']==10. and point['require_navmesh'] is True and geo.calls==[]
    assert nav._active_request.mode=='REPOSITION_FOR_LOS' and nav._active_request.timeout==2.5
    nav.resume_owned_route(world(10.2),10.2)
    assert geo.calls and nav._request_started_at==10.
    calls=len(geo.calls)
    nav.resume_owned_route(world(12.6),12.6)
    assert len(geo.calls)==calls and nav.observe(world(12.6),'expired-los',12.6).reason=='movement_safety_deadline'
    assert nav.command(world(12.6),'no-late-input',12.6)==()


def test_supervisor_fast_handoff_does_not_verify_twice_or_consume_another_retry():
    from test_active_skill_supervision import Verification, Registry
    nav,geo=navigation();state=world();running=runtime_active('COMBAT',state);calls=[]
    def verify(active_,current,now):
        calls.append(now);running.local_retry_count+=1
        result=approach_result('COMBAT')
        running.skill_context['combat']={'approach_request':result.metadata['approach_request']}
        return result
    skill=SimpleNamespace(verify=verify)
    supervisor=ActiveSkillSupervisor(m0_skills=skill,verification_engine=Verification(),
        interaction_runtime=None,combat_runtime=CombatRuntimeRunner(nav,SimpleNamespace()),
        loot_runtime=None,registry=Registry())
    attempt=SimpleNamespace(proposal=Proposal.make('COMBAT','test'))
    view=SimpleNamespace(state=state)
    step=supervisor.step(attempt,running,view,world_observation_id='fast',
        visual_observation_id='v',now=10.,allow_route_queries=False)
    assert step.yield_tick and step.stop_movement and step.reason=='skill_navigation_plan_pending'
    assert geo.calls==[] and calls==[10.]
    supervisor.step(attempt,running,view,world_observation_id='medium',visual_observation_id='v',now=10.2)
    assert len(geo.calls)==1 and calls==[10.] and running.local_retry_count==1


def test_parallel_control_requests_medium_without_movement_or_a_new_attempt(monkeypatch):
    from test_parallel_control import setup, control_sample
    from wowbot.agent.active_skill_supervision import ActiveSkillSupervisionStep
    agent,executor=setup('COMBAT');action=agent.pending.action_id;calls=[]
    def step(*args,**kwargs):
        calls.append(kwargs['allow_route_queries'])
        return ActiveSkillSupervisionStep(yield_tick=True,stop_movement=True,reason='skill_navigation_plan_pending')
    monkeypatch.setattr(agent.active_skill_supervisor,'step',step)
    payload,vision=control_sample(agent,10.04,1)
    result=agent.parallel_control.tick(payload,10.04,vision,10.04)
    assert result['force_medium'] and result['reason']=='skill_navigation_plan_pending'
    assert calls==[False] and not agent.parallel_control.drives(agent.pending,10.04)
    assert agent.pending.action_id==action and executor.stops
    assert all(command.kind=='POINTER' for command in executor.commands)  # compatible attention remains active


def test_unknown_mesh_cannot_silently_become_direct_server_approach():
    nav=NavigationService(navmesh=False)
    nav.move_to_entity(world(),GUID,'no-mesh',10.)
    failure=nav.observe(world(10.1),'checked',10.1)
    assert failure.terminal and not failure.success
    assert failure.reason=='required_navmesh_route_unavailable' and nav.command(world(),'no-input',10.1)==()


def test_fast_view_recovers_held_server_height_after_addon_xy_overlay(bridge):
    from test_packet_agent_bridge import deliver
    from test_packet_codecs import decoded
    from wowbot.agent.parallel_view import control_view
    deliver(bridge,decoded()[-1])
    payload={'session_id':'live-s','monotonic_time':11.,'player_world_position':{
        'x':10.6,'y':-20.2,'instance_id':2175,'coordinate_space':'WORLD_YARDS',
        'source':'C_MAP_PLAYER_WORLD_POS','sample_time':11.,'z_known':False}}
    view=control_view(bridge.world.state,payload,None,11.)
    assert view['player_world_position'].get('z_observed') is not True
    before=deepcopy(bridge.world.addon_state)
    WorldPacketReducer.project_own_navigation(bridge.world,view,11.)
    assert view['player_world_position']['z']==31.75 and view['player_world_position']['z_observed'] is True
    assert view['player_world_position']['sample_time']==11.  # actual addon XY clock, no fake new packet
    assert bridge.world.__dict__['_packet_last_own']['sampled_at']==10.
    assert bridge.world.addon_state==before


def test_explicit_probe_handoff_releases_input_without_erasing_the_owned_request():
    from test_parallel_control import setup
    from wowbot.agent.active_skill_supervision import ActiveSkillSupervisionStep
    agent,executor=setup('COMBAT');nav=agent.navigation
    nav.move_to_entity(world(),GUID,'owned',10.,defer_plan=True)
    request=nav._deferred_request
    yielded=ActiveSkillSupervisionStep(yield_tick=True,stop_movement=True,preserve_navigation=True,
        reason='skill_navigation_plan_pending')
    assert agent._apply_active_supervision(yielded,10.1)
    assert executor.stops and nav._deferred_request is request
    # An ordinary stop still cancels; only the explicit handoff preserves it.
    agent._apply_active_supervision(ActiveSkillSupervisionStep(stop_movement=True,yield_tick=True),10.2)
    assert nav._deferred_request is None


@pytest.mark.parametrize('skill',['COMBAT','INTERACT','LOOT'])
def test_nested_navigation_failure_retains_cause_and_releases_physical_movement(skill):
    nav=NavigationService(navmesh=False);state=world(dead=skill=='LOOT')
    running=runtime_active(skill,state)
    nav.move_to_entity(state,GUID,'unavailable',10.,allow_dead=skill=='LOOT')
    dummy=SimpleNamespace()
    runner=({'COMBAT':CombatRuntimeRunner,'INTERACT':InteractionRuntimeRunner,'LOOT':LootRuntimeRunner}[skill])(nav,dummy)
    step=(runner.step_world_entity if skill=='INTERACT' else runner.continue_approach)(running,state,'failed',10.1)
    assert step.stop_movement and step.terminal_result.reason is FailureReason.PATH_BLOCKED
    detail=step.terminal_result.metadata['navigation_failure']
    assert detail['reason']=='required_navmesh_route_unavailable'
    assert 'packet_entities' not in detail and 'global_route' not in detail
    assert nav._active_request is None


def test_own_height_projection_does_not_cross_a_native_continuity_gap(bridge):
    from test_packet_agent_bridge import deliver
    from test_packet_codecs import decoded
    deliver(bridge,decoded()[-1])
    bridge.world.session_context_provider=SimpleNamespace(continuity_generation=2,capture_epoch='new',
        process=SimpleNamespace(generation='new-process',selected_pid=77),expected=lambda pid:None)
    state={'player_world_position':{'x':10.5,'y':-20.25,'z_known':False,'instance_id':2175}}
    WorldPacketReducer.project_own_navigation(bridge.world,state,10.2)
    assert state['player_world_position'].get('z_observed') is not True and 'z' not in state['player_world_position']
    held={'player_world_position':{'x':10.5,'y':-20.25,'z':31.75,'z_observed':True,'z_known':True,
        'source':'C_MAP_PLAYER_WORLD_POS','z_source':'PACKET_CLIENT_MOVEMENT_HELD','instance_id':2175}}
    WorldPacketReducer.project_own_navigation(bridge.world,held,10.2)
    assert held['player_world_position']['z_observed'] is False and 'z' not in held['player_world_position']


def test_entity_api_uses_the_actual_python_mmap_backend_on_a_real_tile_layout(tmp_path):
    from test_mmap_navmesh import _map_header, _tile
    from wowbot.navigation.mmap_navmesh import TrinityMMapNavMesh
    (tmp_path/'2175.mmap').write_bytes(_map_header())
    (tmp_path/'2175_32_36.mmtile').write_bytes(_tile())
    geometry=TrinityMMapNavMesh(tmp_path);nav=NavigationService(navmesh=geometry)
    state=world()
    guid=GUID.replace('-0-29720-','-2175-29720-')
    state['packet_entities'][guid]=state['packet_entities'].pop(GUID)
    state['packet_entities'][guid]['guid']=guid
    state['target']['guid']=guid
    state['player_world_position'].update(x=-449.7,y=-2614.,z=0.,instance_id=2175)
    state['packet_entities'][guid]['map_id']=2175
    state['packet_entities'][guid]['position'].update(x=-448.3,y=-2614.,z=0.)
    nav.move_to_entity(state,guid,'mmap-entity',10.,stop_distance=.2)
    assert geometry.last_diagnostics['reason']=='route_found'
    assert nav._active_route.regions[0]['route_source']=='TRINITYCORE_MMAP'
    assert nav._active_request.destination['z']==0. and nav._active_request.target_entity_id==guid


from test_packet_agent_bridge import bridge  # fixture; synthetic authenticated IPC only
