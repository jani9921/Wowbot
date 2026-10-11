"""Offline contracts only: no WoW input, no claim of completed live quests."""
from copy import deepcopy
from types import SimpleNamespace
import sqlite3

import pytest
from test_reference_support_20261008 import raw_db, memory, state
from wowbot.agent.reference_catalog import ReferenceCatalog
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
from wowbot.agent.tdb_locations import (objective_region, role_region, geometry_points,
                                        objective_zone_contains_player)
from wowbot.agent.objective_locator import ObjectiveLocator
from wowbot.agent.turnin_resolver import TurnInResolver
from wowbot.agent.map_poi_planning import reachable_records


def snapshot(memory):
    s=state(); s['reference_knowledge']=memory.knowledge.snapshot(s,1)
    return s


def test_zero_height_is_unknown_not_sea_level(memory):
    s=snapshot(memory); s['reference_knowledge']['quests']['7']['pois'][0]['points'][0]['z']=0
    point=objective_region(s,7,SimpleNamespace(objective_id='7:0'))
    assert point['z_known'] is False and 'z' not in point and point['require_navmesh']


def test_primary_precedes_generic_api_waypoint_but_not_live_entity(memory):
    s=snapshot(memory)
    obj=SimpleNamespace(objective_id='7:0', target_entity={'npc_id':100},
                        target_location={'map_id':1409,'x':.9,'y':.9}, confidence=.9)
    record=SimpleNamespace(quest_id=7,known_locations=[])
    assert ObjectiveLocator().locate(obj,record,s).coordinates['source']=='TDB_REFERENCE_POI'
    s['target']={'guid':'Creature-live','npc_id':100}
    assert ObjectiveLocator().locate(obj,record,s).status.value=='LOCAL_ENTITY'


def test_available_api_quest_gets_tdb_starter_without_static_availability(memory):
    s=state(); s['active_quests']=[]
    s['map_pois']={'available_quests':[{'quest_id':7,'map_id':1409,'x':.2,'y':.3}]}
    s['reference_knowledge']=memory.knowledge.snapshot(s,1)
    assert s['reference_knowledge']['quests']['7']['live_status']=='AVAILABLE_API'
    rows=reachable_records(s,'available_quests')
    assert len(rows)==1 and rows[0][2]['reference_entry']==100 and rows[0][2]['x']==20
    s['map_pois']={}
    assert reachable_records(s,'available_quests')==[]


def test_explicit_ender_spawn_primary_but_open_dialog_still_wins(memory):
    s=snapshot(memory)
    r=s['reference_knowledge']['quests']['7']; r['spawn_candidates'][0]['role']='QUEST_ENDER'
    record=SimpleNamespace(quest_id=7,known_locations=[])
    assert TurnInResolver().locate(record,s).location['source']=='TDB_SPAWN'
    s['quest_ui']={'quest_id':7,'action':'TURN_IN'}
    assert TurnInResolver().locate(record,s).kind.value=='FIELD_UI'


def test_turnin_poi_not_objective_location(memory):
    s=snapshot(memory); r=s['reference_knowledge']['quests']['7']
    r['pois'][0].update(objective_index=-1,objective_id=0)
    assert role_region(s,7,'QUEST_ENDER')['source']=='TDB_REFERENCE_POI'
    assert objective_region(s,7,SimpleNamespace(objective_id='7:0')) is None


