"""Quest structure reaches canonical consumers without inventing quest state."""
from types import SimpleNamespace
import struct

import pytest

from wowbot.agent.models import Observation
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.packetio.pkt import PktV31StreamParser
from test_packet_agent_bridge import addon, bridge, deliver
from test_packet_codecs import decoded, pkt_bytes
from test_packet_quest_definition_20261030 import definition_bytes
from test_native_quest_log_20261030 import send, slot
from test_packet_continuity_20261030 import connected


def setup(bridge, *, objectives=None, **changes):
    rows = [{'objective_id':'58915:0', 'description':'0/7 Free the cocoons.',
             'type':'INTERACT', 'current':0, 'required':7, 'is_complete':False}]
    bridge.world.ingest(Observation.create(addon(game_build='70575',
        active_quests=[{'quest_id':58915, 'title':'Current quest', 'is_complete':False,
                       'objectives': rows if objectives is None else objectives}], **changes), 9.1))
    bridge.adapter.observations(None,bridge.world,10.)


def definition(bridge, *, at=10., decoder=None, **options):
    bridge.inbox._clock=lambda:at
    bridge.inbox._wall_clock=lambda:1000.+at-10.
    body=definition_bytes(**options)
    if decoder is None:
        value=decoded('SMSG_QUERY_QUEST_INFO_RESPONSE',body,build=70575,timestamp=1000.+at-10.)[-1]
    else:
        parser=PktV31StreamParser()
        record=parser.feed(pkt_bytes('SMSG_QUERY_QUEST_INFO_RESPONSE',body,build=70575,
                                    timestamp=1000.+at-10.))[0]
        value=decoder.decode_all(record)[-1]
    deliver(bridge,value,at=at)
    return value


def objective(bridge):
    return bridge.world.quest_model.records[58915].objectives[0]


def test_definition_does_not_create_active_quest_accept_reward_actor_or_input_liveness(bridge):
    setup(bridge,objectives=[])
    definition(bridge,quest_id=99999)
    result=bridge.world.query.quest_definition(99999,10.)
    assert result['status']=='OBSERVED_REFERENCE'
    assert 99999 not in bridge.world.quest_model.records
    assert not bridge.world.state.get('target') and bridge.world.last_received==9.1
    assert not any(e.event_type in {'QUEST_ACCEPTED','QUEST_TURNED_IN','QUEST_COMPLETED'}
                   for e in bridge.world.event_records)
    result['definition']['objectives'][0]['object_id']=999
    assert bridge.world.query.quest_definition(99999,10.)['definition']['objectives'][0]['object_id']==301000


def test_exact_quest_text_binds_native_id_and_storage_without_ui_ordinal_or_actor_guess(bridge):
    setup(bridge)
    definition(bridge)
    row=objective(bridge)
    assert row.raw['server_objective_id']==100040 and row.raw['server_storage_index']==9
    assert row.raw['server_credit_object_id']==301000
    assert row.target_object is None and row.target_entity is None
    assert row.current_count==0 and row.completion_state=='IN_PROGRESS'
    assert bridge.world.quest_model.records[58915].current_state=='ACTIVE'
    assert bridge.world.state['server_quest_objectives']['58915']['58915:0']['server_objective_id']==100040


@pytest.mark.parametrize('rows',[
    [{'objective_id':'58915:0','description':'','type':'INTERACT'}],
    [{'objective_id':'58915:0','quest_objective_id':999,'description':'Free the cocoons.'}],
    [{'objective_id':'58915:0','description':'Free the cocoons.'},
     {'objective_id':'58915:1','description':'Free the cocoons.'}],
])
def test_blank_duplicate_or_explicitly_conflicting_objectives_remain_unbound(bridge,rows):
    setup(bridge,objectives=rows)
    definition(bridge)
    assert all('server_objective_id' not in o.raw for o in bridge.world.quest_model.records[58915].objectives)
    assert 'server_quest_objectives' not in bridge.world.state


def test_explicit_global_id_can_bind_a_localized_objective_and_survives_state_refresh(bridge):
    rows=[{'objective_id':'58915:0','quest_objective_id':100040,'description':'Szabadítsd ki őket!'}]
    setup(bridge,objectives=rows)
    definition(bridge)
    assert objective(bridge).raw['server_storage_index']==9
    bridge.world.quest_model.ingest(bridge.world.addon_state['active_quests'],'new-state',10.2)
    assert objective(bridge).raw['server_objective_id']==100040


def test_replaced_or_missing_definition_clears_bindings_but_never_completes_the_quest(bridge):
    setup(bridge);definition(bridge)
    definition(bridge,objective_id=100050,at=10.1)
    assert objective(bridge).raw['server_objective_id']==100050
    definition(bridge,objective_id=100040,at=10.05)
    assert objective(bridge).raw['server_objective_id']==100050  # out-of-order old response
    definition(bridge,has_data=False,at=10.2)
    assert 'server_objective_id' not in objective(bridge).raw
    assert bridge.world.query.quest_definition(58915,10.2)['status']=='UNAVAILABLE'
    assert bridge.world.quest_model.records[58915].current_state=='ACTIVE'


@pytest.mark.parametrize('change',[{'character_guid':'Player-1602-9999'},
                                   {'game_build':'70448'},{'session_id':'new'}, {'loading':True}])
