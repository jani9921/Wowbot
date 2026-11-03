"""Keep the working TDB provider; DB2 is supplementary data, not another brain."""
import json
import sqlite3

import pytest

from test_reference_support_20261008 import raw_db, memory, state
from wowbot.agent.reference_catalog import ReferenceCatalog


@pytest.fixture(autouse=True)
def local_client_catalog(tmp_path, monkeypatch):
    """The public checkout has no extracted client DB; use a tiny real SQLite fixture.

    Keep the real catalog reader and world projection under test. Scene resolution
    is input here; its derivation is covered by test_quest_scene_resolution.
    """
    from test_client_catalog_builder_20261025 import builder, inputs
    from wowbot.quests import client_catalog

    arguments, _ = inputs(tmp_path)
    path = tmp_path / "client_reference.sqlite3"
    builder.build(path, *arguments)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO source_files(table_name,decoded_rows,status) VALUES('QuestPOIBlob',1,'DECODED')")
        for quest_id in (7, 72089):
            db.execute("INSERT INTO quest_links VALUES(?,'QuestV2',?)", (quest_id, quest_id))
            db.execute("INSERT INTO db2_rows VALUES('QuestV2',?,?)", (quest_id, json.dumps({'ID': quest_id})))
        db.execute("INSERT INTO quest_links VALUES(11,'QuestPOIBlob',1)")
        db.execute("INSERT INTO db2_rows VALUES('QuestPOIBlob',1,?)", (json.dumps({'QuestID': 11}),))
        db.execute("INSERT INTO poi_blobs VALUES(1,11,2175,1409)")
        db.execute("INSERT INTO poi_points VALUES(1,1,20,30,-10)")
        db.execute("INSERT INTO quest_scene_resolution VALUES(72089,'RESOLVED_REFERENCE','FIXTURE','[90]','[43699]','REFERENCE_READY')")
        for i in range(7):
            db.execute("INSERT INTO path_nodes VALUES(?,?,?,?)", (i+1, 43699, i, i+1))
            db.execute("INSERT INTO locations VALUES(?,?,?,?,?)", (i+1, 10.*i, 20., 30., '[0,0,0]'))
    monkeypatch.setattr(client_catalog, "default_catalog_path", lambda: path)
    yield path


def test_existing_tdb_world_source_and_rows_are_preserved(raw_db):
    before = raw_db.read_bytes()
    reader = ReferenceCatalog(raw_db)
    try:
        assert reader.raw is not None and reader.path == raw_db
        assert reader.quest(7)["title"] == "Rescue"
        assert reader.spawn_candidates(2175, 100)[0]["z"] == -10
        client = reader.client_quest(11, details=True)
        assert client["tables"]["QuestPOIBlob"] > 0
        assert client["confirmed"] is False
        assert reader.diagnostics()["client_db2"]["decoded_tables"] == 2
    finally:
        reader.close()
    assert raw_db.read_bytes() == before


def test_client_data_joins_the_existing_world_projection_without_replacing_tdb_geometry(memory):
    view = memory.knowledge.snapshot(state(), 1.)["quests"]["7"]
    assert view["title"] == "Rescue" and view["source"] == "TDB_REFERENCE"
    assert view["pois"][0]["points"][0]["z"] == -10
    assert view["client_reference"]["quest_id"] == 7
    assert view["client_reference"]["navigation_trusted"] is False


def test_only_explicit_quest_script_relations_are_returned_without_mutating_tdb(raw_db):
    with sqlite3.connect(raw_db) as db:
        db.executescript('''CREATE TABLE smart_scripts(entryorguid INTEGER,source_type INTEGER,id INTEGER,
            event_type INTEGER,event_param1 INTEGER,action_type INTEGER,action_param1 INTEGER);
            INSERT INTO smart_scripts VALUES(7,5,0,47,0,1,0);
            INSERT INTO smart_scripts VALUES(100,0,1,19,7,1,0);
            INSERT INTO smart_scripts VALUES(100,0,2,19,0,1,0);
            INSERT INTO smart_scripts VALUES(100,0,3,0,7,1,0);
            INSERT INTO smart_scripts VALUES(8,5,0,47,0,1,0);''')
    before = raw_db.read_bytes()
    reader = ReferenceCatalog(raw_db)
    try:
        rows = reader.quest_scripts(7)
        assert len(rows) == 2 and {r["relation"] for r in rows} == {"QUEST_SCRIPT", "QUEST_EVENT"}
        assert all(r["execution_supported"] is False for r in rows)
        assert reader.quest_scripts(99999) == ()
    finally:
        reader.close()
    assert raw_db.read_bytes() == before


def test_active_skytop_race_path_reaches_the_agents_existing_reference_projection(memory):
    live=state()
    live['map_id']=2022
    live['player_world_position']['instance_id']=2444
    live['active_quests']=[{'quest_id':72089,'is_complete':False,
        'objectives':[{'objective_id':'72089:0','description':'Complete the Course','current':0,'required':1}]}]
    quest=memory.knowledge.snapshot(live,1.)['quests']['72089']
    resolution=quest['client_reference']['scene_resolution']
    assert resolution['unique_path_id']==43699
    assert resolution['path_reference']['node_count']==7
    assert not resolution['confirmed_live']