def test_blob_identity_and_point_builds_are_preserved(raw_db):
    with sqlite3.connect(raw_db) as db:
        db.executescript('''ALTER TABLE quest_poi ADD COLUMN BlobIndex INTEGER DEFAULT 0;
            ALTER TABLE quest_poi ADD COLUMN VerifiedBuild INTEGER DEFAULT 66384;
            ALTER TABLE quest_poi_points ADD COLUMN VerifiedBuild INTEGER DEFAULT 60822;
            INSERT INTO quest_poi VALUES(7,0,701,1,2175,1409,0,0,0,1,66384);''')
    c=ReferenceCatalog(raw_db)
    try:
        pois=c.quest(7)['pois']
        assert {p['poi_id'] for p in pois}=={'7:0:0','7:1:0'}
        assert all(p['shared_geometry_count']==2 and p['geometry_ambiguous'] for p in pois)
        assert all(p['points'][0]['verified_build']==60822 and p['verified_build']==66384 for p in pois)
        s=state();s['reference_knowledge']={'quests':{'7':c.quest(7)}}
        assert objective_region(s,7,SimpleNamespace(objective_id='7:0')) is None
    finally:
        c.close()


def test_polygon_is_interior_search_grid_not_vertex_route(memory):
    s=snapshot(memory); p=s['reference_knowledge']['quests']['7']['pois'][0]
    p['points']=[{'x':x,'y':y,'z':-10} for x,y in [(20,20),(40,20),(40,40),(20,40)]]
    region=objective_region(s,7,SimpleNamespace(objective_id='7:0'))
    assert region['region_source']=='TDB_POLYGON_CANDIDATE'
    assert len(region['coverage_points'])==25
    assert all(20<p['x']<40 and 20<p['y']<40 for p in region['coverage_points'])
    assert region['require_navmesh'] and not region['navigation_trusted']


@pytest.mark.parametrize('coords', [[], [(0,0),(1,1)], [(0,0),(2,2),(2,0),(0,2)]])
def test_invalid_geometry_is_not_routed(coords):
    assert geometry_points([{'x':x,'y':y,'z':10} for x,y in coords])==[]


def test_polygon_unknown_or_multiple_floors_abstains(memory):
    s=snapshot(memory); p=s['reference_knowledge']['quests']['7']['pois'][0]
    p['points']=[{'x':20,'y':20,'z':-10},{'x':40,'y':20,'z':-40},{'x':40,'y':40,'z':0}]
    assert objective_region(s,7,SimpleNamespace(objective_id='7:0')) is None


def test_live_poi_agreement_unlocks_exact_phase_unknown_object_spawns(memory):
    s = snapshot(memory)
    s['phase'] = None
    ref = s['reference_knowledge']['quests']['7']
    ref['pois'][0]['points'] = [
        {'x':20,'y':20,'z':140}, {'x':40,'y':20,'z':155},
        {'x':40,'y':40,'z':155}, {'x':20,'y':40,'z':140}]
    ref['spawn_candidates'] = [{
        'spawn_id': 42, 'entity_kind': 'GAMEOBJECT', 'entry': 9999,
        'role': 'OBJECTIVE', 'objective_id': 700, 'world_map_id': 2175,
        'x': 40., 'y': 20., 'z': 155., 'context': {'PhaseId': 15356}}]
    live = {'coordinate_space':'WORLD_YARDS','instance_id':2175,
            'map_id':1409,'x':30.,'y':30.}
    obj = SimpleNamespace(objective_id='7:0', target_location=live)
    region = objective_region(s, 7, obj)
    assert region['source'] == 'TDB_SPAWN' and region['x'] == 40.
    assert region['phase_unverified'] is True and region['require_navmesh']
    assert objective_zone_contains_player(s, 7, '7:0') is False
    s['player_world_position'].update(x=30., y=30., z=150.)
    assert objective_zone_contains_player(s, 7, '7:0') is True
    obj.target_location = {**live, 'x':200., 'y':200.}
    assert objective_region(s, 7, obj) is None
    obj.target_location = None
    assert objective_region(s, 7, obj) is None  # no live agreement, phase unknown
    s['phase'] = 15356
    assert objective_region(s, 7, obj)['source'] == 'TDB_SPAWN'


