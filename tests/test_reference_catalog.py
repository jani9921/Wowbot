import json
import sqlite3
import pytest

from wowbot.agent.reference_catalog import ReferenceCatalog, build_reference, dump_rows


@pytest.fixture
def catalog_path(tmp_path):
    world = tmp_path / "world.sql"
    world.write_text("""CREATE TABLE `creature_template` (
 `entry` int,
 `name` text,
 `VerifiedBuild` int
);
INSERT INTO `creature_template` VALUES (162943,'Hjalmar the Undying',69497),(162947,'Hjalmar the Undying',69497);
CREATE TABLE `creature` (
 `guid` int,
 `id` int,
 `map` int,
 `position_x` float,
 `position_y` float,
 `position_z` float
);
INSERT INTO `creature` VALUES (1,162943,2175,10,20,-5);
CREATE TABLE `quest_template` (
 `ID` int,
 `LogTitle` text,
 `QuestDescription` text,
 `LogDescription` text,
 `QuestCompletionLog` text
);
INSERT INTO `quest_template` VALUES (58915,'Hjalmar\\'s Final Execution','First\\nSecond','Slay Hjalmar with Execute','Return to Private Cole.');
CREATE TABLE `quest_objectives` (
 `ID` int,
 `QuestID` int,
 `Order` int,
 `Type` int,
 `ObjectID` int,
 `Amount` int,
 `Description` text
);
INSERT INTO `quest_objectives` VALUES (395100,58915,0,0,174978,1,'Hjalmar slain with Execute');
CREATE TABLE `creature_queststarter` (
 `id` int,
 `quest` int,
 `VerifiedBuild` int
);
INSERT INTO `creature_queststarter` VALUES (162943,58915,69497);
""", encoding="utf8")
    hotfix = tmp_path / "hotfix.sql"
    hotfix.write_text("""CREATE TABLE `creature` (
 `ID` int,
 `Name` text
);
INSERT INTO `creature` VALUES (162943,'DB2 record');
CREATE TABLE `spell_name` (
 `ID` int,
 `Name` text,
 `VerifiedBuild` int
);
INSERT INTO `spell_name` VALUES (5308,'Execute',69497);
""", encoding="utf8")
    output = tmp_path / "reference.sqlite3"
    build_reference(world, hotfix, output)
    return output


def test_import_preserves_names_text_credit_ids_and_source_namespaces(catalog_path):
    reader = ReferenceCatalog(catalog_path)
    assert len(reader.find_by_name("Hjalmar the Undying")) == 2
    assert reader.npc(162943)["confirmed"] is False
    quest = reader.quest(58915)
    assert quest["description"] == "First\nSecond"
    assert quest["objectives"][0]["credit_object_id"] == 174978
    assert "npc_id" not in quest["objectives"][0]
    assert reader.records("HOTFIX", "creature", 162943)[0]["Name"] == "DB2 record"
    assert reader.records("HOTFIX", "spell_name", 5308)[0]["Name"] == "Execute"
    assert reader.npc(162943)["name"] == "Hjalmar the Undying"
    with pytest.raises(sqlite3.OperationalError):
        reader.db.execute("DELETE FROM npc_templates")
    reader.close()


def test_dump_parser_does_not_execute_strings_and_preserves_escapes():
    assert list(dump_rows("(1,'a,b','c\\'d','a\\nb',NULL,'NULL',-1.5);")) == [
        [1, "a,b", "c'd", "a\nb", None, "NULL", -1.5]]
    with pytest.raises(ValueError):
        list(dump_rows("(1,evil());"))


def test_existing_catalogue_is_never_overwritten(catalog_path, tmp_path):
    before = catalog_path.read_bytes()
    with pytest.raises(FileExistsError):
        build_reference(tmp_path / "world.sql", None, catalog_path)
    assert catalog_path.read_bytes() == before


def test_reference_names_are_hypotheses_not_learned_identities(catalog_path, tmp_path):
    from wowbot.agent.spatial_memory import SpatialMemory
    from wowbot.agent.quest_semantics import resolve_entity_candidates
    memory = SpatialMemory(tmp_path / "profile", reference_path=catalog_path)
    try:
        hits = resolve_entity_candidates({"type": "KILL", "description": "Hjalmar the Undying slain"}, memory.entities)
        assert {hit["npc_id"] for hit in hits} == {162943, 162947}
        assert all(hit["source"] == "TDB_REFERENCE" and not hit["confirmed"]
                   and hit["confidence"] == .3 and hit["source_sha256"] for hit in hits)
        assert memory.entities.get_profile("npc:162943") is None
        assert memory.entities.locations("npc:162943") == []
        assert memory.entities.recognize_visual({"signature_id": "unknown"}) == []
    finally:
        memory.entities.close(); memory.points.close()


