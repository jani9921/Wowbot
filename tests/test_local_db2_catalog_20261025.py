"""Local DB2 provenance, query authority and fourth course regression."""
from copy import deepcopy
import sqlite3

from wowbot.quests.client_catalog import ClientCatalog, default_catalog_path
from wowbot.quests.scene_path_planning import QuestScenePathPolicy
from test_skyriding_lesson_wiring_20261025 import lesson_state


def test_local_catalog_indexes_all_sources_and_admits_partial_import_honestly():
    with sqlite3.connect(default_catalog_path().as_uri() + "?mode=ro", uri=True) as connection:
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert connection.execute("select count(*) from source_files").fetchone()[0] == 1125
        assert connection.execute("select count(*) from source_files where status='DECODED_AVAILABLE_ROWS'").fetchone()[0] == 36
        assert connection.execute("select count(*) from source_files where sha256 is null or length(sha256)!=64").fetchone()[0] == 0
        assert connection.execute("select count(*) from source_files where definition_sha256 is null and decoded_rows>0").fetchone()[0] == 0


def test_the_need_for_higher_velocities_resolves_eight_local_db2_rings_and_a_landing():
    course = ClientCatalog().courses()["77345"]
    assert course["path_id"] == 49404 and course["scene_package"] == 3978
    assert len(course["rings"]) == 8 and len(course["source_node_ids"]) == 9
    assert course["rings"][0][:3] == [2004.0348, 44.026043, 298.28464]
    assert course["target"][:3] == [2226.2136, 78.25347, 142.7569]
    assert course["checkpoint_objective"]["Amount"] == 8
    assert course["coordinate_source"] == "LOCAL_DB2_SCENE_PATH_LOCATION"
    assert course["association_kind"] == "REVIEWED_REFERENCE_RELATION"


def test_quest_adapter_only_resolves_route_data_and_is_stable_through_landing():
    a = lesson_state(mounted=False, rings=0)
    b = lesson_state(mounted=True, rings=5)
    proposal_a = QuestScenePathPolicy().propose(a)[0]
    proposal_b = QuestScenePathPolicy().propose(b)[0]
    assert proposal_a.skill == proposal_b.skill == "MOVE"
    assert proposal_a.key == proposal_b.key
    assert not any(k in proposal_b.parameters for k in ["skyriding_waypoints", "skyriding_course", "binding"])


def test_missing_catalog_has_no_wago_or_old_json_fallback(tmp_path):
    assert QuestScenePathPolicy(ClientCatalog(tmp_path / "absent.sqlite3")).propose(lesson_state()) == []


def test_new_course_uses_current_quest_counts_before_creating_any_route():
    state = lesson_state()
    state["active_quests"][0].update(quest_id=77345, title="The Need For Higher Velocities")
    state["active_quests"][0]["objectives"][0].update(description="0/8 Pass Through The Rings", required=8)
    frozen = deepcopy(state)
    proposal = QuestScenePathPolicy().propose(state)[0]
    assert len(proposal.parameters["flight_path"]["waypoints"]) == 8
    assert state == frozen
    state["active_quests"][0]["objectives"][0]["required"] = 5
    assert QuestScenePathPolicy().propose(state) == []


def test_catalog_is_general_client_data_and_not_a_four_quest_database():
    catalog = ClientCatalog()
    stats = catalog.diagnostics()
    assert stats["quest_ids"] == 66589
    assert stats["scene_packages"] == 3530 and stats["scene_scripts"] == 40431
    assert stats["path_ids"] == 17511 and stats["scene_path_packages"] == 253
    assert stats["poi_blobs"] == 72381 and stats["poi_points"] == 170335
    quest = catalog.quest(11, details=True)
    assert quest["scene_association"] == "UNRESOLVED" and quest["ordered_path"] is None
    assert quest["tables"]["QuestPOIBlob"] > 0
    assert quest["poi_points"][0]["x"] == -9663
    assert not quest["navigation_trusted"] and not quest["confirmed"]


def test_arbitrary_scene_and_path_can_be_queried_without_a_quest_mapping():
    with sqlite3.connect(default_catalog_path().as_uri()+"?mode=ro", uri=True) as db:
        package, path = db.execute("SELECT package_id,path_id FROM scene_paths WHERE package_id NOT IN (3747,3748,3749,3978) LIMIT 1").fetchone()
    catalog = ClientCatalog()
    assert path in catalog.scene(package)["path_ids"]
    geometry = catalog.path_nodes(path)
    assert geometry["node_count"] > 0 and geometry["geometry_complete"]
    assert all(type(p["z"]) in {float, int} for p in geometry["nodes"])
    assert not catalog.scene(package)["execution_supported"]


def test_imported_scene_script_is_queryable_as_data_and_never_executed():
    script = ClientCatalog().record("SceneScriptText", 46850)["Script"]
    assert "pathID = 49404" in script
    assert ClientCatalog().record("SceneScriptText; DROP TABLE db2_rows", 46850) == {}
    assert ClientCatalog().quest(True) == {}


def test_skytop_race_is_resolved_from_its_condition_table_without_a_reviewed_exception():
    result=ClientCatalog().scene_resolution(72089,details=True)
    assert result['status']=='RESOLVED_REFERENCE'
    assert result['package_ids']==[3562] and result['unique_path_id']==43699
    geometry=result['path_reference']
    assert geometry['node_count']==7 and geometry['geometry_complete']
    assert [node['sequence'] for node in geometry['nodes']]==list(range(1,8))
    assert geometry['nodes'][0]['x']==1831.7291 and geometry['nodes'][-1]['z']==345.67175
    evidence=result['candidates'][0]['evidence']
    assert evidence['condition_id']==103255
    assert evidence['root']['record']['CurrQuestID']==[72089,0,0,0]
    assert evidence['path_table_proof'][0]['table_name']=='pathInfo'
    assert not result['confirmed_live'] and not geometry['navigation_trusted']