def test_tdb_route_ignores_unknown_visual_cues_until_quest_zone(memory):
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    from wowbot.agent.models import Proposal
    s = snapshot(memory)
    ref = s['reference_knowledge']['quests']['7']
    ref['pois'][0]['points'] = [
        {'x':20,'y':20,'z':140}, {'x':40,'y':20,'z':155},
        {'x':40,'y':40,'z':155}, {'x':20,'y':40,'z':140}]
    s['monotonic_time'] = 4.
    s['visual_candidates'] = [{
        'source':'WORLD3D', 'track_id':'passing-marker', 'inspectable':True,
        'stable_frames':5, 'lifecycle':'STABLE', 'observed_at':4.,
        'confidence':.8, 'candidate_labels':['quest_marker_like']}]
    move = SimpleNamespace(proposal=Proposal.make('MOVE', 'TDB object', {
        'purpose':'LOCATE_QUEST_OBJECTIVE_REGION', 'knowledge_priority':'PRIMARY_STATIC',
        'quest_id':7, 'objective_id':'7:0', 'objective_type':'USE_OBJECT',
        'instance_id':2175, 'x':40., 'y':20.}))
    assert movement_visual_interrupt(move, s) is None
    s['player_world_position'].update(x=22., y=38., z=150.)
    assert objective_zone_contains_player(s, 7, '7:0') is True
    assert movement_visual_interrupt(move, s) is None  # inside the broad zone, not at this totem
    s['player_world_position'].update(x=35., y=25.)
    assert movement_visual_interrupt(move, s)['track_id'] == 'passing-marker'


def test_live_yellow_dot_selects_matching_tdb_spawn_not_nearest_old_spot(memory, monkeypatch):
    import wowbot.agent.quest_location_planning as locations
    s = snapshot(memory)
    s['phase'] = None
    s['active_quests'][0]['objectives'][0]['current'] = 1
    ref = s['reference_knowledge']['quests']['7']
    ref['pois'][0]['points'] = [
        {'x':10,'y':10,'z':140}, {'x':50,'y':10,'z':155},
        {'x':50,'y':50,'z':155}, {'x':10,'y':50,'z':140}]
    ref['spawn_candidates'] = [{
        'spawn_id': i, 'entity_kind':'GAMEOBJECT', 'entry':9999,
        'role':'OBJECTIVE', 'objective_id':700, 'world_map_id':2175,
        'x':x, 'y':20., 'z':150., 'context':{'PhaseId':15356}}
        for i, x in [(1, 12.), (2, 48.)]]
    s['visual_candidates'] = [{'kind':'minimap_quest_dot'}]
    monkeypatch.setattr(locations, 'minimap_objective_dots',
                        lambda _state: [(48.5, 20.5, '7')])
    objective = SimpleNamespace(objective_id='7:0', target_location={
        'coordinate_space':'WORLD_YARDS','instance_id':2175,
        'map_id':1409,'x':30.,'y':30.})
    point = objective_region(s, 7, objective)
    assert point['x'] == 48. and point['objective_dot_correlated'] is True
    monkeypatch.setattr(locations, 'minimap_objective_dots',
                        lambda _state: [(200., 200., '7')])
    assert objective_region(s, 7, objective) is None  # no matching live dot
    s['visual_candidates'] = []
    assert objective_region(s, 7, objective) is None  # progress alone cannot identify the remaining spawn


def test_completed_live_objective_never_returns_a_tdb_destination(memory):
    s = snapshot(memory)
    objective = SimpleNamespace(objective_id='7:0', completion_state='ACTIVE')
    assert objective_region(s, 7, objective) is not None
    s['active_quests'][0]['objectives'][0]['is_complete'] = True
    assert objective_region(s, 7, objective) is None
    s['active_quests'][0]['objectives'][0]['is_complete'] = False
    objective.completion_state = 'COMPLETE'
    assert objective_region(s, 7, objective) is None


