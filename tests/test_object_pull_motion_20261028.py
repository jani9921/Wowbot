from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills.object_use import ObjectUseSkill
from wowbot.quests.object_motion import motion_for_template
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
from wowbot.navigation.service import NavigationService
from wowbot.navigation.mmap_navmesh import NavMeshPath


GUID = 'GameObject-0-1463-2444-47-377265-0000616823'
TEMPLATE = {'entry':377265,'name':'Overgrown Weeds','type':10,'Data10':375531}


def world(t=1., x=0., count=0, **changes):
    motion = motion_for_template('Pull Overgrown Weeds',TEMPLATE,'Pulling Weeds')
    return {'session_id':'pull-test','monotonic_time':t,'map_id':2022,'orientation':0.,
        'is_in_combat':False,'is_mounted':False,'player_present':True,
        'movement':{'moving':False,'falling':False,'indoors':False},
        'player_world_position':{'x':x,'y':0.,'z':337.,'z_observed':True,'z_known':True,
            'instance_id':2444,'coordinate_space':'WORLD_YARDS','sample_time':t},
        'soft_targets':[{'guid':GUID,'object_id':377265,'name':'Overgrown Weeds',
            'unit_type':'GAMEOBJECT','source_unit':'softinteract'}], 'soft_targets_sample_time':t,
        'packet_entities':{GUID:{'guid':GUID,'entry_id':377265,'map_id':2444,'kind':'GAMEOBJECT',
            'position':{'x':1.,'y':0.,'z':337.}}},
        'active_quests':[{'quest_id':66788,'is_complete':False,'objectives':[
            {'description':'0/2 Sweep Fallen Leaves','current':0,'required':2,'is_complete':False},
            {'description':'Pull Overgrown Weeds','current':count,'required':3,'is_complete':False}]}],
        'reference_knowledge':{'quests':{'66788':{'objectives':[
            {'objective_id':427985,'order':1,'description':'Pull Overgrown Weeds',
             'interaction_objects':[motion]}]}}},**changes}


def start(**kw):
    w = world()
    params = {'activation_source':'INTERACT_KEY','object_guid':GUID,'object_id':377265,
              'quest_ids':[66788],'objective_ids':['66788:1']}
    attempt = Attempt('use',Proposal.make('OBJECT_USE','pull weeds',params),w,'obs',1.,9.,(),
        Prediction('p','use','s',1.,9.,'obs'))
    active = ActiveSkillRuntime().start(intent=Intent('OBJECT_USE',params,None,'66788:1'),
        attempt=attempt,now=1.,before_snapshot=w)
    skill = ObjectUseSkill(bindings=kw.get('bindings',SimpleNamespace(contains=lambda x:True)),
        step_guard=kw.get('step_guard',lambda s:True))
    result = skill.begin(active,w)
    assert result.commands and result.commands[0].binding == 'INTERACTTARGET'
    return skill,active


def test_plant_text_plus_exact_goober_pull_spell_is_required():
    assert motion_for_template('Pull Overgrown Weeds',TEMPLATE,'Pulling Weeds')['object_id'] == 377265
    for text,template,spell in [('Pull the lever',TEMPLATE,'Pulling Weeds'),
            ('Burn Overgrown Weeds',TEMPLATE,'Pulling Weeds'),
            ('Pull Overgrown Weeds',TEMPLATE,'Opening'),
            ('Pull Overgrown Weeds',{**TEMPLATE,'name':'Poisonous Weeds'},'Pulling Weeds')]:
        assert motion_for_template(text,template,spell) is None


def test_one_use_then_backwards_after_grab_stops_only_on_this_objectives_credit():
    skill,active = start()
    assert not skill.verify(active,world(1.5),1.5).commands
    assert not skill.verify(active,world(2.,is_casting=True),2.).commands
    pulled = skill.verify(active,world(3.,soft_targets=[]),3.)
    assert pulled.status is SkillStatus.RUNNING
    assert [(c.binding,c.duration) for c in pulled.commands] == [('MOVEBACKWARD',.3)]
    assert pulled.metadata['identity_check'] == 'POST_USE_PINNED_OBJECT_MOVEMENT'
    assert not skill.verify(active,world(3.1,x=-.9),3.1).commands
    sibling = world(3.5,x=-1.)
    sibling['active_quests'][0]['objectives'][0]['current'] = 1
    assert skill.verify(active,sibling,3.5).status is SkillStatus.RUNNING
    credit = skill.verify(active,world(4.,x=-2.,count=1),4.)
    assert credit.status is SkillStatus.SUCCESS and not credit.commands


@pytest.mark.parametrize('change',[{'is_in_combat':True},{'session_id':'other'},{'is_mounted':True}])
def test_pull_yields_without_another_step_when_its_context_changes(change):
    skill,active=start()
    result = skill.verify(active,world(5.,**change),5.)
    assert result.status is SkillStatus.CANCELLED and not result.commands


