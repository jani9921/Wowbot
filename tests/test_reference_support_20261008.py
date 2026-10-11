from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import pytest

from wowbot.agent.reference_catalog import ReferenceCatalog
from wowbot.agent.reference_experience import ReferenceExperience
from wowbot.agent.reference_fallback import objective_region
from wowbot.agent.spatial_memory import SpatialMemory
from wowbot.agent.models import Proposal, Outcome
from wowbot.agent.quest_turn_in import turn_in_names


@pytest.fixture
def raw_db(tmp_path):
    path = tmp_path / "world.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE creature_template(entry INTEGER PRIMARY KEY,name TEXT);
            INSERT INTO creature_template VALUES(100,'Captain Example'),(200,'Other Captain');
            CREATE TABLE creature(guid INTEGER PRIMARY KEY,id INTEGER,map INTEGER,position_x REAL,position_y REAL,position_z REAL);
            INSERT INTO creature VALUES(10,100,2175,20,30,-10);
            CREATE TABLE quest_template(ID INTEGER PRIMARY KEY,LogTitle TEXT,QuestDescription TEXT,LogDescription TEXT,QuestCompletionLog TEXT,AllowableRaces INTEGER);
            INSERT INTO quest_template VALUES(7,'Rescue','Story','Free the captives','Report back to Captain Example.',1);
            INSERT INTO quest_template VALUES(8,'Rescue','Other faction','Free the captives','Report back to Other Captain.',2);
            CREATE TABLE quest_objectives(ID INTEGER,QuestID INTEGER,"Order" INTEGER,Type INTEGER,ObjectID INTEGER,Amount INTEGER,Description TEXT);
            INSERT INTO quest_objectives VALUES(700,7,0,2,9999,5,'Captives rescued');
            CREATE TABLE creature_questender(id INTEGER,quest INTEGER,VerifiedBuild INTEGER);
            INSERT INTO creature_questender VALUES(200,8,123);
            CREATE TABLE creature_queststarter(id INTEGER,quest INTEGER,VerifiedBuild INTEGER);
            INSERT INTO creature_queststarter VALUES(100,7,123);
            CREATE TABLE quest_poi(QuestID INTEGER,Idx1 INTEGER,QuestObjectiveID INTEGER,ObjectiveIndex INTEGER,MapID INTEGER,UiMapID INTEGER,PlayerConditionID INTEGER,NavigationPlayerConditionID INTEGER,SpawnTrackingID INTEGER);
            INSERT INTO quest_poi VALUES(7,0,700,0,2175,1409,0,0,0);
            CREATE TABLE quest_poi_points(QuestID INTEGER,Idx1 INTEGER,Idx2 INTEGER,X INTEGER,Y INTEGER,Z INTEGER);
            INSERT INTO quest_poi_points VALUES(7,0,0,20,30,-10);
        ''')
    return path


def state():
    return {"session_id": "s1", "character_guid": "Player-one", "map_id": 1409, "phase": 1,
            "faction": "Alliance", "frame_id": 1,
            "player_world_position": {"coordinate_space": "WORLD_YARDS", "instance_id": 2175, "x": 10, "y": 10, "z": -10},
            "active_quests": [{"quest_id": 7, "is_complete": False, "objectives": [
                {"objective_id": "7:0", "description": "Captives rescued", "current": 0, "required": 5}]}]}


def attempt(before, skill="QUEST_DIALOG", action="TURN_IN", qid=7, params=None, action_id="a1"):
    return SimpleNamespace(action_id=action_id, baseline=deepcopy(before), plan_id="plan1", started_at=0,
        proposal=Proposal.make(skill, "test", {"quest_id": qid, "action": action, **(params or {})}))


@pytest.fixture
def memory(raw_db, tmp_path):
    result = SpatialMemory(tmp_path / "profile", reference_path=raw_db)
    yield result
    result.entities.close(); result.points.close()


def test_reads_raw_sqlite_without_changing_source(raw_db):
    before = raw_db.read_bytes()
    c = ReferenceCatalog(raw_db)
    try:
        assert c.available and c.raw is not None
        assert c.find_by_name("captain example")[0]["npc_id"] == 100
        assert c.spawn_candidates(2175,100)[0]["z"] == -10
        assert c.role_candidates(2175)[0]["quest_ids"] == [7]
        q = c.quest(7)
        assert q["quest_roles"] == [{"npc_id":100,"quest_id":7,"role":"QUEST_STARTER","verified_build":123}]
        assert q["objectives"][0]["credit_object_id"] == 9999
        assert "npc_id" not in q["objectives"][0]
        assert q["pois"][0]["coordinate_space"] == "TDB_WORLD_REFERENCE"
        assert c.quest(8)["quest_roles"][0]["npc_id"] == 200
        assert c.provenance()["source_sha256"]
        with pytest.raises(sqlite3.OperationalError):
            c.db.execute("DELETE FROM creature_template")
    finally:
        c.close()
    assert raw_db.read_bytes() == before


def test_reference_turnin_is_hint_and_live_name_wins(memory):
    s = state(); s["active_quests"][0]["is_complete"] = True
    s["reference_knowledge"] = memory.knowledge.snapshot(s,1)
    assert turn_in_names(s) == ["Captain Example"]
    s["quest_turn_in_names"] = {"7":{"name":"Live Correct Captain", "source":"QUEST_TEXT_PATTERN"}}
    assert turn_in_names(s) == ["Live Correct Captain"]
    assert memory.entities.get_profile("npc:100") is None


def test_conflicting_reference_does_not_nominate_an_ender(memory):
    reference = deepcopy(memory.reference.quest(7))
    reference["quest_roles"] = [{"npc_id":200,"role":"QUEST_ENDER"}]
    candidates,status = memory.knowledge.turnins(reference, [])
    assert candidates == [] and status == "AMBIGUOUS_TEXT_ROLE_CONFLICT"


def dialog_state():
    s=state()
    guid="Creature-0-1-2175-1-100-00001"
    s.update(target={"guid":guid,"npc_id":100,"name":"Captain Example"},
             quest_ui={"quest_id":7,"action":"TURN_IN"},
             quest_text={"quest_id":7,"ender_guid":guid})
    return s


def test_verified_turnin_fills_missing_relation_and_survives_restart(memory, raw_db):
    before=dialog_state(); after=deepcopy(before)
    after["events"]=[{"sequence":3,"event_type":"QUEST_TURNED_IN","payload":{"quest_id":7}}]
    a=attempt(before)
    memory.experience.finish(a,Outcome.SUCCESS,"quest_turned_in",after)
    memory.experience.finish(a,Outcome.SUCCESS,"quest_turned_in",after)
    learned=memory.experience.query(after,quest_id=7)
    assert len(learned)==1 and learned[0]["role"]=="QUEST_ENDER"
    assert learned[0]["location_kind"]=="OBSERVER_POSITION"
    assert memory.knowledge.snapshot(after,1)["quests"]["7"]["turnin_status"]=="LEARNED"
    again=SpatialMemory(memory.entities.path.parent,reference_path=raw_db)
    try:
        assert again.knowledge.snapshot(after,1)["quests"]["7"]["turnin_candidates"][0]["npc_id"]==100
        assert again.reference.quest(7)["quest_roles"][0]["role"]=="QUEST_STARTER"
    finally:
        again.entities.close(); again.points.close()


@pytest.mark.parametrize("change", ["no_event","wrong_quest","wrong_guid","stale_event","failure","phase","faction"])
def test_no_false_turnin_learning(memory,change):
    before=dialog_state(); after=deepcopy(before)
    event={"event_type":"QUEST_TURNED_IN","payload":{"quest_id":7}}
    after["events"]=[event]
    outcome=Outcome.SUCCESS
    if change=="no_event": after["events"]=[]
    if change=="wrong_quest": after["events"][0]["payload"]["quest_id"]=8
    if change=="wrong_guid": before["quest_text"]["ender_guid"]="Creature-other"
    if change=="stale_event": before["events"]=[event]
    if change=="failure": outcome=Outcome.FAILURE
    if change=="phase": after["phase"]=2
    if change=="faction": after["faction"]="Horde"
    memory.experience.finish(attempt(before),outcome,"test",after)
    assert memory.experience.query(after,quest_id=7)==[]


def test_observation_stores_exact_world_location_without_normalized_pollution(memory):
    s=state(); unit={"guid":"Creature-0-1-2175-1-100-00001","npc_id":100,"name":"Captain Example",
                    "world_position": {"coordinate_space":"WORLD_YARDS","instance_id":2175,"x":20,"y":30,"z":-10}}
    s["mouseover"]=unit
    memory.ingest(s,1); memory.experience.observe(s,1)
    assert memory.entities.locations("npc:100")==[]
    rows=memory.experience.query(s,npc_id=100)
    assert rows[0]["position"]["z"]==-10
    memory.experience.observe(s,2)
    assert len(memory.experience.query(s,npc_id=100))==1
    unit["world_position"]["z"]=-40
    memory.experience.observe(s,3)
    assert {r["position"]["z"] for r in memory.experience.query(s,npc_id=100)}=={-10,-40}
    other={**s,"phase":2}
    assert memory.experience.query(other,npc_id=100)==[]


def test_poi_is_primary_and_failures_are_context_scoped(memory):
    s=state(); obj=SimpleNamespace(objective_id="7:0")
    s["reference_knowledge"]=memory.knowledge.snapshot(s,1)
    region=objective_region(s,7,obj)
    assert region["z"]==-10 and region["require_navmesh"] and not region["navigation_trusted"]
    assert objective_region({**s,"quest_locations":[{"x":.5,"y":.5}]},7,obj)['reference_hint_id']==region['reference_hint_id']
    assert objective_region({**s,"target":{"guid":"anything"}},7,obj) is not None
    for i in range(2):
        memory.experience.finish(attempt(s,skill="MOVE",params=region,action_id=str(i)),Outcome.FAILURE,"supported_stuck",s)
    s["reference_knowledge"]=memory.knowledge.snapshot(s,2)
    assert objective_region(s,7,obj) is None
    s["phase"]=2; s["reference_knowledge"]=memory.knowledge.snapshot(s,3)
    assert objective_region(s,7,obj) is not None


@pytest.mark.parametrize("change",["polygon","condition","world_map","ui_map"])
def test_unsafe_poi_abstains(memory,change):
    s=state(); s["reference_knowledge"]=memory.knowledge.snapshot(s,1)
    poi=s["reference_knowledge"]["quests"]["7"]["pois"][0]
    if change=="polygon": poi["points"].append({"x":40,"y":40,"z":-10})
    if change=="zero_z": poi["points"][0]["z"]=0
    if change=="condition": poi["conditions"]["PlayerConditionID"]=999
    if change=="world_map": poi["world_map_id"]=99
    if change=="ui_map": poi["ui_map_id"]=99
    assert objective_region(s,7,SimpleNamespace(objective_id="7:0")) is None


def test_successful_objective_teaches_region_when_reference_is_empty(memory):
    before=state(); before["active_quests"][0]["quest_id"]=99
    before["active_quests"][0]["objectives"][0]["objective_id"]="99:0"
    after=deepcopy(before); after["active_quests"][0]["objectives"][0]["current"]=1
    memory.experience.finish(attempt(before,skill="OBJECT_USE",qid=99,params={"objective_id":"99:0"}),Outcome.SUCCESS,"objective_progress",after)
    after["reference_knowledge"]=memory.knowledge.snapshot(after,1)
    # It is learned, but must not send this run back to the already-used object.
    assert objective_region(after,99,SimpleNamespace(objective_id="99:0")) is None
    again=deepcopy(after); again['active_quests'][0]['objectives'][0]['current']=0
    learned=objective_region(again,99,SimpleNamespace(objective_id="99:0"))
    assert learned["source"]=="LEARNED_OBJECTIVE_REGION" and learned["z"]==-10
    assert memory.reference.quest(99) is None


def test_route_capture_is_bounded_and_records_failure(memory):
    s=state(); a=attempt(s,skill="MOVE")
    for i in range(300):
        s["player_world_position"]["x"]=i
        memory.experience.observe(s,i,a)
    memory.experience.finish(a,Outcome.FAILURE,"supported_stuck",s)
    row=memory.experience.query(s,quest_id=7)[0]
    assert row["kind"]=="ROUTE_OUTCOME" and len(row["points"])==256 and row["truncated"]
    assert row["outcome"]=="FAILURE" and not row["navigation_trusted"]


def test_learned_unit_location_precedes_wrong_static_spawn(memory):
    from wowbot.agent.location_fallback import reference_destination
    s=dialog_state()
    s["target"]["world_position"]={"coordinate_space":"WORLD_YARDS","instance_id":2175,"x":12,"y":11,"z":-10}
    memory.experience.observe(s,1)
    s["spawn_reference_candidates"]=memory.spawn_reference(s)["candidates"]
    assert len(s["spawn_reference_candidates"])==2  # old data is preserved
    chosen=reference_destination(s)
    assert chosen["source"]=="ENTITY_MEMORY_WORLD" and chosen["x"]==12


def test_planner_uses_tdb_primary_navmesh_search(memory):
    from wowbot.agent.quest_model import QuestModel
    from wowbot.agent.world import WorldModel
    from wowbot.agent.models import Observation
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    s=state(); s.update(timestamp=1.,frame_id=1)
    s["reference_knowledge"]=memory.knowledge.snapshot(s,1)
    world=WorldModel()
    world.ingest(Observation.create(s,1))
    record=world.quest_model.records[7]
    policy=QuestLocationPlanningPolicy()
    proposals=policy.propose_objective(world,record.objectives[0],record,'7')
    assert len(proposals)==1 and proposals[0].skill=="MOVE"
    p=proposals[0]
    assert p.priority==96 and p.parameters["require_navmesh"] and p.parameters["reference_hint_id"]=="poi:7:0:0"
    world.state["quest_locations"]=[{"quest_id":7,"map_id":1409,"x":.4,"y":.5}]
    assert policy.propose_objective(world,record.objectives[0],record,'7')[0].parameters['source']=='TDB_REFERENCE_POI'


def test_runtime_uses_raw_db_and_publishes_poi_hints(raw_db,tmp_path,monkeypatch):
    from test_agent_runtime import Sensor,binding_file,state as runtime_state
    from wowbot.agent.runtime import AgentRuntime
    from wowbot.agent.executor import RecordingExecutor
    monkeypatch.setenv("AIPC_REFERENCE_CATALOG",str(raw_db))
    sensor=Sensor()
    runtime=AgentRuntime(42,binding_file(tmp_path),tmp_path/'output',sensor=sensor,executor=RecordingExecutor(),vision=False)
    try:
        sensor.payload=runtime_state(**state())
        result=runtime.step(1)
        assert result["reference_catalog"]["path"]==str(raw_db)
        q=runtime.agent.world.query.reference_quest(7)
        assert q["pois"][0]["points"][0]["z"]==-10
        assert q["turnin_candidates"][0]["name"]=="Captain Example"
        assert "reference_knowledge" not in runtime.agent.world.addon_state
    finally:
        runtime.close()


def test_missing_quest_is_filled_from_addon_with_correct_provenance(memory):
    s=state(); quest=s["active_quests"][0]
    quest.update(quest_id=99,title="Live-only quest",completion_log_text="Return to Captain Example.")
    memory.experience.observe(s,1)
    learned=memory.knowledge.snapshot(s,1)["quests"]["99"]
    assert learned["title"]=="Live-only quest"
    assert learned["source"]=="ADDON_QUEST_HISTORY"
    assert learned["turnin_candidates"][0]["source"]=="ADDON_QUEST_HISTORY_TEXT"
    assert memory.reference.quest(99) is None


@pytest.mark.parametrize("field,value", [("faction","Horde"),("character_guid","Player-other")])
def test_snapshot_invalidates_immediately_on_learning_context_change(memory,field,value):
    before=dialog_state(); after=deepcopy(before)
    after["events"]=[{"event_type":"QUEST_TURNED_IN","payload":{"quest_id":7}}]
    memory.experience.finish(attempt(before),Outcome.SUCCESS,"quest_turned_in",after)
    assert memory.knowledge.snapshot(after,1)["quests"]["7"]["turnin_status"]=="LEARNED"
    after[field]=value
    assert memory.knowledge.snapshot(after,1.01)["quests"]["7"]["turnin_status"]=="HYPOTHESIS"


def test_reference_ender_is_used_in_actual_friendly_npc_filter(memory):
    from wowbot.agent.quest_giver_evidence import friendly_npc_relevant
    s=state(); s["active_quests"][0]["is_complete"]=True
    s["reference_knowledge"]=memory.knowledge.snapshot(s,1)
    s["quest_locations"]=[{"quest_id":7,**s["player_world_position"]}]
    assert friendly_npc_relevant(s,"Creature-0-1-2175-1-100-00001",(),unit_name="Captain Example")
    assert not friendly_npc_relevant(s,"Creature-0-1-2175-1-200-00001",(),unit_name="Other Captain")


def test_terminal_hook_records_verified_relation(memory):
    from test_execution_bookkeeping import terminal_planner,World
    from wowbot.agent.execution_bookkeeping import ExecutionBookkeeper
    before=dialog_state(); after=deepcopy(before)
    after["events"]=[{"event_type":"QUEST_TURNED_IN","payload":{"quest_id":7}}]
    world=World(after); world.entity_memory=memory.entities
    ExecutionBookkeeper().record_terminal(attempt(before),Outcome.SUCCESS,"quest_turned_in",2,
        planner=terminal_planner(),world=world,recovery_resume=None)
    assert memory.experience.query(after,quest_id=7)[0]["role"]=="QUEST_ENDER"


def test_optional_learning_error_does_not_break_terminal_recovery(caplog):
    from test_execution_bookkeeping import terminal_planner,World
    from wowbot.agent.execution_bookkeeping import ExecutionBookkeeper
    def fail(*args):
        raise sqlite3.OperationalError("test write failure")
    s=state(); world=World(s)
    world.entity_memory=SimpleNamespace(reference_experience=SimpleNamespace(finish=fail))
    a=attempt(s,skill="MOVE")
    result=ExecutionBookkeeper().record_terminal(a,Outcome.FAILURE,"supported_stuck",2,
        planner=terminal_planner(),world=world,recovery_resume=None)
    assert result.recovery_resume is a.proposal
    assert "Reference learning failed" in caplog.text


def test_reference_poi_never_mixes_coordinate_spaces(memory):
    s=state(); s["reference_knowledge"]=memory.knowledge.snapshot(s,1)
    s["player_world_position"]["coordinate_space"]="NORMALIZED_MAP"
    assert objective_region(s,7,SimpleNamespace(objective_id="7:0")) is None