def test_live_giver_poi_mismatch_keeps_client_endpoint(memory):
    s = snapshot(memory)
    s['map_pois'] = {'available_quests':[{'quest_id':7,'map_id':1409,
        'world_position':{'coordinate_space':'WORLD_YARDS', 'instance_id':2175,
                          'x':150.,'y':150.}}]}
    rows = reachable_records(s, 'available_quests')
    assert rows[0][2]['x'] == 150. and rows[0][2].get('source') != 'TDB_SPAWN'


def test_live_turnin_poi_mismatch_keeps_client_endpoint(memory):
    s = snapshot(memory)
    s['reference_knowledge']['quests']['7']['spawn_candidates'][0]['role'] = 'QUEST_ENDER'
    live = {'source':'QUEST_API_WAYPOINT','map_id':1409,
            'world_position':{'coordinate_space':'WORLD_YARDS',
                              'instance_id':2175,'x':150.,'y':150.}}
    record = SimpleNamespace(quest_id=7, known_locations=[live])
    located = TurnInResolver().locate(record, s)
    assert located.location['x'] == 150.
    assert located.kind.value == 'QUEST_API_REGION'


def test_terrain_minus_one_default_does_not_hide_safe_spawn(memory):
    s=snapshot(memory); row=s['reference_knowledge']['quests']['7']['spawn_candidates'][0]
    row['context']={'PhaseId':0,'terrainSwapMap':-1,'spawnDifficulties':'0'}
    assert role_region(s,7,'QUEST_STARTER') is not None
    row['context']['PhaseId']=999
    assert role_region(s,7,'QUEST_STARTER') is None


def test_objective_credit_never_promoted_to_creature_identity(raw_db):
    with sqlite3.connect(raw_db) as db:
        db.execute('UPDATE quest_objectives SET Type=0,ObjectID=100')
    c=ReferenceCatalog(raw_db)
    try:
        p=TDBKnowledgeProvider(c);q=p.quest(7)
        assert q['objectives'][0]['credit_kind']=='CREATURE_CREDIT'
        assert 'npc_id' not in q['objectives'][0]
        assert all(r['role']!='OBJECTIVE' for r in p.quest_locations(q,state()))
    finally: c.close()


def test_object_template_item_sources_chain_and_services(raw_db):
    with sqlite3.connect(raw_db) as db:
        db.executescript('''CREATE TABLE gameobject_template(entry INTEGER,name TEXT,type INTEGER);
            INSERT INTO gameobject_template VALUES(9999,'Test Cocoon',10);
            CREATE TABLE gameobject(guid INTEGER,id INTEGER,map INTEGER,position_x REAL,position_y REAL,position_z REAL);
            INSERT INTO gameobject VALUES(80,9999,2175,60,70,-10);
            CREATE TABLE creature_questitem(CreatureEntry INTEGER,ItemId INTEGER);
            INSERT INTO creature_questitem VALUES(100,500);
            CREATE TABLE npc_vendor(entry INTEGER,item INTEGER,type INTEGER);
            INSERT INTO npc_vendor VALUES(200,500,1);
            CREATE TABLE quest_template_addon(ID INTEGER,PrevQuestID INTEGER,NextQuestID INTEGER,ExclusiveGroup INTEGER);
            INSERT INTO quest_template_addon VALUES(7,6,8,-5);
            CREATE TABLE creature_template_gossip(CreatureID INTEGER,MenuID INTEGER);
            INSERT INTO creature_template_gossip VALUES(100,50);
            CREATE TABLE gossip_menu_option(MenuID INTEGER,OptionID INTEGER,OptionText TEXT);
            INSERT INTO gossip_menu_option VALUES(50,1,'Continue');''')
    c=ReferenceCatalog(raw_db)
    try:
        p=TDBKnowledgeProvider(c);q=p.quest(7)
        assert q['objectives'][0]['object_template']['name']=='Test Cocoon'
        assert any(r['object_id']==9999 for r in p.quest_locations(q,state()) if r.get('object_id'))
        assert q['chain']['PrevQuestID']==6 and q['chain']['ExclusiveGroup']==-5
        assert {r['kind'] for r in p.item_sources(500)}=={'CREATURE','VENDOR'}
        assert p.services(100)['gossip'][0]['options'][0]['OptionText']=='Continue'
        assert p.lookup('smart_scripts',1)==()
        assert p.lookup('quest_template; DROP TABLE creature',1)==()
    finally: c.close()


