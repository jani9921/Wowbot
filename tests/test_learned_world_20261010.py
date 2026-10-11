"""User 2026-10-10: the TDB is the world memory; what the agent verifies live
is saved in the TDB's own shape and read back next to it (gap filling for
script-summoned NPCs and quests without starter/ender rows)."""
from copy import deepcopy
from types import SimpleNamespace
import sqlite3

import pytest

from wowbot.agent.learned_world import LearnedWorld, merge_spawns
from wowbot.agent.models import Outcome, Proposal
from wowbot.agent.quest_creature_memory import QuestCreatureMemory
from wowbot.agent.spatial_memory import SpatialMemory
from wowbot.agent.tdb_locations import role_region
from wowbot.vision.entity_memory import EntityMemory

GARRICK = "Creature-0-1-2175-1-245394-00001"     # script-summoned: no TDB spawn
PLAYER = {"coordinate_space": "WORLD_YARDS", "instance_id": 2175, "x": 100., "y": 200., "z": 5.}


@pytest.fixture
def raw_db(tmp_path):
    path = tmp_path / "world.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE creature_template(entry INTEGER PRIMARY KEY,name TEXT);
            INSERT INTO creature_template VALUES(245394,'Captain Garrick'),(100,'Alaria');
            CREATE TABLE creature(guid INTEGER PRIMARY KEY,id INTEGER,map INTEGER,position_x REAL,position_y REAL,position_z REAL);
            INSERT INTO creature VALUES(10,100,2175,20,30,-10);
            CREATE TABLE quest_template(ID INTEGER PRIMARY KEY,LogTitle TEXT,QuestDescription TEXT,LogDescription TEXT,QuestCompletionLog TEXT,AllowableRaces INTEGER);
            INSERT INTO quest_template VALUES(55639,'Who Lurks in the Pit','','','',1);
            CREATE TABLE quest_objectives(ID INTEGER,QuestID INTEGER,"Order" INTEGER,Type INTEGER,ObjectID INTEGER,Amount INTEGER,Description TEXT);
            CREATE TABLE creature_questender(id INTEGER,quest INTEGER,VerifiedBuild INTEGER);
            CREATE TABLE creature_queststarter(id INTEGER,quest INTEGER,VerifiedBuild INTEGER);
        ''')
    return path


@pytest.fixture
def memory(raw_db, tmp_path):
    result = SpatialMemory(tmp_path / "profile", reference_path=raw_db)
    yield result
    result.entities.close(); result.points.close()


@pytest.fixture
def world(tmp_path):
    learned = LearnedWorld(tmp_path / "tdb_learned.sqlite3")
    yield learned
    learned.close()


def state(**extra):
    return {"session_id": "s1", "character_guid": "Player-one", "map_id": 1409, "phase": None,
            "frame_id": 1, "player_world_position": dict(PLAYER), **extra}


def attempt(before, skill, params, action_id="a1"):
    return SimpleNamespace(action_id=action_id, baseline=deepcopy(before), plan_id="p", started_at=0,
                           proposal=Proposal.make(skill, "test", params))


def test_observations_merge_into_one_cell_with_a_running_mean(world):
    world.record_spawn("CREATURE", 7, "Goat", {**PLAYER, "x": 100.})
    world.record_spawn("CREATURE", 7, "Goat", {**PLAYER, "x": 102.})
    world.record_spawn("CREATURE", 7, "Goat", {**PLAYER, "x": 160.})     # another cell
    rows = world.spawns(2175, "CREATURE", 7)
    near = next(r for r in rows if r["x"] < 150)
    assert len(rows) == 2 and near["seen_count"] == 2 and near["x"] == pytest.approx(101.)
    assert near["source"] == "LEARNED_SPAWN" and near["location_kind"] == "OBSERVER_POSITION"
    assert world.spawns(9999, "CREATURE", 7) == []


def test_learned_row_confirms_a_tdb_spawn_or_fills_its_gap():
    tdb = [{"spawn_id": 1, "x": 0., "y": 0., "source": "TDB_REFERENCE"}]
    learned = [{"spawn_id": "learned:a", "x": 5., "y": 5., "seen_count": 3, "last_seen": 9.,
                "source": "LEARNED_SPAWN"},
               {"spawn_id": "learned:b", "x": 300., "y": 0., "seen_count": 1, "last_seen": 9.,
                "source": "LEARNED_SPAWN"}]
    merged = merge_spawns(tdb, learned)
    assert merged[0]["live_confirmed"] is True and merged[0]["live_seen_count"] == 3
    assert [row["spawn_id"] for row in merged] == [1, "learned:b"]


def test_verified_interactions_save_places_failures_do_not(memory):
    learned = memory.experience.learned
    before = state(target={"guid": GARRICK, "name": "Captain Garrick"})
    memory.experience.finish(attempt(before, "COMBAT", {"guid": GARRICK}), Outcome.FAILURE, "x", before)
    assert learned.spawns(2175, "CREATURE", 245394) == []
    memory.experience.finish(attempt(before, "TALK", {"guid": GARRICK}, "a2"), Outcome.SUCCESS, "ok", before)
    assert learned.spawns(2175, "CREATURE", 245394)[0]["name"] == "Captain Garrick"
    totem = state(mouseover={"name": "Harpy Totem", "tooltip": "Harpy Totem ~ Purge the Totems"})
    memory.experience.finish(attempt(totem, "OBJECT_USE", {"tdb_object_id": 327146,
                             "tdb_object_name": "Harpy Totem"}, "a3"), Outcome.SUCCESS, "credit", totem)
    assert learned.spawns(2175, "GAMEOBJECT", 327146)[0]["name"] == "Harpy Totem"
    # an object used before its entry is known is found again by name
    campfire = state(mouseover={"name": "Campfire"})
    memory.experience.finish(attempt(campfire, "OBJECT_USE", {}, "a4"), Outcome.SUCCESS, "credit", campfire)
    assert learned.spawns(2175, "GAMEOBJECT", None, "campfire")


def test_quest_creature_memory_is_imported_once_and_followed(memory, tmp_path):
    creatures = QuestCreatureMemory(tmp_path / "qc.sqlite3")
    creatures.record_role(55639, "ENDER", name="Captain Garrick", npc_id=245394,
                          position={"x": 100., "y": 200., "instance_id": 2175})
    learned = memory.experience.learned
    assert learned.attach_creature_memory(creatures) > 0
    assert learned.attach_creature_memory(creatures) == 0          # history imported once
    assert learned.spawns(2175, "CREATURE", 245394)[0]["seen_count"] == 1
    creatures.record_role(55639, "GIVER", name="Alaria", npc_id=100,
                          position={"x": 21., "y": 31., "instance_id": 2175})
    roles = {(r["npc_id"], r["role"]) for r in learned.quest_roles(55639)}
    assert roles == {(245394, "QUEST_ENDER"), (100, "QUEST_STARTER")}


def test_a_quest_without_tdb_ender_gets_the_learned_one_and_its_place(memory, tmp_path):
    """Live: 55639's ender (Captain Garrick 245394) has no TDB relation and
    no TDB spawn; the learned row must route the hand-in."""
    creatures = QuestCreatureMemory(tmp_path / "qc.sqlite3")
    creatures.record_role(55639, "ENDER", name="Captain Garrick", npc_id=245394,
                          position={"x": 400., "y": 250., "instance_id": 2175})
    memory.experience.learned.attach_creature_memory(creatures)
    now = state(active_quests=[{"quest_id": 55639, "is_complete": True, "objectives": []}])
    snapshot = memory.knowledge.snapshot(now, 1)
    quest = snapshot["quests"]["55639"]
    assert {"npc_id": 245394, "role": "QUEST_ENDER"}.items() <= quest["quest_roles"][0].items()
    assert quest["turnin_candidates"][0]["name"] == "Captain Garrick"
    spawn = next(s for s in quest["spawn_candidates"] if s["role"] == "QUEST_ENDER")
    assert spawn["source"] == "LEARNED_SPAWN" and (spawn["x"], spawn["y"]) == (400., 250.)
    region = role_region({**now, "reference_knowledge": snapshot}, 55639, "QUEST_ENDER")
    assert region["source"] == "LEARNED_SPAWN" and region["x"] == 400. and region["require_navmesh"]


def test_a_live_confirmed_phased_tdb_spawn_is_a_destination(tmp_path):
    """Real TDB 2026-10-10: Henry Garrick's (156859) spawn has a PhaseId; the
    live phase is unknown, so the row was dropped although the agent had
    talked to him right there."""
    from wowbot.agent.tdb_locations import _spawn_regions
    spawn = {"spawn_id": 5, "entity_kind": "CREATURE", "entry": 156859, "role": "QUEST_ENDER",
             "world_map_id": 2175, "x": 120., "y": 210., "z": 5., "context": {"PhaseId": 13305}}
    now = state(phase=None)
    assert _spawn_regions(now, {"spawn_candidates": [spawn]}, lambda s: True) == []
    confirmed = merge_spawns([spawn], [{"spawn_id": "learned:x", "x": 121., "y": 211.,
                                        "seen_count": 2, "last_seen": 1., "source": "LEARNED_SPAWN"}])
    regions = _spawn_regions(now, {"spawn_candidates": confirmed}, lambda s: True)
    assert len(regions) == 1 and regions[0]["source"] == "TDB_SPAWN" and regions[0]["x"] == 120.


def test_a_nameless_loot_observation_joins_the_named_place(world):
    """Live 2026-10-10: LOOT_VERIFIED rows had no target name and became a
    second, nameless Murloc Spearhunter place next to the COMBAT one."""
    world.record_spawn("CREATURE", 150228, "Murloc Spearhunter", {**PLAYER, "x": -353., "y": -2606.})
    world.record_spawn("CREATURE", 150228, "", {**PLAYER, "x": -352., "y": -2607.})
    rows = world.spawns(2175, "CREATURE", 150228)
    assert len(rows) == 1 and rows[0]["seen_count"] == 2 and rows[0]["name"] == "Murloc Spearhunter"


def test_the_quest_area_sweep_walks_the_tdb_quest_poi_polygon():
    """User 2026-10-10: walk the area the quest POI points outline, not the
    spawn points.  Murloc Mania (55122) objective 0, real TDB polygon."""
    from wowbot.agent.visual_search_planning import VisualSearchPlanningPolicy
    from wowbot.agent.tdb_locations import _inside
    polygon = [{"x": x, "y": y, "z": z} for x, y, z in (
        (-382, -2620, 9), (-354, -2609, 8), (-311, -2589, 19), (-318, -2484, 14),
        (-396, -2489, 13), (-400, -2521, 15), (-401, -2604, 7))]
    pois = [{"poi_id": "55122:0:0", "objective_index": -1, "world_map_id": 2175, "ui_map_id": 1409,
             "points": [{"x": -423, "y": -2611, "z": 1}], "conditions": {}},
            {"poi_id": "55122:0:1", "objective_index": 0, "objective_id": 390721,
             "world_map_id": 2175, "ui_map_id": 1409, "points": polygon,
             "conditions": {"PlayerConditionID": 0, "NavigationPlayerConditionID": 0}}]
    state = {"map_id": 1409,
             "active_quests": [{"quest_id": 55122, "is_complete": False, "objectives": [
                 {"type": "COLLECT", "description": "0/6 First Aid Kits", "is_complete": False}]}],
             "player_world_position": {"coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                       "x": -370., "y": -2600.},
             "quest_locations": [{"quest_id": 55122, "map_id": 1409, "x": .6, "y": .8,
                                  "world_position": {"coordinate_space": "WORLD_YARDS",
                                                     "instance_id": 2175, "ui_map_id": 1409,
                                                     "x": -360., "y": -2560.}}],
             "reference_knowledge": {"quests": {"55122": {"pois": pois}}}}
    area = VisualSearchPlanningPolicy.active_quest_area(state)["search_area"]
    assert area["region_source"] == "TDB_QUEST_POI_POLYGON"
    cells = area["coverage_points"]
    assert 8 <= len(cells) <= 25
    assert all(_inside(p["x"], p["y"], [{"x": v["x"], "y": v["y"]} for v in polygon]) for p in cells)
    assert all("z" not in p for p in cells)        # 7..19 yd heights: own floor, no guessed z
    # the turn-in point (index -1) is not part of the area
    assert not any(abs(p["x"]+423) < 1 and abs(p["y"]+2611) < 1 for p in cells)
    # a finished objective's polygon is not walked
    state["active_quests"][0]["objectives"][0]["is_complete"] = True
    state["active_quests"][0]["objectives"].append({"type": "TALK", "is_complete": False})
    assert VisualSearchPlanningPolicy.objective_poi_points(state, "55122", state["active_quests"][0]) == []


def test_the_learned_file_is_a_second_tdb_with_the_same_tables(world, tmp_path):
    """User 2026-10-11: save what is learned the way the TDB stores it, in a
    separate file (the original TDB stays untouched)."""
    import sqlite3
    from wowbot.agent.learned_world import GUID_BASE, LEARNED_BUILD, TDB_TABLES
    world.record_spawn("CREATURE", 245394, "Captain Garrick", PLAYER)
    world.record_role("CREATURE", 245394, 55639, "QUEST_ENDER", "Captain Garrick")
    db = sqlite3.connect(world.path)
    guid, entry, build = db.execute("SELECT guid, id, VerifiedBuild FROM creature").fetchone()
    assert int(guid) > GUID_BASE and entry == 245394 and build == LEARNED_BUILD
    assert db.execute("SELECT id, quest, VerifiedBuild FROM creature_questender").fetchall() == \
        [(245394, 55639, LEARNED_BUILD)]
    # Column for column the TDB 1210.26091 layout.
    columns = [row[1] for row in db.execute("PRAGMA table_info(quest_poi_points)")]
    assert columns == ["QuestID", "Idx1", "Idx2", "X", "Y", "Z", "VerifiedBuild"]
    assert "position_x" in [row[1] for row in db.execute("PRAGMA table_info(creature)")]
    db.close()


def test_rows_of_the_first_learned_version_move_into_the_learned_tdb(tmp_path):
    from wowbot.agent.learned_world import LearnedWorld
    entities = EntityMemory(tmp_path / "entity_memory.sqlite3")
    with entities._connect() as old:
        old.executescript("""
            CREATE TABLE learned_spawn (kind TEXT, entry INTEGER, name TEXT, world_map_id INTEGER,
                cell_x INTEGER, cell_y INTEGER, x REAL, y REAL, z REAL, phase TEXT, seen_count INTEGER,
                first_seen REAL, last_seen REAL, source TEXT);
            INSERT INTO learned_spawn VALUES ('CREATURE', 156626, 'Lady Jaina Proudmoore', 2175, 0, 0,
                -434, -2611, NULL, NULL, 6, 1, 2, 'INTERACT_VERIFIED');
            CREATE TABLE learned_quest_role (kind TEXT, entry INTEGER, quest_id INTEGER, role TEXT,
                name TEXT, seen_count INTEGER, last_seen REAL, source TEXT);
            INSERT INTO learned_quest_role VALUES ('CREATURE', 156626, 55122, 'QUEST_ENDER',
                'Lady Jaina Proudmoore', 1, 2, 'QUEST_CREATURE_MEMORY');
            CREATE TABLE learned_meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO learned_meta VALUES ('quest_creature_import', '147');""")
    learned = LearnedWorld(tmp_path / "tdb_learned.sqlite3", legacy_entities=entities)
    try:
        jaina = learned.spawns(2175, "CREATURE", 156626)
        assert len(jaina) == 1 and jaina[0]["seen_count"] == 6
        assert {(r["npc_id"], r["role"]) for r in learned.quest_roles(55122)} == {(156626, "QUEST_ENDER")}
        assert learned._rows("SELECT value FROM learned_meta WHERE key='quest_creature_import'") == [("147",)]
        again = LearnedWorld(tmp_path / "tdb_learned.sqlite3", legacy_entities=entities)
        assert again.spawns(2175, "CREATURE", 156626)[0]["seen_count"] == 6   # imported once
        again.close()
    finally:
        learned.close()
        entities.close()


def test_a_closed_blue_minimap_area_becomes_a_saved_poi_polygon_the_sweep_uses(world):
    """User 2026-10-10: a quest without a TDB POI gets one from vision."""
    from wowbot.agent.quest_area_memory import QuestAreaMemory
    from wowbot.agent.visual_search_planning import VisualSearchPlanningPolicy
    areas = QuestAreaMemory()
    areas.cells["999"] = {(x, y) for x in range(-100, -90) for y in range(-650, -640)}
    assert areas.polygon("999") == []                 # outline never seen closed
    areas.closed_seen["999"] = True
    polygon = areas.polygon("999")
    assert len(polygon) >= 4
    assert world.record_quest_area(999, 2175, 1409, polygon, 100)
    assert not world.record_quest_area(999, 2175, 1409, polygon[:3], 50)      # never shrinks
    saved = world.quest_areas(999, 2175)
    assert len(saved) == 1 and len(saved[0]["points"]) == len(polygon)
    state = {"map_id": 1409,
             "player_world_position": {"coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                       "x": -380., "y": -2580.},
             "reference_knowledge": {"quests": {"999": {"pois": [], "learned_areas": saved}}}}
    quest = {"quest_id": 999, "objectives": [{"objective_id": "999:0", "is_complete": False}]}
    assert VisualSearchPlanningPolicy.objective_poi_polygons(state, "999", quest) == [saved[0]["points"]]
