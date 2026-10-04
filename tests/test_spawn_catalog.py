import json

import pytest

from wowbot.agent.spawn_catalog import (candidates, import_dump,
                                        import_quest_relations,
                                        quest_role_candidates, sql_rows)


def test_sql_strings_are_data():
    assert list(sql_rows("(1,'a,b','c\\'d'),(2,'x(y)','z');")) == [
        ['1', 'a,b', "c'd"], ['2', 'x(y)', 'z']]
    with pytest.raises(ValueError):
        list(sql_rows("(1,'incomplete"))


def test_import_retains_multiple_spawns_and_context(tmp_path):
    source = tmp_path / 'world.sql'
    columns = ['guid', 'id', 'map', 'position_x', 'position_y', 'position_z', 'PhaseId']
    source.write_text('CREATE TABLE `creature` (\n' +
        ''.join(f'  `{c}` float,\n' for c in columns) + ') ENGINE=InnoDB;\n' +
        'INSERT INTO `creature` VALUES (1,156626,2175,-435,-2611,0.6,13845),(2,156626,2175,1,2,3,7);\n', encoding='utf-8')
    catalog = tmp_path / 'catalog.sqlite3'
    assert import_dump(source, catalog)['count'] == 2
    rows = candidates(2175, 156626, catalog)
    assert len(rows) == 2
    assert rows[0]['context']['PhaseId'] == '13845'
    assert rows[0]['z'] == .6
    assert all(not row['confirmed'] and not row['navigation_trusted'] for row in rows)
    assert candidates(1609, 156626, catalog) == []
    with pytest.raises(FileExistsError):
        import_dump(source, catalog)


def test_reference_does_not_replace_live_position(tmp_path, monkeypatch):
    from wowbot.agent.spatial_memory import SpatialMemory
    import wowbot.agent.spawn_catalog as module
    monkeypatch.setattr(module, 'candidates', lambda *args: [
        {'x': 3., 'y': 4., 'z': 1., 'confirmed': False}])
    memory = SpatialMemory(tmp_path)
    state = {'map_id': 1609, 'target': {'guid': 'npc-live', 'npc_id': 156626},
             'player_world_position': {'instance_id': 2175, 'x': 0., 'y': 0.}}
    before = json.dumps(state)
    result = memory.spawn_reference(state)
    assert result['candidates'][0]['distance_yards'] == 5
    assert result['world_map_id'] == 2175
    assert result['navigation_enabled'] is False
    assert json.dumps(state) == before


def test_quest_roles_are_joined_as_candidate_evidence(tmp_path):
    source = tmp_path / "world.sql"
    source.write_text(
        "CREATE TABLE `creature` (\n"
        " `guid` int,\n `id` int,\n `map` int,\n `position_x` float,\n"
        " `position_y` float,\n `position_z` float,\n `PhaseId` int\n);\n"
        "INSERT INTO `creature` VALUES (1,156626,2175,-435,-2611,.6,13845);\n"
        "INSERT INTO `creature_queststarter` VALUES (156626,54951,45745);\n"
        "INSERT INTO `creature_questender` VALUES (156626,54952,45745);\n",
        encoding="utf-8")
    catalog = tmp_path / "catalog.sqlite3"
    import_dump(source, catalog)
    result = import_quest_relations(source, catalog)
    assert result == {"starters": 1, "enders": 1, "sha256": result["sha256"],
                      "catalog": str(catalog)}
    rows = quest_role_candidates(2175, path=catalog)
    assert rows[0]["npc_id"] == 156626
    assert rows[0]["quest_ids"] == [54951]
    assert rows[0]["role_hypothesis"] == "QUEST_STARTER"
    assert rows[0]["confirmed"] is False


def test_role_location_clusters_phase_variants_without_claiming_identity(tmp_path, monkeypatch):
    from wowbot.agent.spatial_memory import SpatialMemory
    import wowbot.agent.spawn_catalog as module
    common = dict(source="TDB_REFERENCE", source_sha256="digest", world_map_id=2175,
                  x=10., y=20., z=1., coordinate_space="WORLD_YARDS",
                  role_hypothesis="QUEST_STARTER", confirmed=False)
    monkeypatch.setattr(module, "quest_role_candidates", lambda *args: [
        {**common, "spawn_id": 1, "npc_id": 100, "quest_ids": [1], "context": {"PhaseId": "5"}},
        {**common, "spawn_id": 2, "npc_id": 200, "quest_ids": [2], "context": {"PhaseId": "6"}},
    ])
    memory = SpatialMemory(tmp_path)
    value = memory.quest_role_reference({"player_world_position": {
        "instance_id": 2175, "x": 0., "y": 0., "z": 1.}})
    assert len(value["candidates"]) == 1
    assert value["candidates"][0]["npc_ids"] == [100, 200]
    assert value["candidates"][0]["identity_confirmed"] is False


# DESIGN-080: get_candidate_locations()/cluster_locations()/reliability_score().

def test_get_candidate_locations_reads_real_stored_world_points(tmp_path):
    from wowbot.agent.spatial_memory import SpatialMemory
    from wowbot.vision.map_mouseover import MapMouseover
    memory = SpatialMemory(tmp_path)
    point = MapMouseover(surface="WORLD_MAP", semantic_type="QUEST_GIVER", map_id=1609,
                         x=.3, y=.4, local_x=None, local_y=None, tooltip="Some Giver")
    memory.points.record(point, name="Some Giver", npc_id=42, observed_at=100.)
    rows = memory.get_candidate_locations(1609, as_of=100.)
    assert len(rows) == 1
    assert rows[0]["npc_id"] == 42 and rows[0]["map_id"] == 1609
    assert memory.get_candidate_locations(9999, as_of=100.) == []


def test_cluster_locations_merges_nearby_rows_and_keeps_far_rows_separate():
    from wowbot.agent.spatial_memory import SpatialMemory
    rows = [
        {"x": 10., "y": 20., "npc_id": 1},
        {"x": 10.2, "y": 20.1, "npc_id": 2},
        {"x": 90., "y": 90., "npc_id": 3},
    ]
    clusters = SpatialMemory.cluster_locations(rows, extra_fields={"npc_ids": "npc_id"})
    assert len(clusters) == 2
    near = next(c for c in clusters if c["x"] == 10.)
    assert near["npc_ids"] == [1, 2]


def test_reliability_score_rewards_repetition_and_recency():
    from wowbot.agent.spatial_memory import SpatialMemory
    fresh_once = SpatialMemory.reliability_score({"seen_count": 1, "last_seen": 100.}, now=100.)
    fresh_many = SpatialMemory.reliability_score({"seen_count": 6, "last_seen": 100.}, now=100.)
    stale_many = SpatialMemory.reliability_score({"seen_count": 6, "last_seen": 0.}, now=90000.)
    assert 0. < fresh_once < fresh_many <= 1.
    assert stale_many < fresh_many
    assert SpatialMemory.reliability_score({"seen_count": 1}, now=100.) == 0.3