def test_used_spawn_not_reselected_after_counter_progress(memory):
    s=snapshot(memory);r=s['reference_knowledge']['quests']['7']; r['pois']=[]
    r['spawn_candidates']=[{'spawn_id':i,'entity_kind':'GAMEOBJECT','entry':9999,
        'role':'OBJECTIVE','objective_id':700,'world_map_id':2175,'x':x,'y':10,'z':-10,'context':{}}
        for i,x in [(1,10),(2,30)]]
    r['learned']=[{'kind':'OBJECTIVE_REGION','objective_id':'7:0','skill':'OBJECT_USE',
        'after':1,'position':{'x':10,'y':10,'z':-10,'instance_id':2175}}]
    s['active_quests'][0]['objectives'][0]['current']=1
    assert objective_region(s,7,SimpleNamespace(objective_id='7:0'))['x']==30


def test_object_name_reaches_hover_search_without_forcing_missing_tooltip_id():
    from wowbot.agent.quest_model import QuestModel
    from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
    model=QuestModel()
    quests=[{'quest_id':7,'objectives':[{'objective_id':'7:0','raw_type':'object',
        'description':'Prisoners rescued','current':0,'required':5}]}]
    model.ingest(quests,'live',1)
    model.apply_reference_knowledge({'quests':{'7':{'objectives':[{'objective_id':700,'order':0,
        'raw_type':2,'object_template':{'name':'Thick Cocoon','object_id':9999}}]}}})
    identity=ObjectInteractionFlow.expected_identity(model.records[7].objectives[0])
    assert 'Thick Cocoon' in identity['expected_tooltips'] and identity['object_id']==9999
    assert ObjectInteractionFlow.mouseover_matches(identity,{'name':'Thick Cocoon','quest_related':True})
    assert ObjectInteractionFlow.mouseover_matches(identity,{'tooltip':'Thick Cocoon ~ Quest 7'})
    assert not ObjectInteractionFlow.mouseover_matches(identity,{'name':'Thick Cocoon','object_id':4444})
    assert not ObjectInteractionFlow.mouseover_matches(identity,{'name':'Torch','quest_related':True})
    model.ingest(quests,'next_full',2)
    assert model.records[7].objectives[0].raw['tdb_object_name']=='Thick Cocoon'


def test_tdb_gameobject_type_fills_unknown_live_objective_only_after_exact_match():
    from wowbot.agent.quest_model import QuestModel
    from wowbot.agent.quest_giver_evidence import is_game_object_objective
    from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
    model=QuestModel()
    model.ingest([{'quest_id':55639,'objectives':[{'objective_id':'55639:0',
        'description':'Trapped Expedition Member rescued from cocoons',
        'current':0,'required':5}]}],'live',1)
    reference={'quests':{'55639':{'objectives':[
        {'objective_id':391939,'order':0,'raw_type':2,'credit_kind':'GAMEOBJECT',
         'verified_build':66384,'object_template':{'name':'Thick Cocoon','object_id':339568}},
        {'objective_id':391940,'order':1,'raw_type':0,'credit_kind':'CREATURE_CREDIT'}]}}}
    model.apply_reference_knowledge(reference)
    objective=model.records[55639].objectives[0]
    assert objective.type=='INTERACT' and is_game_object_objective(objective)
    assert objective.raw['tdb_objective_id']==391939
    identity=ObjectInteractionFlow.expected_identity(objective)
    assert identity['object_id']==339568
    assert ObjectInteractionFlow.mouseover_matches(identity,{'name':'Thick Cocoon'})
    assert not ObjectInteractionFlow.mouseover_matches(identity,{'name':'A nearby torch'})
    state={'active_quests':[{'quest_id':55639,'title':'Who Lurks in the Pit',
                            'objectives':[{'current':0,'required':5}]}]}
    assert ObjectInteractionFlow.quest_mouseover_matches(identity,
        {'name':'Thick Cocoon','quest_related':True,'quest_id':55639},state,55639)
    assert not ObjectInteractionFlow.quest_mouseover_matches(identity,
        {'name':'Thick Cocoon','quest_related':True,'quest_id':99999},state,55639)
    assert ObjectInteractionFlow.quest_mouseover_matches(identity,
        {'name':'Thick Cocoon','tooltip':'Thick Cocoon ~ Who Lurks in the Pit'},state,55639)
    model.apply_reference_knowledge({'quests':{}})
    assert model.records[55639].objectives[0].type=='UNKNOWN'


