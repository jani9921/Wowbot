"""Recorded Charge transition and server-only positioning through shared combat."""
from copy import deepcopy

import pytest

from wowbot.combat.mobility import settling_deadline
from wowbot.navigation.service import NavigationService
from wowbot.runtime import SkillStatus
from wowbot.skills.combat import CombatSkill
from test_m0_combat_loot_skills import active

GUID='Creature-0-1469-0-29720-50039-000064C1B0'


def state(at=10., *, melee=False, charge=False):
    return {'session_id':'range-test','monotonic_time':at,'target_sample_time':at,
        'orientation':0.,'power':30,'health':100,'max_health':100,'is_in_combat':True,
        'target':{'guid':GUID,'attackable':True,'dead':False,'world_position':False},
        'player_world_position':{'x':0.,'y':0.,'z':10.,'instance_id':0,'coordinate_space':'WORLD_YARDS',
                                 'sample_time':at,'z_known':True},
        'packet_entities':{GUID:{'guid':GUID,'kind':'CREATURE','map_id':0,'entry_id':50039,
            'position':{'x':7.,'y':0.,'z':10.,'age':0.,'source':'PACKET_CREATE_MOVEMENT'}}},
        'actionbar':[
            {'id':1464,'kind':'spell','action':'ACTIONBUTTON1','is_harmful':True,
             'is_usable':True,'in_range':melee,'cooldown_remaining':0,'min_range':0,'max_range':0},
            {'id':100,'kind':'spell','action':'ACTIONBUTTON2','is_harmful':True,
             'is_usable':True,'in_range':charge,'cooldown_remaining':0,'min_range':8,'max_range':25},
            {'id':23922,'kind':'spell','action':'ACTIONBUTTON3','is_harmful':True,
             'is_usable':True,'in_range':melee,'cooldown_remaining':0,'min_range':0,'max_range':0}]}


def test_range_gap_uses_exact_server_position_when_retail_selected_position_is_absent():
    world=state();skill=CombatSkill();running=active('COMBAT',{'guid':GUID},world,deadline=30.)
    result=skill.begin(running,world,10.)
    assert result.status is SkillStatus.RUNNING and result.commands==()
    request=result.metadata['approach_request']
    assert request=={'kind':'WORLD_COMBAT','expected_guid':GUID,'stop_distance':3.5}
    destination=NavigationService().move_to_entity(world,request['expected_guid'],'o',10.,
                                                    stop_distance=request['stop_distance'])
    assert destination['server_entity_guid']==GUID and destination['interaction_recipient_guid']==GUID
    assert (destination['x'],destination['y'],destination['z'])==(7.,0.,10.)
    assert destination['require_navmesh'] is True and destination['interaction_identity_source']=='TARGET'
    assert running.local_retry_count==1


def test_successful_charge_does_not_fail_or_issue_walk_while_its_range_update_is_in_flight():
    world=state(10.24);world.update(combat_last_spell_id=100,combat_last_cast_at=10.)
    skill=CombatSkill();running=active('COMBAT',{'guid':GUID},world,deadline=30.)
    result=skill.begin(running,world,10.24)
    assert result.status is SkillStatus.RUNNING and result.commands==()
    assert result.metadata=={'mobility_settling_until':10.8}
    assert running.local_retry_count==0 and not running.skill_context['combat'].get('approach_request')
    # Like the recorded run, the next range transition is actual evidence,
    # not a new plan or a guessed Charge success => target-dead result.
    arrived=state(10.45,melee=True)
    arrived.update(combat_last_spell_id=100,combat_last_cast_at=10.)
    result=skill.verify(running,arrived,10.45)
    assert result.status is SkillStatus.RUNNING
    assert [c.binding for c in result.commands]==['ACTIONBUTTON3']
    assert running.local_retry_count==0


def test_charge_settle_expires_from_original_cast_time_and_then_uses_canonical_approach():
    world=state(10.24);world.update(combat_last_spell_id=100,combat_last_cast_at=10.)
    skill=CombatSkill();running=active('COMBAT',{'guid':GUID},world,deadline=30.)
    skill.begin(running,world,10.24)
    late=state(10.9);late.update(combat_last_spell_id=100,combat_last_cast_at=10.)
    result=skill.verify(running,late,10.9)
    assert result.status is SkillStatus.RUNNING and 'approach_request' in result.metadata
    assert 'mobility_settling_until' not in result.metadata and running.local_retry_count==1


@pytest.mark.parametrize('change',['wrong-target','removed','wrong-map','no-position','foreign-key'])
def test_server_fallback_cannot_bypass_identity_removal_or_world(change):
    world=state()
    if change=='wrong-target':world['target']['guid']='other'
    elif change=='removed':world['packet_entities'][GUID]['removed']=True
    elif change=='wrong-map':world['packet_entities'][GUID]['map_id']=1
    elif change=='no-position':world['packet_entities'][GUID].pop('position')
    else:world['packet_entities']={'another-key':world['packet_entities'][GUID]}
    assert CombatSkill._world_approach_request(world,GUID) is None