def test_runtime_reference_joins_existing_learned_guids_and_visuals(catalog_path, tmp_path):
    from wowbot.agent.spatial_memory import SpatialMemory
    memory = SpatialMemory(tmp_path / "profile", reference_path=catalog_path)
    state = {"session_id": "test", "map_id": 1,
             "mouseover": {"guid": "Creature-confirmed", "npc_id": 162943, "name": "Hjalmar the Undying"},
             "cursor_position": {"nx": .4, "ny": .5}, "active_quests": [{"quest_id": 58915}]}
    signature = {"signature_id": "appearance-A", "appearance": {"red_bin": 4}}
    try:
        memory.ingest(state, 1, probe={"source": "WORLD3D", "x": .4, "y": .5, "visual_signature": signature})
        record = memory.knowledge.entity(162943)
        assert record["reference"]["name"] == "Hjalmar the Undying"
        assert record["learned"]["guids"][0]["guid"] == "Creature-confirmed"
        assert "appearance-A" in record["learned"]["visual_observations"][0]["signature"]
        assert record["learned"]["locations"] == []  # player position is not an NPC position
        statements = []
        memory.reference.db.set_trace_callback(statements.append)
        first = memory.knowledge.snapshot(state, 1)
        count = len(statements)
        first["entities"].clear()  # returned data must not poison cached reads
        assert memory.knowledge.snapshot(state, 1.1)["entities"]
        assert len(statements) == count
        assert memory.knowledge.snapshot({**state, "active_quests": [], "mouseover": {}}, 1.2)["quests"] == {}
        # Reference lookup has not learned the unobserved same-name NPC.
        assert memory.entities.get_profile("npc:162947") is None
    finally:
        memory.entities.close(); memory.points.close()
    reopened = SpatialMemory(tmp_path / "profile", reference_path=catalog_path)
    try:
        assert reopened.knowledge.entity(162943)["learned"]["guids"]
        assert reopened.knowledge.entity(162943)["learned"]["visual_observations"]
    finally:
        reopened.entities.close(); reopened.points.close()


def test_new_catalogue_is_used_for_existing_conservative_spawn_fallback(catalog_path, tmp_path):
    from wowbot.agent.spatial_memory import SpatialMemory
    memory = SpatialMemory(tmp_path / "profile", reference_path=catalog_path)
    try:
        state = {"map_id": 999, "player_world_position": {"instance_id": 2175, "x": 11, "y": 20, "z": -5},
                 "target": {"npc_id": 162943, "guid": "Creature-selected"}}
        spawn = memory.spawn_reference(state)["candidates"][0]
        assert spawn["world_map_id"] == 2175 and spawn["distance_yards"] == 1
        assert spawn["source_sha256"] and not spawn["navigation_trusted"]
        assert memory.quest_role_reference(state)["candidates"][0]["quest_ids"] == [58915]
        state["player_world_position"]["instance_id"] = 99
        assert memory.spawn_reference(state)["candidates"] == []
    finally:
        memory.entities.close(); memory.points.close()


def test_missing_or_invalid_reference_does_not_break_learning(tmp_path):
    from wowbot.agent.spatial_memory import SpatialMemory
    path = tmp_path / "missing.sqlite3"
    memory = SpatialMemory(tmp_path / "profile", reference_path=path)
    try:
        assert memory.reference.status == "MISSING" and not path.exists()
        memory.ingest({"mouseover": {"guid": "Creature-one", "npc_id": 12, "name": "New NPC"}}, 1)
        assert memory.entities.find_by_name("New NPC")[0]["npc_id"] == 12
    finally:
        memory.entities.close(); memory.points.close()
    path.write_bytes(b"not sqlite")
    reader = ReferenceCatalog(path)
    assert not reader.available and reader.status == "INVALID"
    assert reader.npc(1) is None
    reader.close()


def test_actual_runtime_publishes_reference_without_overwriting_live_quest(catalog_path, tmp_path, monkeypatch):
    from test_agent_runtime import Sensor, binding_file, state
    from wowbot.agent.runtime import AgentRuntime
    from wowbot.agent.executor import RecordingExecutor
    from wowbot.agent.observation_ingestion import EPHEMERAL_OBSERVATION_SOURCES
    monkeypatch.setenv("AIPC_REFERENCE_CATALOG", str(catalog_path))
    sensor = Sensor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=RecordingExecutor(), vision=False)
    try:
        sensor.payload = state(target={"guid": "Creature-live", "npc_id": 162943, "name": "Hjalmar the Undying"},
                               active_quests=[{"quest_id": 58915, "title": "Live title", "is_complete": False,
                                              "objectives": [{"type": "KILL", "description": "Hjalmar the Undying slain", "current_count": 0, "required_count": 1}]}])
        result = runtime.step(1)
        query = runtime.agent.world.query
        assert query.reference_entity(162943)["reference"]["name"] == "Hjalmar the Undying"
        assert query.reference_quest(58915)["objectives"][0]["credit_object_id"] == 174978
        assert runtime.agent.world.state["active_quests"][0]["title"] == "Live title"
        assert runtime.agent.world.state["active_quests"][0]["is_complete"] is False
        assert "reference_knowledge" not in runtime.agent.world.addon_state
        assert "REFERENCE_MEMORY" in EPHEMERAL_OBSERVATION_SOURCES
        assert result["reference_catalog"]["status"] == "READY"
        ref = query.reference_entity(162943)
        ref["reference"]["name"] = "Wrong"
        assert query.reference_entity(162943)["reference"]["name"] == "Hjalmar the Undying"
        assert runtime.spatial.entities.get_profile("npc:162947") is None
    finally:
        runtime.close()