def test_nearest_spawn_uses_z_not_only_xy(memory):
    s=snapshot(memory);r=s['reference_knowledge']['quests']['7'];r['pois']=[]
    r['spawn_candidates']=[{'spawn_id':i,'entity_kind':'GAMEOBJECT','entry':9999,
        'role':'OBJECTIVE','objective_id':700,'world_map_id':2175,'x':x,'y':10,'z':z,'context':{}}
        for i,x,z in [(1,10,-70),(2,30,-10)]]
    assert objective_region(s,7,SimpleNamespace(objective_id='7:0'))['x']==30


def test_latest_poi_build_for_same_objective_and_map(raw_db):
    with sqlite3.connect(raw_db) as db:
        db.executescript('''ALTER TABLE quest_poi ADD COLUMN BlobIndex INTEGER DEFAULT 0;
            ALTER TABLE quest_poi ADD COLUMN VerifiedBuild INTEGER DEFAULT 60822;
            ALTER TABLE quest_poi_points ADD COLUMN VerifiedBuild INTEGER DEFAULT 60822;
            INSERT INTO quest_poi VALUES(7,1,700,0,2175,1409,0,0,0,1,66384);
            INSERT INTO quest_poi_points VALUES(7,1,0,90,90,-10,66384);''')
    c=ReferenceCatalog(raw_db)
    try:
        q=c.quest(7)
        assert [p['poi_id'] for p in q['pois']]==['7:1:1']
        assert q['poi_catalogue_count']==2 and q['poi_superseded_count']==1
        s=state(); s['reference_knowledge']={'quests':{'7':q}}
        point=objective_region(s,7,SimpleNamespace(objective_id='7:0'))
        assert point['x']==90 and point['verified_build']==66384
    finally: c.close()


def test_superseded_blob_does_not_make_surviving_geometry_ambiguous(raw_db):
    with sqlite3.connect(raw_db) as db:
        db.executescript('''ALTER TABLE quest_poi ADD COLUMN BlobIndex INTEGER DEFAULT 0;
            ALTER TABLE quest_poi ADD COLUMN VerifiedBuild INTEGER DEFAULT 60822;
            INSERT INTO quest_poi VALUES(7,1,700,0,2175,1409,0,0,0,1,66384);
            INSERT INTO quest_poi VALUES(7,1,999,32,2175,1409,0,0,0,2,60822);
            INSERT INTO quest_poi VALUES(7,2,999,32,2175,1409,0,0,0,3,66384);
            INSERT INTO quest_poi_points VALUES(7,1,0,90,90,-10);
            INSERT INTO quest_poi_points VALUES(7,2,0,80,80,-10);''')
    c=ReferenceCatalog(raw_db)
    try:
        selected=c.quest(7)['pois']
        assert len(selected)==2
        assert all(not p['geometry_ambiguous'] for p in selected)
        assert {p['point_group_id'] for p in selected}=={'7:1','7:2'}
    finally: c.close()


