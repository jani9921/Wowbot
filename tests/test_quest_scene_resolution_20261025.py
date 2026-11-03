"""General source chains, ambiguity and no-guess behavior; no game input."""
import json
from pathlib import Path
import sqlite3

import pytest

from wowbot.quests.client_catalog import ClientCatalog
from wowbot.quests.scene_resolver import index_relations
from wowbot.quests.scene_path_planning import QuestScenePathPolicy

QUEST = 991234  # Deliberately not one of the four reviewed exceptions.
SCRIPT = '''scene:SetRelativeCoords(false)
pathID=30
laps=1
RingHitDistance=10
currentCheckpoint=1
rings=scene:LoadPath(pathID).nodes
maxCheckpoints=#rings
scene:TriggerServerEvent("Checkpoint")
scene:TriggerServerEvent("RaceComplete")'''


@pytest.fixture
def inputs(tmp_path):
    client, world = tmp_path/'client.sqlite3', tmp_path/'world.sqlite3'
    with sqlite3.connect(client) as db:
        db.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE db2_rows(table_name TEXT,id INTEGER,record_json TEXT,PRIMARY KEY(table_name,id));
            CREATE TABLE spell_effects(id INTEGER PRIMARY KEY,spell_id INTEGER,effect INTEGER,aura INTEGER,
                trigger_spell INTEGER,difficulty_id INTEGER,misc1 INTEGER,misc2 INTEGER);
            CREATE TABLE scene_paths(package_id INTEGER,path_id INTEGER,script_id INTEGER,source_member_id INTEGER);
            CREATE TABLE scene_scripts(package_id INTEGER,script_id INTEGER,source_member_id INTEGER);
            CREATE TABLE path_nodes(id INTEGER,path_id INTEGER,sequence INTEGER,location_id INTEGER);
            CREATE TABLE locations(id INTEGER,x REAL,y REAL,z REAL,rot_json TEXT);
            CREATE TABLE quest_routes(quest_id INTEGER PRIMARY KEY,status TEXT,route_json TEXT);
            CREATE TABLE quest_links(quest_id INTEGER,table_name TEXT,record_id INTEGER);
            CREATE TABLE poi_blobs(id INTEGER,quest_id INTEGER,map_id INTEGER,ui_map_id INTEGER);
            CREATE TABLE poi_points(id INTEGER,blob_id INTEGER,x REAL,y REAL,z REAL);''')
        for package in (90,91):
            db.execute('INSERT INTO db2_rows VALUES (?,?,?)',('SceneScriptPackage',package,json.dumps({'ID':package})))
        db.execute('INSERT INTO db2_rows VALUES (?,?,?)',('SceneScriptText',300,json.dumps({'ID':300,'Script':SCRIPT})))
        db.execute('INSERT INTO db2_rows VALUES (?,?,?)',('QuestV2',QUEST,json.dumps({'ID':QUEST})))
        db.execute('INSERT INTO quest_links VALUES (?,?,?)',(QUEST,'QuestV2',QUEST))
        db.execute('INSERT INTO scene_scripts VALUES (90,300,1)')
        db.execute('INSERT INTO scene_paths VALUES (90,30,300,1)')
        for i in range(3):
            db.execute('INSERT INTO path_nodes VALUES (?,?,?,?)',(i+1,30,i,i+1))
            db.execute('INSERT INTO locations VALUES (?,?,?,?,?)',(i+1,i*10.,0.,20.-i*10.,'[0,0,0]'))
        db.execute('INSERT INTO spell_effects VALUES (1,100,198,0,0,0,700,0)')
    with sqlite3.connect(world) as db:
        db.executescript('''CREATE TABLE scene_template(SceneId INTEGER,ScriptPackageID INTEGER);
            INSERT INTO scene_template VALUES(700,90),(701,91);
            CREATE TABLE quest_template(ID INTEGER PRIMARY KEY,LogTitle TEXT);
            CREATE TABLE quest_template_addon(ID INTEGER,SourceSpellID INTEGER);
            CREATE TABLE quest_objectives(ID INTEGER,QuestID INTEGER,Amount INTEGER,ObjectID INTEGER,Description TEXT);
            CREATE TABLE quest_poi(QuestID INTEGER,MapID INTEGER);
            CREATE TABLE smart_scripts(source_type INTEGER,entryorguid INTEGER,id INTEGER,link INTEGER,
                event_type INTEGER,event_param1 INTEGER,action_type INTEGER,action_param1 INTEGER,event_chance INTEGER DEFAULT 100,
                event_phase_mask INTEGER DEFAULT 0,event_flags INTEGER DEFAULT 0,target_type INTEGER DEFAULT 7);
            CREATE TABLE spell_area(spell INTEGER,quest_start INTEGER,quest_start_status INTEGER);
            CREATE TABLE conditions(SourceTypeOrReferenceId INTEGER,SourceEntry INTEGER,
                ConditionTypeOrReference INTEGER,ConditionValue1 INTEGER,NegativeCondition INTEGER);''')
        db.execute('INSERT INTO quest_template VALUES (?,?)',(QUEST,'Data-defined ring lesson'))
        db.execute('INSERT INTO quest_template_addon VALUES (?,100)',(QUEST,))
        db.execute('INSERT INTO quest_objectives VALUES (1,?,2,123,?)',(QUEST,'Fly through the rings'))
        db.execute('INSERT INTO quest_objectives VALUES (2,?,1,124,?)',(QUEST,'Target Area'))
        db.execute('INSERT INTO quest_poi VALUES (?,42)',(QUEST,))
    return client,world


def run(inputs):
    client,world = inputs
    before = world.read_bytes()
    with sqlite3.connect(client) as db:
        index_relations(db,world)
    assert world.read_bytes() == before
    return ClientCatalog(client)


def test_fifth_quest_resolves_and_enters_shared_movement_without_manual_binding(inputs):
    catalog = run(inputs)
    course = catalog.courses()[str(QUEST)]
    assert course['scene_package']==90 and course['path_id']==30
    assert course['association_kind']=='TDB_DB2_STRUCTURAL_REFERENCE'
    assert len(course['rings'])==2
    resolution=catalog.scene_resolution(QUEST,details=True)
    assert resolution['status']=='RESOLVED_REFERENCE' and resolution['route_status']=='REFERENCE_READY'
    assert resolution['candidates'][0]['evidence']['root']['table']=='quest_template_addon'
    state={'is_mounted':True,'player_world_position':{'instance_id':42},'active_quests':[
        {'quest_id':QUEST,'objectives':[{'description':'0/2 Fly through the rings','required':2}]}]}
    proposal=QuestScenePathPolicy(catalog).propose(state)[0]
    assert proposal.skill=='MOVE' and len(proposal.parameters['flight_path']['waypoints'])==2


@pytest.mark.parametrize('effect,aura,misc,kind',[(6,430,700,'AURA_PLAY_SCENE'),(195,0,90,'PLAY_SCENE_PACKAGE')])
def test_aura_scene_and_direct_package_are_typed_edges_not_numeric_guesses(inputs,effect,aura,misc,kind):
    with sqlite3.connect(inputs[0]) as db:
        db.execute('UPDATE spell_effects SET effect=?,aura=?,misc1=?',(effect,aura,misc))
    catalog=run(inputs)
    row=catalog.scene_resolution(QUEST,details=True)['candidates'][0]
    assert row['package_id']==90 and row['evidence']['edge']['kind']==kind


def test_missing_scene_template_never_assumes_scene_id_equals_package_id(inputs):
    with sqlite3.connect(inputs[0]) as db:
        db.execute('UPDATE spell_effects SET misc1=90')
    catalog=run(inputs)
    result=catalog.scene_resolution(QUEST)
    assert result['status']=='UNRESOLVED' and result['reason']=='MISSING_SCENE_TEMPLATE'
    assert result['package_ids']==[] and catalog.courses()=={}


def test_trigger_cycle_is_bounded_and_keeps_the_witness_chain(inputs):
    with sqlite3.connect(inputs[0]) as db:
        db.execute('UPDATE spell_effects SET spell_id=101')
        db.executemany('INSERT INTO spell_effects VALUES (?,?,?,?,?,?,?,?)',[
            (2,100,64,0,101,0,0,0),(3,101,64,0,100,0,0,0)])
    catalog=run(inputs)
    result=catalog.scene_resolution(QUEST,details=True)
    assert result['candidate_count']==1 and result['package_ids']==[90]
    assert result['candidates'][0]['evidence']['spell_chain'][0]['trigger_spell']==101
    assert result['route_status']=='REQUIRES_LIVE_SCENE_OR_CONDITION_RESOLUTION'
    assert not catalog.courses()


def smart(inputs,event=19,action=134,argument=100):
    with sqlite3.connect(inputs[1]) as db:
        db.execute('DELETE FROM quest_template_addon')
        db.execute('INSERT INTO smart_scripts(source_type,entryorguid,id,link,event_type,event_param1,action_type,action_param1) VALUES (0,200,0,0,?,?,?,?)',
                   (event,QUEST,action,argument))


def test_accepted_quest_smart_cast_is_resolved(inputs):
    smart(inputs)
    catalog=run(inputs)
    assert catalog.scene_resolution(QUEST)['package_ids']==[90]
    assert catalog.courses()[str(QUEST)]['association_kind']=='TDB_DB2_STRUCTURAL_REFERENCE'


def test_reward_scene_is_reference_only_and_does_not_start_flight_for_unfinished_quest(inputs):
    smart(inputs,event=20)
    catalog=run(inputs)
    assert catalog.scene_resolution(QUEST)['candidates'][0]['phase']=='ON_REWARD'
    assert not catalog.courses()


def test_timed_action_list_and_link_preserve_two_different_scenes_as_ambiguous(inputs):
    smart(inputs,action=80,argument=500)
    with sqlite3.connect(inputs[0]) as db:
        db.execute('INSERT INTO spell_effects VALUES (2,101,198,0,0,0,701,0)')
    with sqlite3.connect(inputs[1]) as db:
        db.executescript('''INSERT INTO smart_scripts(source_type,entryorguid,id,link,event_type,event_param1,action_type,action_param1)
            VALUES(9,500,0,1,0,0,85,100),(9,500,1,0,61,0,85,101);''')
    catalog=run(inputs)
    result=catalog.scene_resolution(QUEST,details=True)
    assert result['status']=='AMBIGUOUS' and result['package_ids']==[90,91]
    assert result['candidate_count']==2 and not catalog.courses()


def test_quest_owned_smart_scene_play_uses_scene_template(inputs):
    with sqlite3.connect(inputs[1]) as db:
        db.execute('DELETE FROM quest_template_addon')
        db.execute('INSERT INTO smart_scripts(source_type,entryorguid,id,link,event_type,event_param1,action_type,action_param1) VALUES (5,?,0,0,47,0,129,700)',(QUEST,))
    assert run(inputs).scene_resolution(QUEST)['package_ids']==[90]


@pytest.mark.parametrize('negative,expected',[(0,1),(1,0)])
def test_positive_and_negated_quest_spell_conditions_are_distinguished(inputs,negative,expected):
    with sqlite3.connect(inputs[1]) as db:
        db.execute('DELETE FROM quest_template_addon')
        db.execute('INSERT INTO conditions VALUES (17,100,9,?,?)',(QUEST,negative))
    catalog=run(inputs)
    assert catalog.scene_resolution(QUEST)['candidate_count']==expected
    assert not catalog.courses()  # Other condition predicates have not been live-evaluated.


def test_unrelated_creature_cast_and_any_quest_zero_are_not_quest_relations(inputs):
    smart(inputs,event=0)
    with sqlite3.connect(inputs[1]) as db:
        db.execute('UPDATE smart_scripts SET event_type=19,event_param1=0')
    result=run(inputs).scene_resolution(QUEST)
    assert result['seed_count']==0 and result['reason']=='NO_EXPLICIT_QUEST_SOURCE_RELATION'


def test_conditional_area_aura_is_resolved_without_dropping_its_conditions(inputs):
    with sqlite3.connect(inputs[1]) as db:
        db.execute('DELETE FROM quest_template_addon')
        db.execute('INSERT INTO spell_area VALUES (100,?,8)',(QUEST,))
    result=run(inputs).scene_resolution(QUEST,details=True)
    assert result['package_ids']==[90] and result['candidates'][0]['conditional']
    assert result['candidates'][0]['evidence']['root']['record']['quest_start_status']==8


@pytest.mark.parametrize('change,reason',[
    ('relative','UNSUPPORTED_SCENE_MECHANIC'),('laps','AMBIGUOUS_LAP_CONFIGURATION'),
    ('path','NO_UNIQUE_PATH'),('geometry','INCOMPLETE_PATH_GEOMETRY')])
def test_scene_reference_does_not_make_unknown_geometry_or_mechanics_executable(inputs,change,reason):
    with sqlite3.connect(inputs[0]) as db:
        if change in {'relative','laps'}:
            text=SCRIPT.replace('false','true') if change=='relative' else SCRIPT+'\nlaps=2'
            db.execute('UPDATE db2_rows SET record_json=? WHERE table_name=?',(json.dumps({'Script':text}),'SceneScriptText'))
        elif change=='path':
            db.execute('INSERT INTO scene_paths VALUES (90,31,300,1)')
        else:
            db.execute('DELETE FROM locations WHERE id=2')
    catalog=run(inputs)
    assert catalog.scene_resolution(QUEST)['route_status']==reason
    assert not catalog.courses()


def test_db2_quest_condition_reference_resolves_without_any_tdb_quest_spell_link(inputs):
    with sqlite3.connect(inputs[1]) as db:
        db.execute('DELETE FROM quest_template_addon')
    with sqlite3.connect(inputs[0]) as db:
        condition={'ID':555,'CurrQuestID':[QUEST,0,0,0],'CurrQuestLogic':0,'MinLevel':20}
        text=SCRIPT+'\nif scene:EvalPlayerCondition(555) then pathID=30 end'
        db.execute('INSERT INTO db2_rows VALUES (?,?,?)',('PlayerCondition',555,json.dumps(condition)))
        db.execute('UPDATE db2_rows SET record_json=? WHERE table_name=?',(json.dumps({'Script':text}),'SceneScriptText'))
    catalog=run(inputs)
    resolution=catalog.scene_resolution(QUEST,details=True)
    assert resolution['status']=='RESOLVED_REFERENCE' and resolution['package_ids']==[90]
    assert resolution['candidates'][0]['evidence']['root']['table']=='PlayerCondition'
    assert resolution['candidates'][0]['evidence']['root']['record']['MinLevel']==20
    assert any(p['condition_id']==555 for p in catalog.scene(90)['path_candidates'])
    assert not catalog.courses()  # MinLevel/condition logic has not been verified live.


def test_previously_completed_quest_in_client_condition_is_not_current_quest_authority(inputs):
    with sqlite3.connect(inputs[1]) as db:
        db.execute('DELETE FROM quest_template_addon')
    with sqlite3.connect(inputs[0]) as db:
        db.execute('INSERT INTO db2_rows VALUES (?,?,?)',('PlayerCondition',555,json.dumps({'ID':555,'PrevQuestID':[QUEST,0]})))
        db.execute('UPDATE db2_rows SET record_json=? WHERE table_name=?',(
            json.dumps({'Script':SCRIPT+'\nif scene:EvalPlayerCondition(555) then pathID=30 end'}),'SceneScriptText'))
    catalog=run(inputs)
    assert catalog.scene_resolution(QUEST)['candidates'][0]['phase']=='AFTER_QUEST'
    assert not catalog.courses()


def test_resolving_again_publishes_a_closed_new_client_file_and_keeps_both_sources(inputs,tmp_path):
    from tools.resolve_client_scenes import resolve_catalog
    client,world=inputs
    run(inputs)
    original_client, original_world=client.read_bytes(),world.read_bytes()
    output=tmp_path/'refreshed.sqlite3'
    resolve_catalog(client,output,world)
    assert ClientCatalog(output).courses()[str(QUEST)]['scene_package']==90
    renamed=tmp_path/'closed-file-can-be-renamed.sqlite3'
    output.rename(renamed)
    assert client.read_bytes()==original_client and world.read_bytes()==original_world


def test_npc_casting_player_only_scene_spell_is_not_automatic_flight_authority(inputs):
    smart(inputs,action=11)
    catalog=run(inputs)
    assert catalog.scene_resolution(QUEST)['candidates'][0]['conditional']
    assert not catalog.courses()


def condition_table(inputs, *, selector=True):
    with sqlite3.connect(inputs[1]) as db:
        db.execute('DELETE FROM quest_template_addon')
    with sqlite3.connect(inputs[0]) as db:
        db.execute('INSERT INTO db2_rows VALUES (?,?,?)',('PlayerCondition',555,json.dumps({'ID':555,'CurrQuestID':[QUEST]})))
        db.execute('INSERT INTO db2_rows VALUES (?,?,?)',('PlayerCondition',556,json.dumps({'ID':556,'CurrQuestID':[QUEST+1]})))
        text='''routes = { [555]={pathID=30,}, [556]={pathID=31,}, }
            for condition, info in pairs(routes) do
                if scene:EvalPlayerCondition(condition) then pathID=info.pathID end
            end'''
        if not selector:
            text=text[:text.index('for condition')]
        db.execute('UPDATE db2_rows SET record_json=? WHERE table_name=?',(json.dumps({'Script':text}),'SceneScriptText'))


def test_condition_keyed_path_table_selects_only_its_quest_path_without_hardcoded_ids(inputs):
    condition_table(inputs)
    catalog=run(inputs)
    result=catalog.scene_resolution(QUEST,details=True)
    assert result['path_ids']==[30] and result['unique_path_id']==30
    assert result['path_reference']['node_count']==3
    assert result['path_reference']['geometry_complete']
    assert result['candidates'][0]['evidence']['path_table_proof'][0]['table_name']=='routes'
    assert catalog.scene_resolution(QUEST+1)['path_ids']==[31]
    assert not catalog.courses()


def test_numeric_table_keys_are_not_assumed_player_conditions_without_a_matching_selector(inputs):
    condition_table(inputs,selector=False)
    assert run(inputs).scene_resolution(QUEST)['candidate_count']==0


def test_duplicate_condition_table_paths_remain_ambiguous_instead_of_last_value_winning(inputs):
    condition_table(inputs)
    with sqlite3.connect(inputs[0]) as db:
        raw=json.loads(db.execute("SELECT record_json FROM db2_rows WHERE table_name='SceneScriptText'").fetchone()[0])
        raw['Script']=raw['Script'].replace('[556]={pathID=31,}', '[555]={pathID=31,}')
        db.execute("UPDATE db2_rows SET record_json=? WHERE table_name='SceneScriptText'",(json.dumps(raw),))
    catalog=run(inputs)
    assert catalog.scene_resolution(QUEST)['path_ids']==[30,31]
    assert catalog.scene_resolution(QUEST)['unique_path_id'] is None
    assert not catalog.courses()