def test_identity_build_session_and_loading_suspend_definition_use(bridge,change):
    setup(bridge);definition(bridge)
    value={**bridge.world.addon_state, **change, 'frame_id':'new-scope', 'timestamp':10.1,'monotonic_time':10.1}
    bridge.world.ingest(Observation.create(value,10.1))
    assert bridge.world.query.quest_definition(58915,10.1)['status']=='UNKNOWN'
    assert 'server_objective_id' not in objective(bridge).raw


def test_world_and_phase_changes_keep_reference_origin_but_expiry_does_not_rejuvenate_it(bridge):
    setup(bridge);definition(bridge)
    value={**bridge.world.addon_state, 'frame_id':'other-map', 'map_id':1410,'phase':'new-phase',
           'player_world_position':{**bridge.world.addon_state['player_world_position'],'instance_id':2444}}
    bridge.world.ingest(Observation.create(value,10.1))
    result=bridge.world.query.quest_definition(58915,10.1)
    assert result['status']=='OBSERVED_REFERENCE' and result['sample_time']==10.
    assert bridge.world.query.quest_definition(58915,1810.1)['status']=='UNKNOWN'
    bridge.world.ingest(Observation.create({**value,'frame_id':'later'},1810.1))
    assert 'server_objective_id' not in objective(bridge).raw


def test_storage_join_uses_definition_storage_nine_and_never_promotes_count_to_completion(bridge):
    setup(bridge);definition(bridge)
    progress=[99]*24;progress[9]=4
    send(bridge,[slot(3,58915,progress)],at=10.1)
    value=bridge.world.query.quest_objective_storage(58915,100040,10.1)
    assert value['status']=='OBSERVED_STORAGE' and value['value']==4 and value['storage_index']==9
    assert value['sample_time']==10.1 and value['definition_sample_time']==10.
    assert value['complete'] is None and objective(bridge).current_count==0
    assert bridge.world.query.quest_objective_storage(58915,100041,10.1)['status']=='UNKNOWN'
    assert bridge.world.query.quest_objective_storage(58915,100040,12.2)['status']=='UNKNOWN'


def test_real_location_policy_selects_exact_native_poi_despite_different_visible_index(bridge):
    setup(bridge);definition(bridge)
    # Native objective 100040 is blob/objective index 9; UI displays it first.
    body=struct.pack('<IIiI',1,1,58915,1)
    body+=struct.pack('<12iI',0,9,100040,0,2175,1409,0,0,0,0,0,0,1)
    body+=struct.pack('<hhh',80,100,3)+b'\0'
    deliver(bridge,decoded('SMSG_QUEST_POI_QUERY_RESPONSE',body,build=70575)[-1])
    obj=objective(bridge)
    assert len(bridge.world.query.quest_objective_pois(58915,obj,10.))==1
    record=bridge.world.quest_model.records[58915]
    proposals=QuestLocationPlanningPolicy().propose_objective(bridge.world,obj,record,'58915')
    assert proposals and proposals[0].skill=='MOVE'
    assert proposals[0].parameters['source']=='PACKET_QUEST_POI'
    assert proposals[0].parameters['x']==80. and proposals[0].parameters['y']==100.
    from wowbot.agent.quest_runtime import QuestExecutionRuntime
    primary=QuestExecutionRuntime().observe(SimpleNamespace(domain='QUEST',parameters={'quest_id':58915}),
        bridge.world.quest_model,bridge.world.state,10.,
        objective_pois=bridge.world.query.quest_objective_pois)
    assert primary.location_status=='SEARCH_AREA' and 'PACKET_QUEST_POI' in primary.evidence


def test_stream_gap_suspends_reference_and_cannot_reuse_poi_before_projection(bridge):
    provider,decoder,baseline,_=connected(bridge)
    definition(bridge,decoder=decoder)
    assert bridge.world.query.quest_definition(58915,10.)['status']=='OBSERVED_REFERENCE'
    provider.invalidate('stream_gap')
    assert bridge.world.query.quest_definition(58915,10.)['status']=='UNKNOWN'
    assert bridge.world.query.quest_pois(58915,10.)==()
    assert provider.accept_baseline(baseline.to_dict())
    # Structure can remain observed reference; old progress and geometry
    # cannot regain current-state authority with the same logical context.
    assert bridge.world.query.quest_definition(58915,10.)['status']=='OBSERVED_REFERENCE'
    assert bridge.world.query.quest_objective_storage(58915,100040,10.)['status']=='UNKNOWN'


def test_current_native_objective_relation_supersedes_a_different_static_credit_id():
    from wowbot.agent.quest_target_context import physical_target_problem
    guid='Creature-0-1-2175-1-222-00001'
    state={'active_quests':[{'quest_id':58915,'objectives':[{'objective_id':'58915:0',
        'description':'Talk to the keeper','target_entity':{'npc_id':123}}]}],
        'reference_knowledge':{'quests':{'58915':{'objectives':[{'objective_id':100039,
            'description':'Talk to the keeper'}]}}},
        'server_quest_objectives':{'58915':{'58915:0':{'server_objective_id':100040}}},
        'packet_entities':{guid:{'info':{'quest_objective_id':100039}}}}
    params={'quest_id':58915,'objective_id':'58915:0'}
    wanted={'guid':guid,'npc_id':222}
    assert physical_target_problem('TALK',params,wanted,state)=='QUEST_PHYSICAL_TARGET_ROLE_MISMATCH'
    state['packet_entities'][guid]['info']['quest_objective_id']=100040
    assert physical_target_problem('TALK',params,wanted,state) is None
