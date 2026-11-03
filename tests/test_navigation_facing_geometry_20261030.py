"""Canonical bearing geometry and bounded terminal evidence; no client input."""
import ast
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import math

import pytest

from wowbot import entity_spatial
from wowbot.agent import packet_entity_facts
from wowbot.agent.models import Outcome
from wowbot.agent.navigation_terminal import NavigationTerminalProcessor
from wowbot.navigation.facing_geometry import assess
from wowbot.runtime import FailureReason
from test_server_arrival_facing_20261021 import ready_controller,enter_facing,seen

GUID='Creature-0-1-2444-1-7-00000001'


def world():
    return {'orientation':0.,'player_world_position':{'instance_id':2444},
            'packet_entities':{GUID:{'guid':GUID,'map_id':2444,
                'position':{'x':2.,'y':3.,'z':100.,'source':'PACKET_CREATE_MOVEMENT'}}}}


def test_entity_pose_helpers_are_one_canonical_implementation_without_agent_dependency():
    for name in ('entity','best_position','travel_position'):
        assert getattr(packet_entity_facts,name) is getattr(entity_spatial,name)
    nodes=ast.parse(Path(entity_spatial.__file__).read_text(encoding='utf-8')).body
    for node in nodes:
        if isinstance(node,ast.ImportFrom):assert 'agent' not in (node.module or '')


def test_current_server_spline_estimate_controls_bearing_not_old_nav_anchor():
    state=world();state['packet_entities'][GUID]['position']['estimate']={'x':0.,'y':5.,'z':100.}
    result=assess({'x':10.,'y':0.,'server_entity_guid':GUID},state,(0.,0.))
    assert result.reason=='KNOWN' and result.source=='SERVER_ENTITY'
    assert result.distance==5. and result.error==pytest.approx(math.pi/2)
    assert result.target_guid==GUID and (result.target_x,result.target_y)==(0.,5.)


@pytest.mark.parametrize('change,reason',[
    ('no-list','ENTITY_UNKNOWN_OR_REMOVED'),('missing','ENTITY_UNKNOWN_OR_REMOVED'),
    ('foreign-key','ENTITY_UNKNOWN_OR_REMOVED'),('removed','ENTITY_UNKNOWN_OR_REMOVED'),
    ('no-position','ENTITY_POSITION_UNKNOWN'),('wrong-map','WORLD_MISMATCH'),('no-map','WORLD_UNKNOWN')])
def test_unknown_identity_or_world_never_uses_an_old_request_point_for_turning(change,reason):
    state=world()
    if change=='no-list':state.pop('packet_entities')
    elif change=='missing':state['packet_entities'].clear()
    elif change=='foreign-key':state['packet_entities'][GUID]['guid']='other'
    elif change=='removed':state['packet_entities'][GUID]['removed']=True
    elif change=='no-position':state['packet_entities'][GUID].pop('position')
    elif change=='no-map':state['packet_entities'][GUID].pop('map_id')
    else:state['packet_entities'][GUID]['map_id']=1
    result=assess({'x':10.,'y':0.,'server_entity_guid':GUID},state,(0.,0.))
    assert result.reason==reason and result.error is None


def test_explicit_point_and_selected_identity_keep_separate_contracts():
    state=world()
    assert assess({'face_towards':{'x':0.,'y':3.}},state,(0.,0.)).error==math.pi/2
    state['target']={'guid':'selected','world_position':{'x':-5.,'y':0.,'instance_id':2444}}
    result=assess({'target_guid':'selected','x':3.,'y':0.},state,(0.,0.))
    assert result.reason=='KNOWN' and abs(result.error)==math.pi
    state['target']['guid']='different'
    assert assess({'target_guid':'selected'},state,(0.,0.)).reason=='SELECTED_IDENTITY_CHANGED'


def test_final_turn_failure_preserves_exact_geometry_and_last_turn_command():
    controller=ready_controller()
    enter_facing(controller)
    commands=controller.command(seen(math.pi/2,.5),'turn',.5)
    assert commands[0].binding=='TURNRIGHT'
    result=controller.observe(seen(math.pi/2,4.),'no-heading-progress',4.)
    assert result.terminal and result.reason=='facing_failed'
    snapshot=controller.snapshot()['final_facing']
    assert snapshot['geometry']['reason']=='KNOWN'
    assert snapshot['geometry']['error']==pytest.approx(-math.pi/2)
    assert snapshot['last_command_at']==.5
    assert snapshot['recent_commands'][-1][1]=='FACE_ON_ARRIVAL'
    snapshot['geometry']['reason']='changed'
    assert controller.snapshot()['final_facing']['geometry']['reason']=='KNOWN'


def test_terminal_failure_emits_one_compact_detail_event_without_whole_world_or_corridor():
    controller=ready_controller();enter_facing(controller)
    controller.command(seen(math.pi/2,.5),'turn',.5)
    controller.observe(seen(math.pi/2,4.),'failed',4.)
    navigation=SimpleNamespace(movement_snapshot=controller.snapshot)
    attempt=SimpleNamespace(action_id='same-attempt',proposal=SimpleNamespace(skill='MOVE',parameters={}))
    report=NavigationTerminalProcessor(navigation).process(attempt,Outcome.FAILURE,'facing_failed',
        FailureReason.FACING_FAILED,{},world(),latest_observation_id='after',now=4.)
    kind,payload=report.events[0]
    assert kind=='NAVIGATION_FAILURE_DETAIL' and payload['action_id']=='same-attempt'
    assert payload['final_facing']['geometry']['reason']=='KNOWN'
    assert 'packet_entities' not in str(payload) and 'path_corridor' not in payload


def test_lost_server_facing_identity_stops_with_its_real_cause_without_spending_turn_budget():
    controller=ready_controller(server_entity_guid=GUID)
    current=seen(math.pi/2,.1);current['packet_entities']={}
    for i in range(1,5):
        result=controller.observe(current,str(i),i*.1)
        if result.terminal:break
    assert result.terminal and not result.success
    assert result.reason=='reach_object_identity_or_position_lost'
    assert not controller.command(current,'no-blind-turn',.5)
    assert controller.snapshot()['final_facing']['geometry']['reason']=='ENTITY_UNKNOWN_OR_REMOVED'
    current['packet_entities']=world()['packet_entities']
    after=controller.observe(current,'late-returned-identity',.6)
    assert after.terminal and not after.success  # only an explicit new start can re-arm