@pytest.mark.parametrize('change',['no-success','old-success','future-clock','wrong-target','dead','no-metadata'])
def test_mobility_settling_is_not_a_generic_wait_or_range_permission(change):
    world=state(10.2);world.update(combat_last_spell_id=100,combat_last_cast_at=10.)
    actions=CombatSkill().ability_rules.actionbar(world)
    if change=='no-success':world.pop('combat_last_cast_at')
    elif change=='old-success':world['combat_last_cast_at']=8.
    elif change=='future-clock':world['combat_last_cast_at']=11.
    elif change=='wrong-target':world['target']['guid']='other'
    elif change=='dead':world['target']['dead']=True
    else:actions=[{**a,'movement_settle_seconds':None} for a in actions]
    assert settling_deadline(world,actions,GUID,10.2) is None


def test_a_near_target_uses_melee_without_requiring_charge_to_be_in_range():
    world=state(melee=True,charge=False);skill=CombatSkill()
    running=active('COMBAT',{'guid':GUID},world,deadline=30.)
    result=skill.begin(running,world,10.)
    assert result.commands[0].binding=='ACTIONBUTTON3'
    assert 'approach_request' not in result.metadata


def test_charge_max_range_does_not_become_the_followup_melee_approach_radius():
    world=state(10.,charge=True)
    skill=CombatSkill();running=active('COMBAT',{'guid':GUID},world,deadline=30.)
    result=skill.begin(running,world,10.)
    assert result.commands[0].binding=='ACTIONBUTTON2'
    assert running.skill_context['combat']['desired_range']==3.5
    outside=state(11.);outside.update(combat_last_spell_id=100,combat_last_cast_at=10.)
    request=skill.verify(running,outside,11.).metadata['approach_request']
    assert request['stop_distance']==3.5  # never the opener's former 25*.8=20


def test_mobility_opener_keeps_a_ranged_rotation_range_instead_of_forcing_melee():
    from wowbot.combat.positioning.range import engagement_range
    skill=CombatSkill()
    charge=next(a for a in skill.ability_rules.actionbar(state()) if a['id']==100)
    ranged={'id':77,'kind':'spell','action':'ACTIONBUTTON4','is_harmful':True,
            'max_range':30.,'combat_priority':100.}
    assert engagement_range([charge,ranged],skill.ability_rules.definition(charge))==24.


def test_range_policy_does_not_turn_zero_or_unbound_spells_into_ranged_attack_authority():
    from wowbot.combat.positioning.range import engagement_range
    skill=CombatSkill();actions=skill.ability_rules.actionbar(state())
    charge=next(a for a in actions if a['id']==100)
    assert engagement_range([*actions,{'kind':'spell','max_range':40.,'is_harmful':True}],
                            skill.ability_rules.definition(charge))==3.5


@pytest.mark.parametrize('addon_map',[0,1])
def test_exact_server_pose_beats_nonempty_zero_height_or_wrong_world_addon_pose(addon_map):
    world=state()
    world['target']['world_position']={'x':5.,'y':1.,'z':0.,'z_known':True,
        'instance_id':addon_map,'source':'UNIT_POSITION','sample_time':10.}
    assert CombatSkill._world_approach_request(world,GUID) is not None
    navigation=NavigationService()
    destination=navigation.move_to_entity(world,GUID,'pose-priority',10.,stop_distance=3.5)
    assert destination['server_entity_guid']==GUID and destination['z_source']=='PACKET_ENTITY'
    assert (destination['x'],destination['y'],destination['z'],destination['instance_id'])==(7.,0.,10.,0)
    assert world['target']['world_position']['z']==0.  # source observation is not rewritten


def test_foreign_server_world_does_not_override_a_fresh_selected_same_world_pose():
    world=state();world['packet_entities'][GUID]['map_id']=1
    world['target']['world_position']={'x':5.,'y':1.,'z':12.,'z_known':True,
        'instance_id':0,'sample_time':10.,'coordinate_space':'WORLD_YARDS'}
    destination=NavigationService().move_to_entity(world,GUID,'addon-still-scoped',10.)
    assert destination.get('server_entity_guid') is None
    assert (destination['x'],destination['y'],destination['z'],destination['instance_id'])==(5.,1.,12.,0)


def test_no_server_height_leaves_addon_target_xy_without_a_fake_zero_layer():
    world=state();world['packet_entities']={}
    world['target']['world_position']={'x':5.,'y':1.,'z':0.,'z_known':True,
        'source':'UNIT_POSITION','instance_id':0,'sample_time':10.}
    nav=NavigationService()
    destination=nav.move_to_entity(world,GUID,'no-server-height',10.)
    assert destination['z_known'] is False and 'layer_z' not in destination and 'z' not in destination
    assert nav._movement.destination['z_known'] is False
    assert 'z' not in nav._movement.destination and 'layer_z' not in nav._movement.destination


def test_server_recipient_reach_refreshes_the_same_guid_instead_of_freezing_its_start_pose():
    from test_domain_navigation_handoff_20261030 import navigation
    world=state();world['player_world_position']['z_observed']=True
    nav,_=navigation()
    nav.move_to_entity(world,GUID,'moving',10.)
    moved=deepcopy(world)
    moved['packet_entities'][GUID]['position'].update(x=12.,y=3.,z=11.)
    assert nav.owned_route_plan_pending(moved,10.)
    assert nav.resume_owned_route(moved,10.,allow_route_queries=False) is False
    nav.resume_owned_route(moved,10.)
    point=nav._active_request.destination
    assert (point['x'],point['y'],point['z'],point['layer_z'])==(12.,3.,11.,11.)
    assert point['server_entity_guid']==GUID
    moved['packet_entities'][GUID]['removed']=True
    assert not nav._entity_route_identity_matches(moved,10.)