def test_lost_guid_and_missing_movement_binding_or_surface_never_move():
    skill,active=start()
    gone=world(5.);gone['packet_entities'][GUID]['removed']={'reason':'OUT_OF_RANGE'}
    assert not skill.verify(active,gone,5.).commands
    for kw in [{'bindings':None},{'step_guard':lambda s:False}]:
        skill,active=start(**kw)
        result=skill.verify(active,world(5.),5.)
        assert result.status is SkillStatus.BLOCKED and not result.commands


def test_no_displacement_is_bounded_and_no_f7_retry_is_mixed_with_the_pull():
    skill,active=start()
    results=[skill.verify(active,world(t),t) for t in [5.,5.5,6.,6.5]]
    assert results[-1].status is SkillStatus.FAILURE
    assert results[-1].metadata['reason']=='object_pull_no_displacement'
    assert all(c.binding=='MOVEBACKWARD' for r in results for c in r.commands)


def test_exact_fresh_pull_channel_allows_movement_but_other_and_stale_casts_hold():
    from wowbot.skills.object_pull import channel_movement_allowed
    skill,active=start()
    for spell,at in [(22810,2.),(375531,.5)]:
        sample=world(2.,is_casting=True,combat_hint={'channel_spell_id':spell,'channel_at':at})
        assert not channel_movement_allowed(active,sample,2.)
        assert not skill.verify(active,sample,2.).commands
    sample=world(2.2,is_casting=True,combat_hint={'channel_spell_id':375531,'channel_at':2.2})
    assert channel_movement_allowed(active,sample,2.2)
    result=skill.verify(active,sample,2.2)
    assert result.commands[0].binding=='MOVEBACKWARD'


def test_removed_object_after_pulling_waits_briefly_for_credit_without_any_input():
    skill,active=start()
    assert skill.verify(active,world(5.),5.).commands
    gone=world(5.5);gone['packet_entities'][GUID]['removed']={'reason':'DESTROYED'}
    assert skill.verify(active,gone,5.5).status is SkillStatus.RUNNING
    assert not skill.verify(active,gone,6.).commands
    gone['active_quests'][0]['objectives'][1]['current']=1
    assert skill.verify(active,gone,6.1).status is SkillStatus.SUCCESS


def test_pull_channel_passes_the_shared_fast_lane_cast_hold():
    from wowbot.agent.engine import AutonomousAgent
    from wowbot.agent.executor import RecordingExecutor
    from wowbot.agent.models import Observation,Mode
    skill,active=start()
    executor=RecordingExecutor();agent=AutonomousAgent(executor)
    base=world();agent.world.ingest(Observation.create(base,1.));agent.set_mode(Mode.FULL_AI)
    agent.pending=active.attempt
    agent.active_skill.state.skill_context.update(active.skill_context)
    # Dispatcher adapters were bound at construction, so replace its concrete
    # shared object's dependencies instead of installing another controller.
    agent.object_use_skill.bindings=skill.bindings;agent.object_use_skill.step_guard=skill.step_guard
    agent.parallel_control.enabled=True
    sample=world(2.,is_casting=True,combat_hint={'channel_spell_id':375531,'channel_at':2.},
        frame_id='channel:2',telemetry_lane='FAST_STATE')
    result=agent.parallel_control.tick(sample,2.,None,2.)
    assert result['consumed']
    assert any(c.binding=='MOVEBACKWARD' for c in executor.commands)


def test_catalog_keeps_latest_template_instead_of_reviving_an_old_supported_spell(monkeypatch):
    from wowbot.quests.client_supplement import ClientSupplement
    monkeypatch.setattr(ClientSupplement,'record',lambda self,t,i:{'Name_lang':'Pulling Weeds' if i==375531 else 'Opening'})
    raw=SimpleNamespace(tables={'gameobject_template'},rows=lambda *a:[
        {**TEMPLATE,'VerifiedBuild':46801},{**TEMPLATE,'Data10':22810,'VerifiedBuild':70575}])
    assert TDBKnowledgeProvider(SimpleNamespace(raw=raw)).object_motions('Pull Overgrown Weeds') == []


class Floor:
    def __init__(self,mode='flat'):self.mode=mode
    def project_position(self,instance,point):
        if self.mode=='unknown':return None
        return {**point,'z':point['z']-(10. if self.mode=='drop' else 0.)}
    def find_path(self,instance,start,end):
        if self.mode in {'wall','unknown'}:return None
        return NavMeshPath((start,{**end,'z':end['z']-(10. if self.mode=='drop' else 0.)}),1,1,1.)


@pytest.mark.parametrize('mode,allowed',[('flat',True),('drop',False),('unknown',False),('wall',False)])
def test_backward_step_uses_the_canonical_geometry_and_rejects_drop_unknown_and_wall(mode,allowed):
    nav=NavigationService(navmesh=Floor(mode))
    assert nav.object_pull_step_safe(world()) is allowed