def test_same_build_distinct_regions_and_unique_older_spawn_survive(raw_db):
    with sqlite3.connect(raw_db) as db:
        db.executescript('''ALTER TABLE quest_poi ADD COLUMN BlobIndex INTEGER DEFAULT 0;
            ALTER TABLE quest_poi ADD COLUMN VerifiedBuild INTEGER DEFAULT 66384;
            INSERT INTO quest_poi VALUES(7,1,700,0,2175,1409,0,0,0,1,66384);
            INSERT INTO quest_poi_points VALUES(7,1,0,40,40,-10);''')
    c=ReferenceCatalog(raw_db)
    try:
        assert len(c.quest(7)['pois'])==2
        assert c.quest(7)['poi_superseded_count']==0
        assert c.spawn_candidates(2175,100)[0]['spawn_id']==10
    finally: c.close()


def test_build_selection_treats_negative_manual_revision_as_its_client_build():
    from wowbot.agent.tdb_builds import newest_rows
    rows=[{'id':1,'VerifiedBuild':-66384},{'id':1,'VerifiedBuild':60822},
          {'id':2,'VerifiedBuild':58238}]
    assert newest_rows(rows,lambda r:r['id'])==[rows[0],rows[2]]


def test_mixed_build_vertices_are_queryable_but_not_routable(memory):
    s=snapshot(memory);p=s['reference_knowledge']['quests']['7']['pois'][0]
    p['points']=[{'x':20,'y':20,'z':-10},{'x':40,'y':20,'z':-10},{'x':40,'y':40,'z':-10}]
    p['geometry_mixed_build']=True
    assert objective_region(s,7,SimpleNamespace(objective_id='7:0')) is None


def test_tdb_chain_enriches_graph_without_asserting_unlock_or_readiness():
    from wowbot.agent.quest_model import QuestModel
    model=QuestModel()
    model.ingest([{'quest_id':7,'objectives':[{'description':'Find X','current':0,'required':1}]}],'live',1)
    model.apply_reference_knowledge({'quests':{'7':{'chain':{'PrevQuestID':6,'RewardNextQuest':8,
        'ExclusiveGroup':-5,'source_build':66384}}}})
    graph=model.graph()
    tdb=[edge for edge in graph['quest_edges'] if edge.get('source')=='TDB_REFERENCE']
    assert {(e['from'],e['to']) for e in tdb}=={('6','7'),('7','8')}
    assert all(e['confirmed'] is False and e['verified_build']==66384 for e in tdb)
    assert model.records[7].dependencies==()
    model.apply_reference_knowledge({'quests':{}})
    assert not [edge for edge in model.graph()['quest_edges'] if edge.get('source')=='TDB_REFERENCE']


def test_proxy_credit_text_names_the_creature_for_location_only(raw_db):
    """Live 2026-10-11 (56034): the credit entry is an invisible proxy; the
    objective text names the real creature, whose spawns locate the area."""
    with sqlite3.connect(raw_db) as db:
        db.executescript('''
            UPDATE quest_objectives SET Type=0,ObjectID=156722,Description='Re-Sizer v9.0.1 tested on Wandering Boars';
            INSERT INTO creature_template VALUES(156716,'Wandering Boar'),(156722,'Re-Sizer Credit'),(300,'Boar');
            INSERT INTO creature VALUES(11,156716,2175,40,50,-10),(12,300,2175,90,90,-10);''')
    c=ReferenceCatalog(raw_db)
    try:
        p=TDBKnowledgeProvider(c);q=p.quest(7)
        objective=q['objectives'][0]
        assert 'npc_id' not in objective
        assert [n['entry'] for n in objective['named_creatures']]==[156716]   # longest name only
        spots=[r for r in p.quest_locations(q,state()) if r['role']=='OBJECTIVE']
        assert [(r['entry'],r['x'],r['y']) for r in spots]==[(156716,40,50)]
    finally: c.close()
